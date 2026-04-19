"""Three-tier confidence scoring for the CBC matching engine.

Three dimensions:
  Tier 1 - Rule Match Score (RMS): weighted fraction of evaluable rules that PASS
  Tier 2 - Data Confidence (DC):   audit quality × ambiguity penalties
  Tier 3 - Profile Completeness (PC): populated fields / required fields

Composite = min(RMS, DC, PC). Bottleneck = dimension with lowest value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.config import (
    CRITICAL_AMB_DATA_CAP,
    HIGH_AMB_PENALTY,
    MEDIUM_AMB_PENALTY,
    UNVERIFIED_PASS_SCORE,
)

# Audit status base scores for data confidence
_AUDIT_BASE_SCORES: dict[str, float] = {
    "VERIFIED": 1.0,
    "NEEDS_REVIEW": 0.7,
    "PENDING": 0.5,
    "OVERRIDDEN": 0.8,
    "DISPUTED": 0.0,
}

# Composite label thresholds
_LABEL_THRESHOLDS: list[tuple[float, str]] = [
    (0.80, "HIGH"),
    (0.60, "MEDIUM"),
    (0.40, "LOW"),
    (0.20, "VERY_LOW"),
    (0.0, "UNLIKELY"),
]


@dataclass
class ConfidenceBreakdown:
    """Three-tier confidence breakdown for a scheme determination.

    composite = min(rule_match_score, data_confidence, profile_completeness)
    bottleneck = the dimension that caps the composite.
    """

    rule_match_score: float
    data_confidence: float
    profile_completeness: float
    composite: float
    composite_label: str
    bottleneck: str
    bottleneck_explanation: str
    improvement_actions: list[str]


def _get_composite_label(composite: float) -> str:
    """Return a human-readable label for a composite confidence score."""
    for threshold, label in _LABEL_THRESHOLDS:
        if composite >= threshold:
            return label
    return "UNLIKELY"


def compute_rule_match_score(evaluations: list[Any]) -> float:
    """Compute the Rule Match Score (RMS) from a list of rule evaluations.

    PASS = 1.0, UNVERIFIED_PASS = 0.70 (UNVERIFIED_PASS_SCORE), FAIL = 0.0.
    UNDETERMINED evaluations are excluded from the average.
    All UNDETERMINED (or empty list) → returns 0.0.

    Args:
        evaluations: List of objects with .outcome attribute.

    Returns:
        Float in [0.0, 1.0].
    """
    _OUTCOME_SCORES: dict[str, float] = {
        "PASS": 1.0,
        "UNVERIFIED_PASS": UNVERIFIED_PASS_SCORE,
        "FAIL": 0.0,
    }

    evaluable = [e for e in evaluations if getattr(e, "outcome", None) in _OUTCOME_SCORES]

    if not evaluable:
        return 0.0

    total = sum(_OUTCOME_SCORES[e.outcome] for e in evaluable)
    return total / len(evaluable)


def compute_data_confidence(
    evaluations: list[Any],
    ambiguity_flags: list[Any],
) -> float:
    """Compute the Data Confidence (DC) score.

    Base score = average of per-rule audit status scores.
    Penalties applied for ambiguity flags linked to evaluated rules:
      CRITICAL → cap the entire score at CRITICAL_AMB_DATA_CAP (0.30)
      HIGH     → subtract HIGH_AMB_PENALTY (0.15)
      MEDIUM   → subtract MEDIUM_AMB_PENALTY (0.05)
    Score is always in [0.0, 1.0].

    Args:
        evaluations: List of objects with .audit_status and .ambiguity_notes attributes.
        ambiguity_flags: List of objects with .flag_id (or .ambiguity_id) and .severity attributes.

    Returns:
        Float in [0.0, 1.0].
    """
    if not evaluations:
        return 0.0

    # Compute average audit status base score
    scores = []
    for ev in evaluations:
        audit_status = getattr(ev, "audit_status", "PENDING")
        if hasattr(audit_status, "value"):
            audit_status = audit_status.value
        base = _AUDIT_BASE_SCORES.get(str(audit_status), 0.5)
        scores.append(base)

    avg_score = sum(scores) / len(scores)

    # Build ambiguity flag lookup by ID
    flag_lookup: dict[str, str] = {}  # flag_id → severity string
    for flag in ambiguity_flags:
        flag_id = (
            getattr(flag, "flag_id", None)
            or getattr(flag, "ambiguity_id", None)
        )
        severity = getattr(flag, "severity", None)
        if severity is not None:
            sev_str = severity.value if hasattr(severity, "value") else str(severity)
            if flag_id:
                flag_lookup[flag_id] = sev_str

    # Collect all ambiguity note IDs from evaluations
    linked_severities: list[str] = []
    for ev in evaluations:
        notes = getattr(ev, "ambiguity_notes", []) or []
        for note in notes:
            # Notes can be plain IDs like "AMB-007" or strings like "AMB-007: description"
            note_id = note.split(":")[0].strip() if isinstance(note, str) else str(note)
            if note_id in flag_lookup:
                linked_severities.append(flag_lookup[note_id])

    # Apply penalties
    has_critical = any(s == "CRITICAL" for s in linked_severities)
    high_count = sum(1 for s in linked_severities if s == "HIGH")
    medium_count = sum(1 for s in linked_severities if s == "MEDIUM")

    penalty = high_count * HIGH_AMB_PENALTY + medium_count * MEDIUM_AMB_PENALTY
    result = max(0.0, avg_score - penalty)

    if has_critical:
        result = min(result, CRITICAL_AMB_DATA_CAP)

    return max(0.0, min(1.0, result))


def compute_profile_completeness_score(
    required_fields: set[str],
    populated_fields: set[str],
) -> float:
    """Compute Profile Completeness Score (PC).

    PC = |populated ∩ required| / |required|
    Returns 0.0 when required is empty (no ZeroDivisionError).

    Args:
        required_fields: Fields a scheme needs for evaluation.
        populated_fields: Fields present in the user profile.

    Returns:
        Float in [0.0, 1.0].
    """
    if not required_fields:
        return 0.0

    present = required_fields & populated_fields
    return len(present) / len(required_fields)


def compute_confidence_breakdown(
    evaluations: list[Any],
    ambiguity_flags: list[Any],
    required_fields: set[str],
    populated_fields: set[str],
) -> ConfidenceBreakdown:
    """Compute the full three-tier confidence breakdown.

    composite = min(rule_match, data_confidence, profile_completeness)
    bottleneck = the lowest scoring dimension.

    Args:
        evaluations: List of rule evaluation result objects.
        ambiguity_flags: Known ambiguity flags for the scheme.
        required_fields: Fields the scheme requires.
        populated_fields: Fields present in the profile.

    Returns:
        ConfidenceBreakdown dataclass with all three dimensions and composite.
    """
    rms = compute_rule_match_score(evaluations)
    dc = compute_data_confidence(evaluations, ambiguity_flags)
    pc = compute_profile_completeness_score(required_fields, populated_fields)

    composite = min(rms, dc, pc)
    label = _get_composite_label(composite)

    # Identify bottleneck
    dims = {"rule_match": rms, "data_confidence": dc, "profile_completeness": pc}
    bottleneck = min(dims, key=lambda k: dims[k])

    # Generate improvement actions
    actions: list[str] = []
    if rms < 0.80:
        actions.append(
            "Check eligibility rules — some rules failed or were undetermined"
        )
    if dc < 0.80:
        actions.append(
            "Data quality is limited — some rules have PENDING or NEEDS_REVIEW audit status. "
            "Verify source documents to improve confidence."
        )
    if pc < 0.80:
        missing_count = len(required_fields - populated_fields)
        actions.append(
            f"Profile is incomplete — {missing_count} required field(s) are missing. "
            "Provide more details to improve accuracy."
        )

    bottleneck_explanations: dict[str, str] = {
        "rule_match": (
            f"Rule match score ({rms:.2f}) is the lowest dimension. "
            "One or more eligibility rules failed."
        ),
        "data_confidence": (
            f"Data confidence ({dc:.2f}) is the lowest dimension. "
            "Source data quality or ambiguity flags limit confidence."
        ),
        "profile_completeness": (
            f"Profile completeness ({pc:.2f}) is the lowest dimension. "
            "Provide more profile fields to improve the evaluation."
        ),
    }

    return ConfidenceBreakdown(
        rule_match_score=rms,
        data_confidence=dc,
        profile_completeness=pc,
        composite=composite,
        composite_label=label,
        bottleneck=bottleneck,
        bottleneck_explanation=bottleneck_explanations.get(bottleneck, ""),
        improvement_actions=actions,
    )
