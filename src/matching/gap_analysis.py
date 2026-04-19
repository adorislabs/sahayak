"""Gap analysis and remediation generation for the CBC matching engine.

Explains WHY a scheme resulted in NEAR_MISS, INELIGIBLE, DISQUALIFIED, etc.,
and what the user could do to become eligible.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Gap type constants
_GAP_TYPE_BOOLEAN_MISMATCH = "BOOLEAN_MISMATCH"
_GAP_TYPE_NUMERIC_OVERSHOOT = "NUMERIC_OVERSHOOT"
_GAP_TYPE_NUMERIC_UNDERSHOOT = "NUMERIC_UNDERSHOOT"
_GAP_TYPE_CATEGORICAL_MISMATCH = "CATEGORICAL_MISMATCH"
_GAP_TYPE_MISSING_DATA = "MISSING_DATA"
_GAP_TYPE_MISSING_DOCUMENT = "MISSING_DOCUMENT"
_GAP_TYPE_ENROLLMENT_CONFLICT = "ENROLLMENT_CONFLICT"
_GAP_TYPE_PREREQUISITE_UNMET = "PREREQUISITE_UNMET"
_GAP_TYPE_DISCRETIONARY_BLOCK = "DISCRETIONARY_BLOCK"
_GAP_TYPE_AMBIGUITY_BLOCK = "AMBIGUITY_BLOCK"


@dataclass
class FailedRuleDetail:
    """Details about a single failed or undetermined rule."""

    rule_id: str
    field: str
    operator: str
    required_value: Any
    user_value: Any
    gap_type: str
    gap_magnitude: Optional[float]
    display_text: str


@dataclass
class RemediationAction:
    """A specific action the user could take to close a gap."""

    action_id: str
    description: str
    urgency: str        # IMMEDIATE / SHORT_TERM / LONG_TERM
    document_needed: Optional[str]
    estimated_effort: Optional[str]


@dataclass
class PrerequisiteGap:
    """A prerequisite scheme that is required but not enrolled."""

    scheme_id: str
    scheme_name: str
    is_enrolled: bool
    enrollment_url: Optional[str]


@dataclass
class AmbiguityNote:
    """An ambiguity flag affecting the determination."""

    ambiguity_id: str
    severity: str
    description: str
    affects_rule: str


@dataclass
class DocumentGap:
    """A document required for the scheme that is missing or unverified."""

    document_field: str
    document_name: str
    is_obtainable: bool


@dataclass
class GapAnalysis:
    """Complete gap analysis for a non-ELIGIBLE scheme determination."""

    scheme_id: str
    scheme_name: str
    status: str
    rules_passed: int
    rules_failed: int
    rules_undetermined: int
    failed_rules: list[FailedRuleDetail]
    prerequisite_gaps: list[PrerequisiteGap]
    remediation_actions: list[RemediationAction]
    ambiguity_notes: list[AmbiguityNote]
    missing_documents: list[DocumentGap]
    near_miss_score: Optional[float]


def _classify_gap_type(
    field_name: str,
    operator: str,
    rule_value: Any,
    user_value: Any,
    outcome: str,
) -> tuple[str, Optional[float]]:
    """Classify the type of gap and compute magnitude if applicable.

    Returns:
        (gap_type_string, magnitude_or_none)
    """
    # Missing data case
    if user_value is None or outcome == "UNDETERMINED":
        return _GAP_TYPE_MISSING_DATA, None

    # Document fields
    doc_fields = {
        "documents.bank_account",
        "documents.aadhaar",
        "documents.mgnrega_job_card",
        "documents.caste_certificate",
        "documents.income_certificate",
    }
    if field_name in doc_fields:
        if isinstance(user_value, bool) and isinstance(rule_value, bool):
            return _GAP_TYPE_MISSING_DOCUMENT, None
        return _GAP_TYPE_BOOLEAN_MISMATCH, None

    # Boolean fields
    if isinstance(user_value, bool) or isinstance(rule_value, bool):
        return _GAP_TYPE_BOOLEAN_MISMATCH, None

    # Numeric fields
    numeric_operators = {"GTE", "GT", "LTE", "LT", "BETWEEN"}
    if operator in numeric_operators:
        try:
            uv = float(user_value)
            # Determine direction
            if operator in {"GTE", "GT"}:
                # Rule requires value >= threshold; user is below
                threshold = float(rule_value) if not isinstance(rule_value, list) else float(rule_value[0])
                magnitude = threshold - uv
                if magnitude > 0:
                    return _GAP_TYPE_NUMERIC_UNDERSHOOT, magnitude
                else:
                    return _GAP_TYPE_NUMERIC_OVERSHOOT, abs(magnitude)
            elif operator in {"LTE", "LT"}:
                # Rule requires value <= threshold; user is above
                threshold = float(rule_value) if not isinstance(rule_value, list) else float(rule_value[0])
                magnitude = uv - threshold
                if magnitude > 0:
                    return _GAP_TYPE_NUMERIC_OVERSHOOT, magnitude
                else:
                    return _GAP_TYPE_NUMERIC_UNDERSHOOT, abs(magnitude)
            elif operator == "BETWEEN":
                # rule_value is [min, max]
                if isinstance(rule_value, list) and len(rule_value) >= 2:
                    lo, hi = float(rule_value[0]), float(rule_value[1])
                    if uv < lo:
                        return _GAP_TYPE_NUMERIC_UNDERSHOOT, lo - uv
                    elif uv > hi:
                        return _GAP_TYPE_NUMERIC_OVERSHOOT, uv - hi
        except (TypeError, ValueError, IndexError):
            pass
        return _GAP_TYPE_NUMERIC_UNDERSHOOT, None

    # Categorical / string fields
    return _GAP_TYPE_CATEGORICAL_MISMATCH, None


def _extract_failed_rules(determination: Any) -> list[FailedRuleDetail]:
    """Extract FailedRuleDetail objects from failed and undetermined evaluations."""
    details: list[FailedRuleDetail] = []
    rule_evals = getattr(determination, "rule_evaluations", [])

    for ev in rule_evals:
        outcome = getattr(ev, "outcome", "")
        if outcome not in ("FAIL", "UNDETERMINED"):
            continue

        field_name = getattr(ev, "field", "")
        operator = getattr(ev, "operator", "EQ")
        rule_value = getattr(ev, "rule_value", None)
        user_value = getattr(ev, "user_value", None)
        ambiguity_notes = getattr(ev, "ambiguity_notes", [])

        # Ambiguity-blocked rules
        if ambiguity_notes and outcome == "UNDETERMINED":
            gap_type = _GAP_TYPE_AMBIGUITY_BLOCK
            magnitude = None
        else:
            gap_type, magnitude = _classify_gap_type(
                field_name, str(operator), rule_value, user_value, outcome
            )

        details.append(
            FailedRuleDetail(
                rule_id=getattr(ev, "rule_id", ""),
                field=field_name,
                operator=str(operator),
                required_value=rule_value,
                user_value=user_value,
                gap_type=gap_type,
                gap_magnitude=magnitude,
                display_text=getattr(ev, "display_text", ""),
            )
        )

    return details


def _extract_prerequisite_gaps(determination: Any) -> list[PrerequisiteGap]:
    """Extract prerequisite gaps from a determination."""
    gaps: list[PrerequisiteGap] = []
    prerequisites = getattr(determination, "prerequisites", None)
    if prerequisites is None:
        return gaps

    unmet = getattr(prerequisites, "unmet_prerequisites", [])
    for prereq in unmet:
        if isinstance(prereq, str):
            gaps.append(
                PrerequisiteGap(
                    scheme_id=prereq,
                    scheme_name=prereq,
                    is_enrolled=False,
                    enrollment_url=None,
                )
            )
        else:
            gaps.append(
                PrerequisiteGap(
                    scheme_id=getattr(prereq, "scheme_id", str(prereq)),
                    scheme_name=getattr(prereq, "scheme_name", str(prereq)),
                    is_enrolled=False,
                    enrollment_url=getattr(prereq, "enrollment_url", None),
                )
            )

    return gaps


def _extract_ambiguity_notes(determination: Any) -> list[AmbiguityNote]:
    """Extract AmbiguityNote objects from rule evaluations that have ambiguity flags."""
    notes: list[AmbiguityNote] = []
    seen_ids: set[str] = set()

    rule_evals = getattr(determination, "rule_evaluations", [])
    for ev in rule_evals:
        rule_id = getattr(ev, "rule_id", "")
        amb_flags = getattr(ev, "ambiguity_notes", [])
        for note in amb_flags:
            if isinstance(note, str):
                note_id = note.split(":")[0].strip()
                if note_id not in seen_ids:
                    seen_ids.add(note_id)
                    notes.append(
                        AmbiguityNote(
                            ambiguity_id=note_id,
                            severity="UNKNOWN",
                            description=note,
                            affects_rule=rule_id,
                        )
                    )
            else:
                amb_id = getattr(note, "ambiguity_id", str(note))
                if amb_id not in seen_ids:
                    seen_ids.add(amb_id)
                    sev = getattr(note, "severity", "UNKNOWN")
                    if hasattr(sev, "value"):
                        sev = sev.value
                    notes.append(
                        AmbiguityNote(
                            ambiguity_id=amb_id,
                            severity=str(sev),
                            description=getattr(note, "description", ""),
                            affects_rule=rule_id,
                        )
                    )

    return notes


def _generate_remediation_actions(
    failed_rules: list[FailedRuleDetail],
    prerequisite_gaps: list[PrerequisiteGap],
    status: str,
) -> list[RemediationAction]:
    """Generate actionable remediation steps for the user."""
    actions: list[RemediationAction] = []
    action_counter = [1]

    def _next_id(scheme_id: str = "ACT") -> str:
        aid = f"{scheme_id}-{action_counter[0]:03d}"
        action_counter[0] += 1
        return aid

    # Prerequisite gaps → enroll in prerequisite schemes
    for pg in prerequisite_gaps:
        actions.append(
            RemediationAction(
                action_id=_next_id("PREREQ"),
                description=(
                    f"Enroll in {pg.scheme_name} ({pg.scheme_id}) as a prerequisite. "
                    "This scheme is required before you can apply."
                ),
                urgency="IMMEDIATE",
                document_needed=None,
                estimated_effort="1-2 weeks",
            )
        )

    # Document gaps → obtain documents
    doc_field_map: dict[str, str] = {
        "documents.bank_account": "bank account (Jan Dhan Yojana or any nationalised bank)",
        "documents.aadhaar": "Aadhaar card",
        "documents.mgnrega_job_card": "MGNREGA job card",
        "documents.caste_certificate": "caste certificate from competent authority",
        "documents.income_certificate": "income certificate from tehsildar/SDM",
    }

    for fr in failed_rules:
        if fr.gap_type == _GAP_TYPE_MISSING_DOCUMENT and fr.field in doc_field_map:
            doc_name = doc_field_map[fr.field]
            actions.append(
                RemediationAction(
                    action_id=_next_id("DOC"),
                    description=f"Obtain a {doc_name} to meet document requirement.",
                    urgency="IMMEDIATE",
                    document_needed=doc_name,
                    estimated_effort="1-4 weeks",
                )
            )
        elif fr.gap_type == _GAP_TYPE_BOOLEAN_MISMATCH and fr.field == "documents.bank_account":
            actions.append(
                RemediationAction(
                    action_id=_next_id("DOC"),
                    description=(
                        "Open a bank account (Jan Dhan Yojana is free and available at all "
                        "nationalised banks) to receive Direct Benefit Transfer payments."
                    ),
                    urgency="IMMEDIATE",
                    document_needed="Bank account",
                    estimated_effort="1-2 weeks",
                )
            )
        elif fr.gap_type == _GAP_TYPE_MISSING_DATA:
            actions.append(
                RemediationAction(
                    action_id=_next_id("DATA"),
                    description=f"Provide information for field '{fr.field}' to enable evaluation.",
                    urgency="SHORT_TERM",
                    document_needed=None,
                    estimated_effort="Immediate",
                )
            )
        elif fr.gap_type in (_GAP_TYPE_NUMERIC_UNDERSHOOT, _GAP_TYPE_NUMERIC_OVERSHOOT):
            actions.append(
                RemediationAction(
                    action_id=_next_id("CONDITION"),
                    description=(
                        f"Condition not met for '{fr.display_text}'. "
                        f"Current value: {fr.user_value}, required: {fr.required_value}."
                    ),
                    urgency="LONG_TERM",
                    document_needed=None,
                    estimated_effort=None,
                )
            )

    return actions


def compute_near_miss_score(determination: Any) -> float:
    """Compute how close a scheme determination is to eligibility.

    Score 0.0-1.0: 1.0 = all rules passed, 0.0 = no rules passed.

    Args:
        determination: SchemeDetermination object with rule_evaluations.

    Returns:
        Float in [0.0, 1.0].
    """
    rule_evals = getattr(determination, "rule_evaluations", [])
    if not rule_evals:
        return 0.0

    total = len(rule_evals)
    passed = sum(1 for e in rule_evals if getattr(e, "outcome", "") in ("PASS", "UNVERIFIED_PASS"))

    return float(passed / total)


def generate_gap_analysis(
    determination: Any,
    all_scheme_determinations: list[Any],
) -> GapAnalysis:
    """Generate a complete gap analysis for a non-ELIGIBLE scheme determination.

    Args:
        determination: SchemeDetermination object.
        all_scheme_determinations: All determinations (for cross-scheme context).

    Returns:
        GapAnalysis dataclass with failed rules, gaps, and remediation actions.
    """
    try:
        scheme_id = getattr(determination, "scheme_id", "UNKNOWN")
        scheme_name = getattr(determination, "scheme_name", scheme_id)
        status = getattr(determination, "status", "UNKNOWN")

        rule_evals = getattr(determination, "rule_evaluations", [])
        rules_passed = sum(
            1 for e in rule_evals if getattr(e, "outcome", "") in ("PASS", "UNVERIFIED_PASS")
        )
        rules_failed = sum(1 for e in rule_evals if getattr(e, "outcome", "") == "FAIL")
        rules_undetermined = sum(
            1 for e in rule_evals if getattr(e, "outcome", "") == "UNDETERMINED"
        )

        failed_rules = _extract_failed_rules(determination)
        prerequisite_gaps = _extract_prerequisite_gaps(determination)
        ambiguity_notes = _extract_ambiguity_notes(determination)
        remediation_actions = _generate_remediation_actions(
            failed_rules, prerequisite_gaps, status
        )

        # Near-miss score (only meaningful for NEAR_MISS status)
        near_miss_score: Optional[float] = None
        if status in ("NEAR_MISS", "INELIGIBLE"):
            near_miss_score = compute_near_miss_score(determination)

        return GapAnalysis(
            scheme_id=scheme_id,
            scheme_name=scheme_name,
            status=status,
            rules_passed=rules_passed,
            rules_failed=rules_failed,
            rules_undetermined=rules_undetermined,
            failed_rules=failed_rules,
            prerequisite_gaps=prerequisite_gaps,
            remediation_actions=remediation_actions,
            ambiguity_notes=ambiguity_notes,
            missing_documents=[],  # Derived from failed_rules by caller if needed
            near_miss_score=near_miss_score,
        )

    except Exception as e:
        logger.exception("Error generating gap analysis for %s: %s", determination, e)
        return GapAnalysis(
            scheme_id=getattr(determination, "scheme_id", "UNKNOWN"),
            scheme_name=getattr(determination, "scheme_name", "Unknown"),
            status=getattr(determination, "status", "UNKNOWN"),
            rules_passed=0,
            rules_failed=0,
            rules_undetermined=0,
            failed_rules=[],
            prerequisite_gaps=[],
            remediation_actions=[],
            ambiguity_notes=[],
            missing_documents=[],
            near_miss_score=None,
        )
