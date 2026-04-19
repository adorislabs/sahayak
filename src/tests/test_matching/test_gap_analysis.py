"""Tests for Feature 4: Gap analysis and remediation generation.

Spec reference: docs/part2-planning/specs/04-gap-analysis.md
Architecture:   docs/part2-planning/ARCHITECTURE-CONTRACT.md § src/matching/gap_analysis.py

Gap type taxonomy:
  NUMERIC_OVERSHOOT | NUMERIC_UNDERSHOOT | CATEGORICAL_MISMATCH | BOOLEAN_MISMATCH
  MISSING_DATA | MISSING_DOCUMENT | ENROLLMENT_CONFLICT | PREREQUISITE_UNMET
  DISCRETIONARY_BLOCK | AMBIGUITY_BLOCK

near_miss_score: 1.0 = single small waivable gap; 0.0 = many large unwaivable gaps.

Tests will fail (ImportError) until Agent B implements src/matching/gap_analysis.py.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.matching.gap_analysis import (  # type: ignore[import]
    AmbiguityNote,
    DocumentGap,
    FailedRuleDetail,
    GapAnalysis,
    PrerequisiteGap,
    RemediationAction,
    compute_near_miss_score,
    generate_gap_analysis,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_determination(
    scheme_id: str = "PMKISAN",
    scheme_name: str = "PM-KISAN",
    status: str = "NEAR_MISS",
    rule_evals: list[MagicMock] | None = None,
    group_evals: list[MagicMock] | None = None,
    prerequisites: MagicMock | None = None,
    discretion_warnings: list[MagicMock] | None = None,
    state_overrides_applied: list[str] | None = None,
    excluded_rules_count: int = 0,
) -> MagicMock:
    """Build a minimal SchemeDetermination mock."""
    det = MagicMock()
    det.scheme_id = scheme_id
    det.scheme_name = scheme_name
    det.status = status
    det.rule_evaluations = rule_evals or []
    det.group_evaluations = group_evals or []
    det.discretion_warnings = discretion_warnings or []
    det.state_overrides_applied = state_overrides_applied or []
    det.excluded_rules_count = excluded_rules_count

    if prerequisites is None:
        prerequisites = MagicMock()
        prerequisites.all_met = True
        prerequisites.unmet_prerequisites = []
        prerequisites.met_prerequisites = []
    det.prerequisites = prerequisites

    return det


def _make_rule_eval(
    rule_id: str,
    outcome: str,
    field: str = "applicant.age",
    operator: str = "GTE",
    rule_value: Any = 18,
    user_value: Any = 16,
    audit_status: str = "VERIFIED",
    ambiguity_notes: list[str] | None = None,
    display_text: str = "Applicant must be at least 18",
    source_quote: str = "Must be at least 18",
    source_url: str = "https://example.gov.in",
) -> MagicMock:
    ev = MagicMock()
    ev.rule_id = rule_id
    ev.outcome = outcome
    ev.field = field
    ev.operator = operator
    ev.rule_value = rule_value
    ev.user_value = user_value
    ev.audit_status = audit_status
    ev.ambiguity_notes = ambiguity_notes or []
    ev.display_text = display_text
    ev.source_quote = source_quote
    ev.source_url = source_url
    return ev


# ===========================================================================
# Group 1: generate_gap_analysis — eligibility
# ===========================================================================

class TestGapAnalysisEligibility:
    """generate_gap_analysis only called for non-ELIGIBLE schemes."""

    def test_generate_gap_analysis_returns_gap_analysis_for_near_miss(self) -> None:
        """NEAR_MISS determination must return a GapAnalysis object."""
        det = _make_determination(
            status="NEAR_MISS",
            rule_evals=[_make_rule_eval("PMKISAN-R001", "FAIL", field="applicant.land_ownership_status",
                                        operator="EQ", rule_value=True, user_value=False)],
        )
        result = generate_gap_analysis(det, [det])

        assert isinstance(result, GapAnalysis)

    def test_generate_gap_analysis_for_ineligible(self) -> None:
        """INELIGIBLE determination must also return a GapAnalysis."""
        det = _make_determination(status="INELIGIBLE")
        result = generate_gap_analysis(det, [det])

        assert isinstance(result, GapAnalysis)

    def test_generate_gap_analysis_for_disqualified(self) -> None:
        """DISQUALIFIED determination must return a GapAnalysis (explaining why)."""
        det = _make_determination(status="DISQUALIFIED")
        result = generate_gap_analysis(det, [det])

        assert isinstance(result, GapAnalysis)

    def test_generate_gap_analysis_for_requires_prerequisite(self) -> None:
        """REQUIRES_PREREQUISITE determination must return a GapAnalysis with prerequisite_gaps."""
        prereqs = MagicMock()
        prereqs.all_met = False
        prereqs.unmet_prerequisites = ["NSAP-BANK-PREREQ"]
        prereqs.met_prerequisites = []

        det = _make_determination(status="REQUIRES_PREREQUISITE", prerequisites=prereqs)
        result = generate_gap_analysis(det, [det])

        assert isinstance(result, GapAnalysis)
        assert len(result.prerequisite_gaps) > 0

    def test_generate_gap_analysis_for_partial(self) -> None:
        """PARTIAL determination must return a GapAnalysis with ambiguity_notes."""
        det = _make_determination(
            status="PARTIAL",
            rule_evals=[_make_rule_eval("MGNREGA-R002", "UNDETERMINED",
                                        ambiguity_notes=["AMB-007"])],
        )
        result = generate_gap_analysis(det, [det])

        assert isinstance(result, GapAnalysis)

    def test_generate_gap_analysis_for_insufficient_data(self) -> None:
        """INSUFFICIENT_DATA determination must return a GapAnalysis."""
        det = _make_determination(status="INSUFFICIENT_DATA")
        result = generate_gap_analysis(det, [det])

        assert isinstance(result, GapAnalysis)


# ===========================================================================
# Group 2: GapAnalysis field accuracy
# ===========================================================================

class TestGapAnalysisFields:
    """GapAnalysis fields accurately reflect the determination's rules."""

    def test_rules_passed_count_accurate(self) -> None:
        """GapAnalysis.rules_passed must match count of PASS evaluations."""
        det = _make_determination(
            status="NEAR_MISS",
            rule_evals=[
                _make_rule_eval("PMKISAN-R001", "PASS"),
                _make_rule_eval("PMKISAN-R002", "FAIL"),
            ],
        )
        result = generate_gap_analysis(det, [det])

        assert result.rules_passed == 1
        assert result.rules_failed == 1

    def test_rules_undetermined_count_accurate(self) -> None:
        """GapAnalysis.rules_undetermined must count UNDETERMINED evaluations."""
        det = _make_determination(
            status="PARTIAL",
            rule_evals=[
                _make_rule_eval("PMKISAN-R001", "PASS"),
                _make_rule_eval("PMKISAN-R003", "UNDETERMINED"),
            ],
        )
        result = generate_gap_analysis(det, [det])

        assert result.rules_undetermined == 1

    def test_failed_rules_list_populated_with_fail_details(self) -> None:
        """failed_rules list must contain FailedRuleDetail for each FAIL evaluation."""
        det = _make_determination(
            status="NEAR_MISS",
            rule_evals=[
                _make_rule_eval(
                    "PMKISAN-R001",
                    "FAIL",
                    field="applicant.land_ownership_status",
                    operator="EQ",
                    rule_value=True,
                    user_value=False,
                ),
            ],
        )
        result = generate_gap_analysis(det, [det])

        assert len(result.failed_rules) == 1
        fd = result.failed_rules[0]
        assert isinstance(fd, FailedRuleDetail)
        assert fd.rule_id == "PMKISAN-R001"
        assert fd.field == "applicant.land_ownership_status"

    def test_failed_rule_gap_type_boolean_mismatch(self) -> None:
        """Boolean field fail → gap_type = BOOLEAN_MISMATCH."""
        det = _make_determination(
            status="NEAR_MISS",
            rule_evals=[
                _make_rule_eval(
                    "PMKISAN-R001",
                    "FAIL",
                    field="applicant.land_ownership_status",
                    operator="EQ",
                    rule_value=True,
                    user_value=False,
                ),
            ],
        )
        result = generate_gap_analysis(det, [det])

        assert result.failed_rules[0].gap_type == "BOOLEAN_MISMATCH"

    def test_failed_rule_gap_type_numeric_undershoot(self) -> None:
        """Age less than required → gap_type = NUMERIC_UNDERSHOOT."""
        det = _make_determination(
            status="NEAR_MISS",
            rule_evals=[
                _make_rule_eval(
                    "PMSYM-R001",
                    "FAIL",
                    field="applicant.age",
                    operator="BETWEEN",
                    rule_value=[18.0, 40.0],
                    user_value=45,  # over 40 → NUMERIC_OVERSHOOT
                ),
            ],
        )
        result = generate_gap_analysis(det, [det])

        assert result.failed_rules[0].gap_type in ("NUMERIC_OVERSHOOT", "NUMERIC_UNDERSHOOT")

    def test_failed_rule_gap_type_missing_data_for_none_user_value(self) -> None:
        """user_value=None → gap_type = MISSING_DATA."""
        det = _make_determination(
            status="NEAR_MISS",
            rule_evals=[
                _make_rule_eval(
                    "PMKISAN-R002",
                    "UNDETERMINED",
                    field="applicant.land_ownership_status",
                    operator="EQ",
                    rule_value=True,
                    user_value=None,  # data not provided
                ),
            ],
        )
        result = generate_gap_analysis(det, [det])

        # UNDETERMINED rules from missing data → MISSING_DATA gap
        if result.failed_rules:
            assert result.failed_rules[0].gap_type in ("MISSING_DATA", "AMBIGUITY_BLOCK")

    def test_scheme_id_and_name_match_determination(self) -> None:
        """GapAnalysis.scheme_id and .scheme_name must match the input determination."""
        det = _make_determination(
            scheme_id="PMSYM",
            scheme_name="PM Shram Yogi Maandhan",
            status="INELIGIBLE",
        )
        result = generate_gap_analysis(det, [det])

        assert result.scheme_id == "PMSYM"
        assert result.scheme_name == "PM Shram Yogi Maandhan"


# ===========================================================================
# Group 3: Remediation actions
# ===========================================================================

class TestRemediationActions:
    """Remediation actions are generated for actionable gaps."""

    def test_missing_bank_account_generates_open_account_action(self) -> None:
        """documents.bank_account = False → remediation action for bank account enrollment."""
        det = _make_determination(
            status="REQUIRES_PREREQUISITE",
            rule_evals=[
                _make_rule_eval(
                    "NSAP-PRE-001",
                    "FAIL",
                    field="documents.bank_account",
                    operator="EQ",
                    rule_value=True,
                    user_value=False,
                    display_text="Applicant must have a bank account",
                ),
            ],
        )
        result = generate_gap_analysis(det, [det])

        action_descriptions = [a.description.lower() for a in result.remediation_actions]
        bank_action = any("bank" in desc or "jan dhan" in desc for desc in action_descriptions)
        assert bank_action, f"Expected bank account action, got: {action_descriptions}"

    def test_remediation_actions_have_urgency_levels(self) -> None:
        """All remediation actions must have urgency in {high, medium, low}."""
        det = _make_determination(
            status="NEAR_MISS",
            rule_evals=[
                _make_rule_eval("PMKISAN-R001", "FAIL",
                                field="applicant.land_ownership_status",
                                operator="EQ", rule_value=True, user_value=False),
            ],
        )
        result = generate_gap_analysis(det, [det])

        valid_urgency = {"high", "medium", "low"}
        for action in result.remediation_actions:
            assert action.urgency in valid_urgency

    def test_remediation_actions_are_remediation_action_instances(self) -> None:
        """Items in remediation_actions must be RemediationAction dataclass instances."""
        det = _make_determination(
            status="NEAR_MISS",
            rule_evals=[
                _make_rule_eval("PMKISAN-R001", "FAIL"),
            ],
        )
        result = generate_gap_analysis(det, [det])

        for action in result.remediation_actions:
            assert isinstance(action, RemediationAction)


# ===========================================================================
# Group 4: Near-miss score
# ===========================================================================

class TestComputeNearMissScore:
    """near_miss_score reflects closeness to eligibility."""

    def test_single_small_waivable_gap_returns_high_score(self) -> None:
        """1 waivable gap → near_miss_score close to 1.0."""
        det = _make_determination(
            status="NEAR_MISS",
            rule_evals=[
                _make_rule_eval("PMKISAN-R001", "FAIL"),
                _make_rule_eval("PMKISAN-R002", "PASS"),
                _make_rule_eval("PMKISAN-R003", "PASS"),
            ],
        )
        score = compute_near_miss_score(det)

        assert score >= 0.6  # one fail among many passes → high near_miss score

    def test_many_failures_returns_low_score(self) -> None:
        """Many failing rules → near_miss_score close to 0.0."""
        det = _make_determination(
            status="INELIGIBLE",
            rule_evals=[
                _make_rule_eval("PMKISAN-R001", "FAIL"),
                _make_rule_eval("PMKISAN-R002", "FAIL"),
                _make_rule_eval("PMKISAN-R003", "FAIL"),
                _make_rule_eval("PMSYM-R001", "FAIL"),
                _make_rule_eval("PMSYM-R002", "FAIL"),
            ],
        )
        score = compute_near_miss_score(det)

        assert score <= 0.3

    def test_near_miss_score_bounded_0_to_1(self) -> None:
        """near_miss_score must always be in [0.0, 1.0]."""
        det = _make_determination(status="NEAR_MISS")
        score = compute_near_miss_score(det)

        assert 0.0 <= score <= 1.0

    def test_near_miss_score_is_float(self) -> None:
        """Return type must be float."""
        det = _make_determination(status="NEAR_MISS")
        score = compute_near_miss_score(det)

        assert isinstance(score, float)

    def test_never_raises_on_empty_rule_list(self) -> None:
        """Empty rule evaluations must not raise."""
        det = _make_determination(status="NEAR_MISS", rule_evals=[])
        score = compute_near_miss_score(det)

        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0


# ===========================================================================
# Group 5: Ambiguity notes in gap analysis
# ===========================================================================

class TestAmbiguityNotes:
    """Ambiguity flags referenced in rule evaluations appear in GapAnalysis.ambiguity_notes."""

    def test_critical_ambiguity_rule_generates_ambiguity_note(self) -> None:
        """Rule with CRITICAL ambiguity (AMB-007) must appear in ambiguity_notes."""
        det = _make_determination(
            status="PARTIAL",
            rule_evals=[
                _make_rule_eval(
                    "MGNREGA-R002",
                    "UNDETERMINED",
                    ambiguity_notes=["AMB-007: Rural residence portability ambiguity"],
                ),
            ],
        )
        result = generate_gap_analysis(det, [det])

        assert len(result.ambiguity_notes) > 0

    def test_no_ambiguity_flags_produces_empty_ambiguity_notes(self) -> None:
        """Rules with no ambiguity flags → ambiguity_notes = []."""
        det = _make_determination(
            status="NEAR_MISS",
            rule_evals=[
                _make_rule_eval("PMKISAN-R001", "FAIL", ambiguity_notes=[]),
            ],
        )
        result = generate_gap_analysis(det, [det])

        assert result.ambiguity_notes == []


# ===========================================================================
# Group 6: generate_gap_analysis — never raises
# ===========================================================================

class TestGapAnalysisNeverRaises:
    """generate_gap_analysis must never propagate exceptions."""

    def test_determination_with_no_rule_evals_does_not_raise(self) -> None:
        """Empty rule_evaluations list must not cause an exception."""
        det = _make_determination(status="INSUFFICIENT_DATA", rule_evals=[])
        result = generate_gap_analysis(det, [det])

        assert isinstance(result, GapAnalysis)

    def test_generate_gap_analysis_with_multiple_all_schemes_does_not_raise(self) -> None:
        """Passing multiple determinations (for cross-referencing) must not raise."""
        det1 = _make_determination(scheme_id="PMKISAN", status="NEAR_MISS")
        det2 = _make_determination(scheme_id="MGNREGA", status="ELIGIBLE")

        result = generate_gap_analysis(det1, [det1, det2])

        assert isinstance(result, GapAnalysis)
