"""Core 4-phase evaluation engine for the CBC matching engine.

Phase A: Disqualifying rules (short-circuit → DISQUALIFIED)
Phase B: Prerequisite rules (short-circuit → REQUIRES_PREREQUISITE)
Phase C: Eligibility rules with AND/OR group logic
Phase D: Administrative discretion rules (warnings only)

Status taxonomy (in priority order):
  INSUFFICIENT_DATA     – profile completeness < 60%
  DISQUALIFIED          – Phase A fired
  REQUIRES_PREREQUISITE – Phase B failed
  ELIGIBLE_WITH_CAVEATS – all C rules pass + CRITICAL ambiguity
  ELIGIBLE              – all C rules pass, no CRITICAL ambiguity
  NEAR_MISS             – 0 < fail_count < NEAR_MISS_MAX_FAILED_RULES
  INELIGIBLE            – fail_count >= NEAR_MISS_MAX_FAILED_RULES
  PARTIAL               – all UNDETERMINED (no PASS or FAIL)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.config import (
    ENGINE_VERSION,
    NEAR_MISS_MAX_FAILED_RULES,
    PROFILE_COMPLETE_THRESHOLD,
    UNVERIFIED_PASS_SCORE,
)
from src.exceptions import EvaluationError, InvalidProfileError, RuleBaseError
from src.matching.gap_analysis import generate_gap_analysis
from src.matching.loader import SchemeRuleSet, load_ambiguity_map, load_relationship_matrix, load_rule_base
from src.matching.operators import evaluate_operator
from src.matching.output import MatchingResult, assemble_matching_result
from src.matching.scoring import compute_confidence_breakdown
from src.matching.sequencing import compute_application_sequence
from src.schema import AuditStatus, Operator, Rule

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RuleEvaluation:
    """Result of evaluating a single rule against a profile."""

    rule_id: str
    scheme_id: str
    field: str
    operator: str
    rule_value: Any
    user_value: Any
    outcome: str           # PASS / UNVERIFIED_PASS / FAIL / UNDETERMINED
    outcome_score: Optional[float]
    display_text: str
    source_quote: str
    source_url: str
    audit_status: str
    undetermined_reason: Optional[str]
    ambiguity_notes: list[str]


@dataclass
class GroupEvaluation:
    """Result of evaluating a rule group (AND/OR logic)."""

    group_id: str
    logic_operator: str    # AND / OR
    rule_ids: list[str]
    outcome: str           # PASS / FAIL / UNDETERMINED


@dataclass
class RuleTraceEntry:
    """Audit trail entry for a single rule."""

    rule_id: str
    excluded: bool
    phase: str             # A_DISQUALIFYING / B_PREREQUISITE / C_ELIGIBILITY / D_DISCRETION
    outcome: Optional[str] = None


@dataclass
class DisqualificationResult:
    """Result of Phase A evaluation."""

    fired: bool
    rule_id: str


@dataclass
class PrerequisiteResult:
    """Result of Phase B evaluation."""

    all_met: bool
    unmet_prerequisites: list[Any]
    met_prerequisites: list[Any]


@dataclass
class SchemeDetermination:
    """Complete evaluation result for one scheme against one profile."""

    scheme_id: str
    scheme_name: str
    status: str
    rule_evaluations: list[RuleEvaluation]
    group_evaluations: list[GroupEvaluation]
    disqualification: Optional[DisqualificationResult]
    prerequisites: Optional[PrerequisiteResult]
    discretion_warnings: list[str]
    confidence: Any           # ConfidenceBreakdown
    gap_analysis: Optional[Any]
    rule_trace: list[RuleTraceEntry]
    state_overrides_applied: list[str]
    excluded_rules_count: int
    scheme: Any               # Scheme object (for ministry, etc.)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_effective_rule_value(rule: Rule) -> Any:
    """Return a display-friendly rule value for storing in RuleEvaluation."""
    if rule.values:
        return rule.values
    if rule.value_min is not None or rule.value_max is not None:
        return [rule.value_min, rule.value_max]
    return rule.value


def _evaluate_single_rule(
    profile: Any,
    rule: Rule,
) -> RuleEvaluation:
    """Evaluate one rule against the profile. Returns RuleEvaluation.

    Raises:
        EvaluationError: If the evaluation itself fails unexpectedly.
    """
    from src.matching.profile import UserProfile  # avoid circular import at module level

    user_value = None
    if hasattr(profile, "get_field_value"):
        user_value = profile.get_field_value(rule.field)

    try:
        rule_values_arg = rule.values if rule.values else None
        result = evaluate_operator(
            rule.operator,
            user_value,
            rule.value,
            rule_value_min=rule.value_min,
            rule_value_max=rule.value_max,
            rule_values=rule_values_arg,
        )
    except Exception as exc:
        raise EvaluationError(rule_id=rule.rule_id, reason=str(exc)) from exc

    # Determine outcome
    if result is None:
        outcome = "UNDETERMINED"
        outcome_score = None
        undetermined_reason = "Field not provided" if user_value is None else "Cannot determine"
    elif result:
        if rule.audit_status in (AuditStatus.PENDING,):
            outcome = "UNVERIFIED_PASS"
            outcome_score = UNVERIFIED_PASS_SCORE
        else:
            outcome = "PASS"
            outcome_score = 1.0
        undetermined_reason = None
    else:
        outcome = "FAIL"
        outcome_score = 0.0
        undetermined_reason = None

    # Collect ambiguity note IDs from the rule's own flags
    ambiguity_notes = [f.ambiguity_id for f in (rule.ambiguity_flags or [])]

    return RuleEvaluation(
        rule_id=rule.rule_id,
        scheme_id=rule.scheme_id,
        field=rule.field,
        operator=rule.operator.value if hasattr(rule.operator, "value") else str(rule.operator),
        rule_value=_get_effective_rule_value(rule),
        user_value=user_value,
        outcome=outcome,
        outcome_score=outcome_score,
        display_text=rule.display_text or "",
        source_quote=(
            rule.source_anchor.source_quote if rule.source_anchor else ""
        ),
        source_url=(
            rule.source_anchor.source_url if rule.source_anchor else ""
        ),
        audit_status=rule.audit_status.value if hasattr(rule.audit_status, "value") else str(rule.audit_status),
        undetermined_reason=undetermined_reason,
        ambiguity_notes=ambiguity_notes,
    )


def _evaluate_group_outcome(
    logic_operator: str,
    evaluations: list[RuleEvaluation],
) -> str:
    """Compute AND/OR group outcome from individual rule evaluations.

    AND: all PASS/UNVERIFIED_PASS → PASS; any FAIL → FAIL; else UNDETERMINED
    OR:  any PASS/UNVERIFIED_PASS → PASS; all FAIL → FAIL; else UNDETERMINED
    """
    outcomes = [e.outcome for e in evaluations]

    if logic_operator.upper() == "OR":
        if any(o in ("PASS", "UNVERIFIED_PASS") for o in outcomes):
            return "PASS"
        if all(o == "FAIL" for o in outcomes):
            return "FAIL"
        return "UNDETERMINED"
    else:  # AND (default)
        if all(o in ("PASS", "UNVERIFIED_PASS") for o in outcomes):
            return "PASS"
        if any(o == "FAIL" for o in outcomes):
            return "FAIL"
        return "UNDETERMINED"


def _compute_required_fields(rules: list[Rule]) -> set[str]:
    """Collect all field paths referenced by a list of rules."""
    return {r.field for r in rules if r.field}


def _has_critical_ambiguity_on_passing_rules(
    evaluations: list[RuleEvaluation],
    rules_by_id: dict[str, Rule],
) -> bool:
    """Check if any passing/unverified rule has CRITICAL ambiguity flags."""
    for ev in evaluations:
        if ev.outcome not in ("PASS", "UNVERIFIED_PASS"):
            continue
        rule = rules_by_id.get(ev.rule_id)
        if rule is None:
            continue
        for flag in (rule.ambiguity_flags or []):
            severity = getattr(flag, "severity", None)
            sev_str = severity.value if hasattr(severity, "value") else str(severity)
            if sev_str == "CRITICAL":
                return True
    return False


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------


async def evaluate_scheme(
    profile: Any,
    ruleset: SchemeRuleSet,
    ambiguity_flags: list[Any],
) -> SchemeDetermination:
    """Evaluate a profile against one scheme's rule set.

    Phases:
      A — Disqualifying rules (short-circuit)
      B — Prerequisite rules (short-circuit)
      C — Eligibility rules (AND/OR group logic)
      D — Administrative discretion rules (warnings only)

    Args:
        profile: UserProfile with get_field_value() and get_populated_fields().
        ruleset: SchemeRuleSet with active_rules.
        ambiguity_flags: Global ambiguity flag list (for confidence scoring).

    Returns:
        SchemeDetermination with full audit trail.
    """
    active_rules = ruleset.active_rules
    scheme = ruleset.scheme
    scheme_id = scheme.scheme_id
    scheme_name = scheme.scheme_name

    # Build lookup dict for quick access
    rules_by_id: dict[str, Rule] = {r.rule_id: r for r in active_rules}

    # Separate by rule_type
    dis_rules: list[Rule] = []
    pre_rules: list[Rule] = []
    elig_rules: list[Rule] = []
    disc_rules: list[Rule] = []

    _RULE_TYPE_PHASE = {
        "disqualifying": ("A_DISQUALIFYING", dis_rules),
        "prerequisite": ("B_PREREQUISITE", pre_rules),
        "eligibility": ("C_ELIGIBILITY", elig_rules),
        "admin_discretion": ("D_DISCRETION", disc_rules),
        "administrative_discretion": ("D_DISCRETION", disc_rules),
        "discretion": ("D_DISCRETION", disc_rules),
    }

    for rule in active_rules:
        rtype = (rule.rule_type or "eligibility").lower().strip()
        if rtype in _RULE_TYPE_PHASE:
            _RULE_TYPE_PHASE[rtype][1].append(rule)
        else:
            elig_rules.append(rule)

    # Initialize trace entries for active (non-excluded) rules
    rule_trace: list[RuleTraceEntry] = []
    for rule in active_rules:
        rtype = (rule.rule_type or "eligibility").lower().strip()
        phase_map = {
            "disqualifying": "A_DISQUALIFYING",
            "prerequisite": "B_PREREQUISITE",
            "eligibility": "C_ELIGIBILITY",
            "admin_discretion": "D_DISCRETION",
            "administrative_discretion": "D_DISCRETION",
            "discretion": "D_DISCRETION",
        }
        phase = phase_map.get(rtype, "C_ELIGIBILITY")
        rule_trace.append(RuleTraceEntry(rule_id=rule.rule_id, excluded=False, phase=phase))

    # Add synthetic trace entries for excluded rules
    for n in range(ruleset.excluded_rules_count):
        rule_trace.append(
            RuleTraceEntry(
                rule_id=f"EXCLUDED-{scheme_id}-{n+1:03d}",
                excluded=True,
                phase="C_ELIGIBILITY",
                outcome=None,
            )
        )

    trace_by_id: dict[str, RuleTraceEntry] = {t.rule_id: t for t in rule_trace}

    # Compute populated fields for confidence scoring later
    all_fields = _compute_required_fields(active_rules)
    populated_fields: set[str] = set()
    if hasattr(profile, "get_populated_fields"):
        populated_fields = profile.get_populated_fields()

    all_evaluations: list[RuleEvaluation] = []

    # -----------------------------------------------------------------------
    # Phase A — Disqualifying rules
    # -----------------------------------------------------------------------
    disqualification = DisqualificationResult(fired=False, rule_id="")

    for rule in dis_rules:
        try:
            ev = _evaluate_single_rule(profile, rule)
        except EvaluationError as e:
            logger.warning("EvaluationError in Phase A rule %s: %s", rule.rule_id, e.reason)
            ev = RuleEvaluation(
                rule_id=rule.rule_id,
                scheme_id=scheme_id,
                field=rule.field,
                operator=str(rule.operator),
                rule_value=rule.value,
                user_value=None,
                outcome="UNDETERMINED",
                outcome_score=None,
                display_text=rule.display_text or "",
                source_quote="",
                source_url="",
                audit_status=str(rule.audit_status),
                undetermined_reason=str(e.reason),
                ambiguity_notes=[],
            )
        except Exception as e:
            logger.warning("Unexpected error in Phase A rule %s: %s", rule.rule_id, e)
            continue

        all_evaluations.append(ev)
        if t := trace_by_id.get(rule.rule_id):
            t.outcome = ev.outcome

        if ev.outcome == "PASS":
            # Disqualifying rule matches → DISQUALIFIED
            disqualification = DisqualificationResult(fired=True, rule_id=rule.rule_id)
            confidence = compute_confidence_breakdown(
                all_evaluations, ambiguity_flags, all_fields, populated_fields
            )
            det = SchemeDetermination(
                scheme_id=scheme_id,
                scheme_name=scheme_name,
                status="DISQUALIFIED",
                rule_evaluations=all_evaluations,
                group_evaluations=[],
                disqualification=disqualification,
                prerequisites=PrerequisiteResult(all_met=True, unmet_prerequisites=[], met_prerequisites=[]),
                discretion_warnings=[],
                confidence=confidence,
                gap_analysis=None,
                rule_trace=rule_trace,
                state_overrides_applied=list(ruleset.state_overrides_applied),
                excluded_rules_count=ruleset.excluded_rules_count,
                scheme=scheme,
            )
            try:
                det.gap_analysis = generate_gap_analysis(det, [])
            except Exception as e:
                logger.warning("Gap analysis failed for %s: %s", scheme_id, e)
            return det

    # -----------------------------------------------------------------------
    # Phase A½ — Numeric-threshold disqualifying rules that FAILED are eligibility
    # barriers (e.g. income > cap).  Re-inject them into Phase C so they count
    # toward fail_count.  Rules that PASSED already fired → DISQUALIFIED above.
    # Rules that are UNDETERMINED are left as-is (no additional penalty).
    # -----------------------------------------------------------------------
    _NUMERIC_THRESHOLD_OPS: frozenset = frozenset({
        Operator.LTE, Operator.LT, Operator.GTE, Operator.GT, Operator.BETWEEN,
    })
    dis_fail_evals: list[RuleEvaluation] = []
    for ev in all_evaluations:
        if ev.outcome != "FAIL":
            continue
        rule = rules_by_id.get(ev.rule_id)
        if rule is None:
            continue
        if (rule.rule_type or "").lower().strip() == "disqualifying" and rule.operator in _NUMERIC_THRESHOLD_OPS:
            dis_fail_evals.append(ev)

    # -----------------------------------------------------------------------
    # Phase B — Prerequisite rules
    # -----------------------------------------------------------------------
    prerequisites = PrerequisiteResult(all_met=True, unmet_prerequisites=[], met_prerequisites=[])

    for rule in pre_rules:
        try:
            ev = _evaluate_single_rule(profile, rule)
        except EvaluationError as e:
            logger.warning("EvaluationError in Phase B rule %s: %s", rule.rule_id, e.reason)
            ev = RuleEvaluation(
                rule_id=rule.rule_id,
                scheme_id=scheme_id,
                field=rule.field,
                operator=str(rule.operator),
                rule_value=rule.value,
                user_value=None,
                outcome="UNDETERMINED",
                outcome_score=None,
                display_text=rule.display_text or "",
                source_quote="",
                source_url="",
                audit_status=str(rule.audit_status),
                undetermined_reason=str(e.reason),
                ambiguity_notes=[],
            )
        except Exception as e:
            logger.warning("Unexpected error in Phase B rule %s: %s", rule.rule_id, e)
            continue

        all_evaluations.append(ev)
        if t := trace_by_id.get(rule.rule_id):
            t.outcome = ev.outcome

        if ev.outcome in ("FAIL", "UNDETERMINED"):
            prerequisites.all_met = False
            prerequisites.unmet_prerequisites.append(rule.rule_id)
        else:
            prerequisites.met_prerequisites.append(rule.rule_id)

    if not prerequisites.all_met:
        confidence = compute_confidence_breakdown(
            all_evaluations, ambiguity_flags, all_fields, populated_fields
        )
        det = SchemeDetermination(
            scheme_id=scheme_id,
            scheme_name=scheme_name,
            status="REQUIRES_PREREQUISITE",
            rule_evaluations=all_evaluations,
            group_evaluations=[],
            disqualification=disqualification,
            prerequisites=prerequisites,
            discretion_warnings=[],
            confidence=confidence,
            gap_analysis=None,
            rule_trace=rule_trace,
            state_overrides_applied=list(ruleset.state_overrides_applied),
            excluded_rules_count=ruleset.excluded_rules_count,
            scheme=scheme,
        )
        try:
            det.gap_analysis = generate_gap_analysis(det, [])
        except Exception as e:
            logger.warning("Gap analysis failed for %s: %s", scheme_id, e)
        return det

    # -----------------------------------------------------------------------
    # Phase C — Eligibility rules (AND/OR group logic)
    # -----------------------------------------------------------------------
    group_evaluations: list[GroupEvaluation] = []
    # Seed c_evaluations with numeric-threshold disqualifying FAILs (Phase A½)
    c_evaluations: list[RuleEvaluation] = list(dis_fail_evals)

    for rule in elig_rules:
        try:
            ev = _evaluate_single_rule(profile, rule)
        except EvaluationError as e:
            logger.warning("EvaluationError in Phase C rule %s: %s", rule.rule_id, e.reason)
            ev = RuleEvaluation(
                rule_id=rule.rule_id,
                scheme_id=scheme_id,
                field=rule.field,
                operator=str(rule.operator),
                rule_value=rule.value,
                user_value=None,
                outcome="UNDETERMINED",
                outcome_score=None,
                display_text=rule.display_text or "",
                source_quote="",
                source_url="",
                audit_status=str(rule.audit_status),
                undetermined_reason=str(e.reason),
                ambiguity_notes=[],
            )
        except Exception as e:
            logger.warning("Unexpected error in Phase C rule %s: %s", rule.rule_id, e)
            ev = RuleEvaluation(
                rule_id=rule.rule_id,
                scheme_id=scheme_id,
                field=rule.field,
                operator=str(rule.operator),
                rule_value=rule.value,
                user_value=None,
                outcome="UNDETERMINED",
                outcome_score=None,
                display_text=rule.display_text or "",
                source_quote="",
                source_url="",
                audit_status=str(rule.audit_status),
                undetermined_reason="Evaluation error",
                ambiguity_notes=[],
            )

        all_evaluations.append(ev)
        c_evaluations.append(ev)
        if t := trace_by_id.get(rule.rule_id):
            t.outcome = ev.outcome

    # Build group evaluations by logic_group
    groups: dict[str, list[RuleEvaluation]] = {}
    group_logic: dict[str, str] = {}
    ungrouped: list[RuleEvaluation] = []

    for ev in c_evaluations:
        rule = rules_by_id.get(ev.rule_id)
        if rule and rule.logic_group:
            groups.setdefault(rule.logic_group, []).append(ev)
            group_logic[rule.logic_group] = rule.logic_operator or "AND"
        else:
            ungrouped.append(ev)

    for gid, gevs in groups.items():
        logic_op = group_logic.get(gid, "AND")
        g_outcome = _evaluate_group_outcome(logic_op, gevs)
        group_evaluations.append(
            GroupEvaluation(
                group_id=gid,
                logic_operator=logic_op,
                rule_ids=[e.rule_id for e in gevs],
                outcome=g_outcome,
            )
        )

    # Determine overall Phase C outcome:
    # Individual rule fails count for NEAR_MISS/INELIGIBLE thresholds
    fail_count = sum(1 for e in c_evaluations if e.outcome == "FAIL")
    pass_count = sum(1 for e in c_evaluations if e.outcome in ("PASS", "UNVERIFIED_PASS"))

    # -----------------------------------------------------------------------
    # Phase D — Administrative discretion rules (warnings only)
    # -----------------------------------------------------------------------
    discretion_warnings: list[str] = []

    for rule in disc_rules:
        try:
            ev = _evaluate_single_rule(profile, rule)
        except (EvaluationError, Exception) as e:
            logger.warning("EvaluationError in Phase D rule %s: %s", rule.rule_id, e)
            continue

        all_evaluations.append(ev)
        if t := trace_by_id.get(rule.rule_id):
            t.outcome = ev.outcome

        if ev.outcome == "FAIL":
            discretion_warnings.append(
                f"Administrative discretion: {rule.display_text or rule.rule_id} "
                f"— condition not met (field: {rule.field})"
            )

    # -----------------------------------------------------------------------
    # Status determination
    # -----------------------------------------------------------------------
    has_critical = _has_critical_ambiguity_on_passing_rules(c_evaluations, rules_by_id)

    if fail_count == 0 and pass_count == 0:
        # All Phase C evaluations are UNDETERMINED — check completeness threshold
        if all_fields:
            pc = len(all_fields & populated_fields) / len(all_fields)
        else:
            pc = 1.0
        if pc < PROFILE_COMPLETE_THRESHOLD:
            status = "INSUFFICIENT_DATA"
        else:
            # Completeness OK but all UNDETERMINED (e.g. ambiguity blocks)
            status = "PARTIAL"
    elif fail_count == 0:
        # All pass (possibly some UNDETERMINED too)
        if has_critical:
            status = "ELIGIBLE_WITH_CAVEATS"
        else:
            status = "ELIGIBLE"
    elif 0 < fail_count < NEAR_MISS_MAX_FAILED_RULES:
        status = "NEAR_MISS"
    else:
        status = "INELIGIBLE"

    # -----------------------------------------------------------------------
    # Confidence scoring
    # -----------------------------------------------------------------------
    confidence = compute_confidence_breakdown(
        all_evaluations, ambiguity_flags, all_fields, populated_fields
    )

    # -----------------------------------------------------------------------
    # Gap analysis (for non-ELIGIBLE statuses)
    # -----------------------------------------------------------------------
    determination = SchemeDetermination(
        scheme_id=scheme_id,
        scheme_name=scheme_name,
        status=status,
        rule_evaluations=all_evaluations,
        group_evaluations=group_evaluations,
        disqualification=disqualification,
        prerequisites=prerequisites,
        discretion_warnings=discretion_warnings,
        confidence=confidence,
        gap_analysis=None,
        rule_trace=rule_trace,
        state_overrides_applied=list(ruleset.state_overrides_applied),
        excluded_rules_count=ruleset.excluded_rules_count,
        scheme=scheme,
    )

    if status not in ("ELIGIBLE", "ELIGIBLE_WITH_CAVEATS"):
        try:
            determination.gap_analysis = generate_gap_analysis(determination, [])
        except Exception as e:
            logger.warning("Gap analysis failed for %s: %s", scheme_id, e)

    return determination


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


async def evaluate_profile(
    profile: Any,
    rule_base_path: Path,
    state: Optional[str] = None,
    _rule_base_cache: Optional[dict] = None,
) -> MatchingResult:
    """Evaluate a UserProfile against all schemes in rule_base_path.

    Args:
        profile: UserProfile. Must be fully constructed (already validated).
        rule_base_path: Directory containing scheme JSON files.
        state: Optional state code. If None, reads from profile.location_state.
        _rule_base_cache: Optional pre-loaded rule base dict (avoids re-reading files).

    Returns:
        MatchingResult with all scheme determinations bucketed by status.

    Raises:
        InvalidProfileError: If profile validation fails (age > 120, etc.).
        RuleBaseError: If rule_base_path is empty or no active schemes found.
    """
    from src.matching.profile import UserProfile  # local import for patching

    # Validate profile is internally consistent
    # (InvalidProfileError is raised during UserProfile construction if age > 120)
    # If profile is passed as already-valid, we can do an extra explicit check
    applicant_age = getattr(profile, "applicant_age", None)
    if applicant_age is not None and applicant_age > 120:
        raise InvalidProfileError(
            field="applicant.age",
            reason=f"Age {applicant_age} exceeds maximum allowed value of 120",
            suggestion="Verify the age field",
        )

    # Resolve state
    effective_state = state or getattr(profile, "location_state", None)

    # Load rule base (patchable at src.matching.engine.load_rule_base)
    if _rule_base_cache is not None:
        rule_base: dict[str, SchemeRuleSet] = _rule_base_cache
    else:
        rule_base: dict[str, SchemeRuleSet] = await load_rule_base(
            rule_base_path, user_state=effective_state
        )

    # Load ancillary data (errors are non-fatal; use empty lists as fallback)
    relationships = []
    amb_flags = []
    try:
        rel_path = rule_base_path / "relationships.json"
        if rel_path.exists():
            relationships = await load_relationship_matrix(rel_path)
    except Exception as e:
        logger.warning("Could not load relationship matrix: %s", e)

    try:
        amb_path = rule_base_path / "ambiguity_map.json"
        if amb_path.exists():
            amb_flags = await load_ambiguity_map(amb_path)
    except Exception as e:
        logger.warning("Could not load ambiguity map: %s", e)

    # Evaluate all schemes concurrently, bounded to 200 at a time (M5)
    _sem = asyncio.Semaphore(200)

    async def _bounded(ruleset: Any) -> Any:
        async with _sem:
            return await evaluate_scheme(profile, ruleset, amb_flags)

    determinations: list[SchemeDetermination] = []
    tasks = [_bounded(ruleset) for ruleset in rule_base.values()]
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                logger.error("Scheme evaluation failed: %s", res)
            else:
                determinations.append(res)
    except Exception as e:
        logger.exception("Fatal error during concurrent evaluation: %s", e)

    # Compute application sequence
    sequence = compute_application_sequence(determinations, relationships)

    # Collect profile warnings (from cross-field validation)
    profile_warnings: list[str] = list(getattr(profile, "_warnings", []) or [])

    # Assemble final result
    return assemble_matching_result(profile, determinations, sequence, profile_warnings)
