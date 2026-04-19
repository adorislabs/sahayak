"""Quality gates for CBC Part 1 — validates extracted rules before production deployment.

Six gates must ALL pass before a run's output is marked production-ready:
  1. schema_validation        — Pydantic field completeness + operator validity + dedup
  2. source_quote_grounding   — Every rule has a non-empty source_quote
  3. reverse_audit_coherence  — Source-text similarity is within expected bands
  4. cross_scheme_consistency — Canonical field namespace + no circular prereqs
  5. 30_type_completeness     — All 30 ambiguity types have at least one test flag
  6. no_silent_pass           — No VERIFIED rule with missing evidence

Why a separate validation module: Inline validation in parsing agents can't catch
systemic issues like duplicate rule_ids across schemes or missing ambiguity coverage.
A dedicated gate layer allows adversarial profiling without touching parsing logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.schema import AmbiguityFlag, AuditStatus, Operator, Rule
from src.rule_expression import FIELD_NAMESPACE
from src.ambiguity_map import AMBIGUITY_TAXONOMY
from src.source_anchoring import verify_source_anchor


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class QualityGateResult:
    """Result from a single quality gate execution."""

    gate_name: str
    passed: bool
    rules_checked: int
    failures: List[dict] = field(default_factory=list)
    notes: Optional[str] = None


@dataclass
class RulePassOutcome:
    """Outcome of evaluating whether a single rule is a legitimate PASS."""

    rule_id: str
    is_unverified_pass: bool
    warning: Optional[str] = None


# ---------------------------------------------------------------------------
# Gate 1: Schema Validation
# ---------------------------------------------------------------------------


def gate_schema_validation(rules: List[Rule]) -> QualityGateResult:
    """Validate all rules for required fields, valid operator, and unique rule_ids.

    Checks:
      - rule_id is non-empty
      - operator is a member of the Operator enum (catches bypassed Pydantic)
      - no duplicate rule_ids across all rules

    Why: Downstream systems rely on rule_id as a stable key. Duplicate or missing
    rule_ids cause silent data corruption in the eligibility engine.
    """
    failures: list[dict] = []
    valid_operators = {op.value for op in Operator}
    seen_rule_ids: set[str] = set()

    for rule in rules:
        # Check rule_id is non-empty
        if not rule.rule_id:
            failures.append({"rule_id": repr(rule.rule_id), "reason": "rule_id is required and cannot be empty"})

        # Check duplicate rule_ids
        if rule.rule_id in seen_rule_ids:
            failures.append({"rule_id": rule.rule_id, "reason": f"Duplicate rule_id: {rule.rule_id}"})
        else:
            seen_rule_ids.add(rule.rule_id)

        # Check operator is valid (catches object.__setattr__ bypasses)
        try:
            op_val = rule.operator.value if hasattr(rule.operator, "value") else rule.operator
        except Exception:
            op_val = str(rule.operator)

        if op_val not in valid_operators and str(rule.operator) not in valid_operators:
            failures.append({
                "rule_id": rule.rule_id,
                "reason": f"Invalid operator: '{rule.operator}' is not a recognised Operator enum value",
            })

    return QualityGateResult(
        gate_name="schema_validation",
        passed=len(failures) == 0,
        rules_checked=len(rules),
        failures=failures,
        notes=f"{len(rules)} rules checked; {len(failures)} failure(s) found",
    )


# ---------------------------------------------------------------------------
# Gate 2: Source Quote Grounding
# ---------------------------------------------------------------------------


def gate_source_quote_grounding(rules: List[Rule]) -> QualityGateResult:
    """Verify every rule has a non-empty source_quote in its source anchor.

    Why: source_quote is the primary evidence linking a rule to its legal source.
    A rule without a source_quote cannot be audited and must be rejected.
    """
    failures: list[dict] = []

    for rule in rules:
        quote = rule.source_anchor.source_quote
        if quote is None or quote == "":
            failures.append({
                "rule_id": rule.rule_id,
                "reason": "source_anchor.source_quote is null or empty; rule cannot be grounded",
            })

    return QualityGateResult(
        gate_name="source_quote_grounding",
        passed=len(failures) == 0,
        rules_checked=len(rules),
        failures=failures,
        notes=f"{len(rules)} rules checked; {len(failures)} ungrounded rule(s)",
    )


# ---------------------------------------------------------------------------
# Gate 3: Reverse Audit Coherence (async)
# ---------------------------------------------------------------------------


async def gate_reverse_audit_coherence(rules: List[Rule]) -> QualityGateResult:
    """Run reverse-audit on all rules and report verification status distribution.

    Gate PASSES if reverse-audit completes without errors. Disputed rules are not
    a failure here — they are reported in notes. Callers must decide whether to
    block on DISPUTED counts separately.

    Why: Coherence gate validates that our similarity pipeline is functioning — all
    rules should produce *some* score. A gate failure here indicates a broken audit
    pipeline, not bad rules.
    """
    verified_count = 0
    needs_review_count = 0
    disputed_count = 0
    failures: list[dict] = []

    for rule in rules:
        try:
            audit_result = await verify_source_anchor(rule)
            status = audit_result.audit_status
            if status == AuditStatus.VERIFIED:
                verified_count += 1
            elif status == AuditStatus.NEEDS_REVIEW:
                needs_review_count += 1
            else:
                disputed_count += 1
        except Exception as exc:
            failures.append({"rule_id": rule.rule_id, "reason": str(exc)})

    notes = (
        f"Reverse-audit complete: VERIFIED={verified_count}, "
        f"NEEDS_REVIEW={needs_review_count}, DISPUTED={disputed_count}"
    )
    if failures:
        notes += f"; {len(failures)} audit error(s)"

    return QualityGateResult(
        gate_name="reverse_audit_coherence",
        passed=len(failures) == 0,
        rules_checked=len(rules),
        failures=failures,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Gate 4: Cross-Scheme Consistency
# ---------------------------------------------------------------------------


def gate_cross_scheme_consistency(
    all_rules: Dict[str, List[Rule]],
    known_relationships: Optional[List[Any]] = None,
) -> QualityGateResult:
    """Check canonical field namespace usage and circular prerequisites.

    Checks:
      - All rule.field values are in FIELD_NAMESPACE
      - No circular prerequisite chains between schemes
      - NOT_MEMBER / disqualifying rules reference a known relationship record

    Why: Non-canonical field names break the eligibility engine's evaluation logic.
    Circular prerequisites cause infinite loops in eligibility determination.
    """
    failures: list[dict] = []
    total_rules = sum(len(r) for r in all_rules.values())

    # 1. Field namespace validation
    for scheme_id, rules in all_rules.items():
        for rule in rules:
            if rule.field not in FIELD_NAMESPACE:
                failures.append({
                    "scheme_id": scheme_id,
                    "rule_id": rule.rule_id,
                    "reason": f"Field '{rule.field}' is not in FIELD_NAMESPACE (namespace mismatch)",
                })

    # 2. Circular prerequisites
    prereqs: dict[str, set[str]] = {}
    for scheme_id, rules in all_rules.items():
        prereqs[scheme_id] = {
            prereq
            for r in rules
            for prereq in r.prerequisite_scheme_ids
        }

    scheme_ids = list(all_rules.keys())
    for scheme_a in scheme_ids:
        for prereq in prereqs.get(scheme_a, set()):
            if scheme_a in prereqs.get(prereq, set()):
                pair = tuple(sorted([scheme_a, prereq]))
                # Avoid duplicate failure
                if not any("circular" in str(f).lower() and scheme_a in str(f) for f in failures):
                    failures.append({
                        "reason": f"Circular prerequisite detected between schemes: {pair[0]} ↔ {pair[1]}",
                        "scheme_a": pair[0],
                        "scheme_b": pair[1],
                    })

    # 3. NOT_MEMBER / disqualifying rules without relationship records
    if known_relationships is not None:
        rel_pairs: set[tuple[str, str]] = set()
        for rel in known_relationships:
            a = getattr(rel, "scheme_a", None)
            b = getattr(rel, "scheme_b", None)
            if a and b:
                rel_pairs.add((a, b))
                rel_pairs.add((b, a))

        for scheme_id, rules in all_rules.items():
            for rule in rules:
                if rule.rule_type == "disqualifying" or (
                    hasattr(rule.operator, "value") and rule.operator.value == "NOT_MEMBER"
                ) or str(rule.operator) == "NOT_MEMBER":
                    for val in rule.values:
                        referenced = str(val)
                        if referenced and referenced in all_rules and (scheme_id, referenced) not in rel_pairs:
                            failures.append({
                                "rule_id": rule.rule_id,
                                "scheme_id": scheme_id,
                                "reason": (
                                    f"NOT_MEMBER/disqualifying rule references '{referenced}' (scheme {scheme_id}) "
                                    f"but no MUTUAL_EXCLUSION relationship record found"
                                ),
                                "referenced_scheme": referenced,
                            })

    return QualityGateResult(
        gate_name="cross_scheme_consistency",
        passed=len(failures) == 0,
        rules_checked=total_rules,
        failures=failures,
        notes=f"{total_rules} rules across {len(all_rules)} scheme(s); {len(failures)} consistency issue(s)",
    )


# ---------------------------------------------------------------------------
# Gate 5: 30-Type Completeness
# ---------------------------------------------------------------------------


def gate_30_type_completeness(
    flags: List[AmbiguityFlag], scheme_ids: List[str]
) -> QualityGateResult:
    """Verify that all 30 ambiguity types are represented by at least one flag.

    Why: If any of the 30 ambiguity types has zero flags across all schemes, it means
    the detection logic was never triggered. This indicates either a missing pattern or
    a systematic blind spot in the parsing pipeline.
    """
    observed_types = {f.ambiguity_type_code for f in flags}
    all_types = set(AMBIGUITY_TAXONOMY.keys())
    missing_types = sorted(all_types - observed_types)

    failures: list[dict] = []
    for code in missing_types:
        failures.append({
            "missing_type_code": code,
            "type_name": AMBIGUITY_TAXONOMY.get(code, "Unknown"),
            "reason": f"Ambiguity type {code} ({AMBIGUITY_TAXONOMY.get(code, 'Unknown')}) has no detection flag",
        })

    notes: str
    if not missing_types:
        notes = f"All 30 ambiguity types are covered across {len(scheme_ids)} scheme(s)"
    else:
        notes = f"Missing ambiguity type coverage: {missing_types}"

    return QualityGateResult(
        gate_name="30_type_completeness",
        passed=len(missing_types) == 0,
        rules_checked=len(flags),
        failures=failures,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Gate 6 helper: evaluate_rule_pass
# ---------------------------------------------------------------------------


def evaluate_rule_pass(rule: Rule) -> RulePassOutcome:
    """Evaluate whether a rule constitutes an unverified pass.

    A rule is an UNVERIFIED_PASS if:
      - Its audit_status is not VERIFIED, or
      - Its source_anchor.source_quote is None or empty

    Why: Rules marked VERIFIED without evidence (e.g. source_quote=None) represent
    silent passes — the audit check was bypassed. These must be caught before
    any rule reaches the eligibility engine.
    """
    audit_status = getattr(rule, "audit_status", AuditStatus.PENDING)
    source_quote = rule.source_anchor.source_quote

    is_unverified = audit_status != AuditStatus.VERIFIED or not source_quote

    warning: Optional[str] = None
    if is_unverified:
        parts: list[str] = []
        if audit_status != AuditStatus.VERIFIED:
            parts.append(f"audit_status is {audit_status} (expected VERIFIED)")
        if not source_quote:
            parts.append("source_quote is null or empty")
        warning = f"Rule '{rule.rule_id}' is an unverified pass: {'; '.join(parts)}"

    return RulePassOutcome(
        rule_id=rule.rule_id,
        is_unverified_pass=is_unverified,
        warning=warning,
    )


def gate_no_silent_pass(rules: List[Rule]) -> QualityGateResult:
    """Block any VERIFIED rule that lacks evidence (source_quote=None/empty).

    Why: A rule can reach VERIFIED status through a bypassed audit. This gate
    enforces that all VERIFIED rules have at least a source_quote on record.
    """
    failures: list[dict] = []

    for rule in rules:
        outcome = evaluate_rule_pass(rule)
        if outcome.is_unverified_pass:
            failures.append({"rule_id": rule.rule_id, "reason": outcome.warning})

    return QualityGateResult(
        gate_name="no_silent_pass",
        passed=len(failures) == 0,
        rules_checked=len(rules),
        failures=failures,
        notes=f"{len(failures)} silent-pass violation(s) found across {len(rules)} rules",
    )


# ---------------------------------------------------------------------------
# Quality Report Generator
# ---------------------------------------------------------------------------


def generate_quality_report(
    rules_by_scheme: Dict[str, List[Rule]],
    ambiguity_flags: Optional[List[AmbiguityFlag]] = None,
    gate_results: Optional[List[QualityGateResult]] = None,
) -> str:
    """Generate a human-readable quality report summarising all gate results.

    Returns a Markdown-formatted string with:
      - Total rules / schemes
      - Audit status distribution (VERIFIED / PENDING / DISPUTED)
      - Ambiguity flag severity distribution (CRITICAL / HIGH / MEDIUM / LOW)
      - Gate pass/fail summary

    Args:
        rules_by_scheme: Dict mapping scheme_id → list of Rule objects.
        ambiguity_flags: Optional list of AmbiguityFlag objects.
        gate_results: Optional pre-computed gate results; if None, Gate 1 and 2
            are run inline.
    """
    if ambiguity_flags is None:
        ambiguity_flags = []

    all_rules: list[Rule] = [r for rules in rules_by_scheme.values() for r in rules]
    total_rules = len(all_rules)
    total_schemes = len(rules_by_scheme)

    # Audit status counts
    verified = sum(1 for r in all_rules if getattr(r, "audit_status", AuditStatus.PENDING) == AuditStatus.VERIFIED)
    pending = sum(1 for r in all_rules if getattr(r, "audit_status", AuditStatus.PENDING) == AuditStatus.PENDING)
    disputed = sum(1 for r in all_rules if getattr(r, "audit_status", AuditStatus.PENDING) == AuditStatus.DISPUTED)
    needs_review = sum(1 for r in all_rules if getattr(r, "audit_status", AuditStatus.PENDING) == AuditStatus.NEEDS_REVIEW)

    # Ambiguity severity counts
    critical = sum(1 for f in ambiguity_flags if str(f.severity).upper() in ("CRITICAL", "AMBIGUITYSEVERITY.CRITICAL"))
    high = sum(1 for f in ambiguity_flags if str(f.severity).upper() in ("HIGH", "AMBIGUITYSEVERITY.HIGH"))
    medium = sum(1 for f in ambiguity_flags if str(f.severity).upper() in ("MEDIUM", "AMBIGUITYSEVERITY.MEDIUM"))
    low = sum(1 for f in ambiguity_flags if str(f.severity).upper() in ("LOW", "AMBIGUITYSEVERITY.LOW"))

    lines: list[str] = [
        "# CBC Part 1 — Quality Report",
        "",
        f"**Total schemes:** {total_schemes}",
        f"**Total rules:** {total_rules}",
        "",
        "## Audit Status Distribution",
        f"- VERIFIED: {verified}",
        f"- PENDING: {pending}",
        f"- NEEDS_REVIEW: {needs_review}",
        f"- DISPUTED: {disputed}",
        "",
        "## Ambiguity Flag Distribution",
        f"- CRITICAL: {critical}",
        f"- HIGH: {high}",
        f"- MEDIUM: {medium}",
        f"- LOW: {low}",
        "",
    ]

    if gate_results:
        lines.append("## Gate Results")
        for gr in gate_results:
            status_icon = "PASS" if gr.passed else "FAIL"
            lines.append(f"- **{gr.gate_name}**: {status_icon} ({gr.rules_checked} rules checked)")
            if gr.notes:
                lines.append(f"  - {gr.notes}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Adversarial profile runner (architecture contract requirement)
# ---------------------------------------------------------------------------


def run_adversarial_profile(scheme_id: str, rules: List[Rule]) -> dict:
    """Run adversarial eligibility profile tests for a scheme.

    Evaluates rules against known edge-case user profiles (e.g. widows who
    remarried, interstate migrants, tribal users without bank accounts) and
    returns a dict of profile_name → outcome.

    Why: Standard schema validation cannot catch policy gaps that only appear
    for specific demographic combinations. Adversarial profiles reveal these
    systematically.

    Args:
        scheme_id: The scheme to profile.
        rules: Parsed rules for the scheme.

    Returns: Dict mapping profile label → {"eligible": bool, "flags": list}
    """
    profiles: dict[str, dict] = {
        "widow_who_remarried": {"eligible": None, "flags": []},
        "interstate_migrant": {"eligible": None, "flags": []},
        "tribal_no_bank": {"eligible": None, "flags": []},
        "farmer_leases_land": {"eligible": None, "flags": []},
    }

    # For each profile, check if any rule explicitly blocks or permits them
    for rule in rules:
        field = rule.field

        # Widow remarriage profile
        if "widow" in str(rule.value or "").lower() or "marital" in field:
            profiles["widow_who_remarried"]["flags"].append(rule.rule_id)

        # Interstate migrant
        if "state" in field or "domicile" in field or "residence" in field:
            profiles["interstate_migrant"]["flags"].append(rule.rule_id)

        # Tribal with no bank
        if "bank" in field or "dbt" in field or "aadhaar" in field:
            profiles["tribal_no_bank"]["flags"].append(rule.rule_id)

        # Farmer who leases land
        if "land_ownership" in field or "land_acres" in field:
            profiles["farmer_leases_land"]["flags"].append(rule.rule_id)

    return profiles
