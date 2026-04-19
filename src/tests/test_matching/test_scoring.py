"""Tests for Feature 3: Three-tier confidence scoring.

Spec reference: docs/part2-planning/specs/03-confidence-scoring.md
Architecture:   docs/part2-planning/ARCHITECTURE-CONTRACT.md § src/matching/scoring.py

Three scoring dimensions:
  Rule Match Score (RMS)         — weighted fraction of evaluable rules that PASS
  Data Confidence (DC)           — audit quality × ambiguity penalties
  Profile Completeness Score (PC) — populated fields / required fields

Composite = min(RMS, DC, PC); bottleneck = argmin.
Labels: HIGH (≥0.80) | MEDIUM (≥0.60) | LOW (≥0.40) | VERY_LOW (≥0.20) | UNLIKELY (<0.20)

Tests will fail (ImportError) until Agent B implements src/matching/scoring.py.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.matching.scoring import (  # type: ignore[import]
    ConfidenceBreakdown,
    compute_confidence_breakdown,
    compute_data_confidence,
    compute_profile_completeness_score,
    compute_rule_match_score,
)


# ---------------------------------------------------------------------------
# Helpers — build RuleEvaluation-like mocks
# ---------------------------------------------------------------------------

def _eval_mock(
    outcome: str,
    audit_status: str = "VERIFIED",
    ambiguity_ids: list[str] | None = None,
) -> MagicMock:
    m = MagicMock()
    m.outcome = outcome
    m.audit_status = audit_status
    m.ambiguity_notes = ambiguity_ids or []
    return m


def _ambiguity_mock(flag_id: str, severity: str) -> MagicMock:
    m = MagicMock()
    m.flag_id = flag_id
    m.severity = MagicMock()
    m.severity.value = severity
    return m


# ===========================================================================
# Group 1: compute_rule_match_score
# ===========================================================================

class TestComputeRuleMatchScore:
    """RMS: weighted average of pass scores for evaluable (non-UNDETERMINED) rules."""

    def test_all_pass_returns_1_0(self) -> None:
        """All PASS → RMS = 1.0."""
        evals = [_eval_mock("PASS"), _eval_mock("PASS"), _eval_mock("PASS")]
        assert compute_rule_match_score(evals) == 1.0

    def test_all_fail_returns_0_0(self) -> None:
        """All FAIL → RMS = 0.0."""
        evals = [_eval_mock("FAIL"), _eval_mock("FAIL")]
        assert compute_rule_match_score(evals) == 0.0

    def test_all_undetermined_returns_0_0(self) -> None:
        """All UNDETERMINED → RMS = 0.0 (nothing evaluable)."""
        evals = [_eval_mock("UNDETERMINED"), _eval_mock("UNDETERMINED")]
        assert compute_rule_match_score(evals) == 0.0

    def test_unverified_pass_scores_0_7(self) -> None:
        """Single UNVERIFIED_PASS → RMS = 0.7 (not 1.0)."""
        evals = [_eval_mock("UNVERIFIED_PASS")]
        assert compute_rule_match_score(evals) == pytest.approx(0.7)

    def test_mix_pass_fail_computes_weighted_average(self) -> None:
        """1 PASS + 1 FAIL → average = (1.0 + 0.0) / 2 = 0.5."""
        evals = [_eval_mock("PASS"), _eval_mock("FAIL")]
        assert compute_rule_match_score(evals) == pytest.approx(0.5)

    def test_mix_pass_unverified_pass_fail(self) -> None:
        """1 PASS (1.0) + 1 UNVERIFIED_PASS (0.7) + 1 FAIL (0.0) → mean = 0.567."""
        evals = [_eval_mock("PASS"), _eval_mock("UNVERIFIED_PASS"), _eval_mock("FAIL")]
        expected = (1.0 + 0.7 + 0.0) / 3
        assert compute_rule_match_score(evals) == pytest.approx(expected, rel=1e-3)

    def test_undetermined_excluded_from_average(self) -> None:
        """UNDETERMINED rules are excluded; average is over evaluable only.
        1 PASS + 1 UNDETERMINED → RMS = 1.0 (only 1 evaluable rule)."""
        evals = [_eval_mock("PASS"), _eval_mock("UNDETERMINED")]
        assert compute_rule_match_score(evals) == pytest.approx(1.0)

    def test_empty_evaluations_returns_0_0(self) -> None:
        """Empty evaluation list → RMS = 0.0 (no rules to average)."""
        assert compute_rule_match_score([]) == 0.0

    def test_never_raises_on_unknown_outcome(self) -> None:
        """Unknown outcome strings must not raise — treated as UNDETERMINED."""
        evals = [_eval_mock("UNKNOWN_STATUS")]
        result = compute_rule_match_score(evals)
        assert isinstance(result, float)


# ===========================================================================
# Group 2: compute_data_confidence
# ===========================================================================

class TestComputeDataConfidence:
    """DC: audit status base scores minus ambiguity penalties."""

    def test_all_verified_rules_returns_1_0(self) -> None:
        """All VERIFIED rules → DC = 1.0."""
        evals = [_eval_mock("PASS", "VERIFIED"), _eval_mock("PASS", "VERIFIED")]
        assert compute_data_confidence(evals, []) == pytest.approx(1.0)

    def test_needs_review_rule_scores_0_7(self) -> None:
        """Single NEEDS_REVIEW rule → DC = 0.7."""
        evals = [_eval_mock("PASS", "NEEDS_REVIEW")]
        assert compute_data_confidence(evals, []) == pytest.approx(0.7)

    def test_pending_rule_scores_0_5(self) -> None:
        """Single PENDING rule → DC = 0.5."""
        evals = [_eval_mock("PASS", "PENDING")]
        assert compute_data_confidence(evals, []) == pytest.approx(0.5)

    def test_overridden_rule_scores_0_8(self) -> None:
        """Single OVERRIDDEN rule → DC = 0.8."""
        evals = [_eval_mock("PASS", "OVERRIDDEN")]
        assert compute_data_confidence(evals, []) == pytest.approx(0.8)

    def test_critical_ambiguity_caps_rule_score_at_0_3(self) -> None:
        """VERIFIED rule with CRITICAL ambiguity (AMB-007) → score capped at 0.30."""
        eval_with_amb = _eval_mock("PASS", "VERIFIED", ambiguity_ids=["AMB-007"])
        critical_flag = _ambiguity_mock("AMB-007", "CRITICAL")

        result = compute_data_confidence([eval_with_amb], [critical_flag])

        assert result <= 0.30

    def test_high_ambiguity_reduces_score_by_0_15(self) -> None:
        """VERIFIED rule with HIGH ambiguity → score = 1.0 - 0.15 = 0.85."""
        eval_with_high = _eval_mock("PASS", "VERIFIED", ambiguity_ids=["AMB-002"])
        high_flag = _ambiguity_mock("AMB-002", "HIGH")

        result = compute_data_confidence([eval_with_high], [high_flag])

        assert result == pytest.approx(0.85)

    def test_medium_ambiguity_reduces_score_by_0_05(self) -> None:
        """VERIFIED rule with MEDIUM ambiguity → score = 1.0 - 0.05 = 0.95."""
        eval_with_med = _eval_mock("PASS", "VERIFIED", ambiguity_ids=["AMB-004"])
        med_flag = _ambiguity_mock("AMB-004", "MEDIUM")

        result = compute_data_confidence([eval_with_med], [med_flag])

        assert result == pytest.approx(0.95)

    def test_no_ambiguity_flags_no_penalty(self) -> None:
        """VERIFIED rule with no ambiguity flags → DC = 1.0 (no penalty)."""
        evals = [_eval_mock("PASS", "VERIFIED")]
        result = compute_data_confidence(evals, [])
        assert result == pytest.approx(1.0)

    def test_mix_verified_needs_review_averages_correctly(self) -> None:
        """VERIFIED (1.0) + NEEDS_REVIEW (0.7) → DC = 0.85."""
        evals = [_eval_mock("PASS", "VERIFIED"), _eval_mock("PASS", "NEEDS_REVIEW")]
        result = compute_data_confidence(evals, [])
        assert result == pytest.approx(0.85)

    def test_empty_evaluations_returns_0_0(self) -> None:
        """Empty evaluations → DC = 0.0."""
        assert compute_data_confidence([], []) == 0.0

    def test_score_never_below_zero(self) -> None:
        """Multiple ambiguity penalties must not push score below 0.0."""
        eval_bad = _eval_mock("PASS", "PENDING", ambiguity_ids=["AMB-007", "AMB-002"])
        flags = [_ambiguity_mock("AMB-007", "CRITICAL"), _ambiguity_mock("AMB-002", "HIGH")]

        result = compute_data_confidence([eval_bad], flags)

        assert result >= 0.0


# ===========================================================================
# Group 3: compute_profile_completeness_score
# ===========================================================================

class TestComputeProfileCompletenessScore:
    """PC: populated fields / required fields for a scheme."""

    def test_all_fields_provided_returns_1_0(self) -> None:
        """All 3 required fields present → PC = 1.0."""
        required = {"applicant.age", "location.state", "household.bpl_status"}
        populated = {"applicant.age", "location.state", "household.bpl_status"}
        assert compute_profile_completeness_score(required, populated) == 1.0

    def test_half_fields_provided_returns_0_5(self) -> None:
        """2 of 4 required fields present → PC = 0.5."""
        required = {"a", "b", "c", "d"}
        populated = {"a", "b"}
        assert compute_profile_completeness_score(required, populated) == pytest.approx(0.5)

    def test_no_fields_provided_returns_0_0(self) -> None:
        """None of the required fields provided → PC = 0.0."""
        required = {"applicant.age", "location.state"}
        populated = set()
        assert compute_profile_completeness_score(required, populated) == 0.0

    def test_empty_required_set_returns_0_0(self) -> None:
        """Empty required set → PC = 0.0 (no fields to be complete over)."""
        assert compute_profile_completeness_score(set(), {"applicant.age"}) == 0.0

    def test_extra_fields_in_populated_not_counted(self) -> None:
        """Fields in populated but not in required must not inflate the score."""
        required = {"applicant.age"}
        populated = {"applicant.age", "extra.field", "another.field"}
        assert compute_profile_completeness_score(required, populated) == 1.0

    def test_score_bounded_between_0_and_1(self) -> None:
        """PC must always be in [0.0, 1.0]."""
        required = {"a", "b", "c"}
        populated = {"a"}
        score = compute_profile_completeness_score(required, populated)
        assert 0.0 <= score <= 1.0


# ===========================================================================
# Group 4: compute_confidence_breakdown (full composite)
# ===========================================================================

class TestComputeConfidenceBreakdown:
    """Composite = min(RMS, DC, PC); bottleneck = argmin dimension."""

    def test_composite_is_min_of_three_dimensions(self) -> None:
        """composite = min(RMS, DC, PC)."""
        evals = [_eval_mock("PASS", "VERIFIED")]
        required = {"applicant.age", "location.state"}
        populated = {"applicant.age"}  # PC = 0.5

        breakdown = compute_confidence_breakdown(evals, [], required, populated)

        assert breakdown.composite == pytest.approx(0.5)  # PC is bottleneck

    def test_bottleneck_identifies_lowest_dimension(self) -> None:
        """bottleneck label must name the dimension with lowest value."""
        evals = [_eval_mock("PASS", "VERIFIED")]
        required = {"applicant.age", "location.state"}
        populated = {"applicant.age"}  # PC = 0.5

        breakdown = compute_confidence_breakdown(evals, [], required, populated)

        assert breakdown.bottleneck == "profile_completeness"

    def test_bottleneck_rule_match_when_all_rules_fail(self) -> None:
        """All rules FAIL → RMS = 0.0 → bottleneck = rule_match."""
        evals = [_eval_mock("FAIL", "VERIFIED")]
        required = {"applicant.age"}
        populated = {"applicant.age"}  # PC = 1.0

        breakdown = compute_confidence_breakdown(evals, [], required, populated)

        assert breakdown.bottleneck == "rule_match"

    def test_bottleneck_data_confidence_when_critical_ambiguity_present(self) -> None:
        """CRITICAL ambiguity caps DC at 0.30 → bottleneck = data_confidence."""
        eval_amb = _eval_mock("PASS", "VERIFIED", ambiguity_ids=["AMB-007"])
        critical_flag = _ambiguity_mock("AMB-007", "CRITICAL")
        required = {"applicant.age"}
        populated = {"applicant.age"}

        breakdown = compute_confidence_breakdown(
            [eval_amb], [critical_flag], required, populated
        )

        assert breakdown.bottleneck == "data_confidence"
        assert breakdown.data_confidence <= 0.30

    def test_label_high_for_composite_above_0_80(self) -> None:
        """Composite ≥ 0.80 → label = HIGH."""
        evals = [_eval_mock("PASS", "VERIFIED")]
        required = {"applicant.age"}
        populated = {"applicant.age"}

        breakdown = compute_confidence_breakdown(evals, [], required, populated)

        assert breakdown.composite_label == "HIGH"

    def test_label_medium_for_composite_between_0_60_and_0_80(self) -> None:
        """Composite in [0.60, 0.80) → label = MEDIUM."""
        evals = [_eval_mock("UNVERIFIED_PASS", "PENDING")]  # RMS=0.7, DC=0.5
        required = {"applicant.age"}
        populated = {"applicant.age"}

        breakdown = compute_confidence_breakdown(evals, [], required, populated)

        # Composite = min(0.7, 0.5, 1.0) = 0.5 → LOW
        assert breakdown.composite_label in ("MEDIUM", "LOW")

    def test_label_unlikely_for_composite_below_0_20(self) -> None:
        """Composite < 0.20 → label = UNLIKELY."""
        evals = [_eval_mock("FAIL", "PENDING")]  # RMS=0.0
        required = {"a", "b", "c", "d", "e"}
        populated = set()  # PC = 0.0

        breakdown = compute_confidence_breakdown(evals, [], required, populated)

        assert breakdown.composite_label == "UNLIKELY"

    def test_breakdown_returns_confidence_breakdown_instance(self) -> None:
        """Return type must be ConfidenceBreakdown dataclass."""
        evals = [_eval_mock("PASS", "VERIFIED")]
        required = {"applicant.age"}
        populated = {"applicant.age"}

        result = compute_confidence_breakdown(evals, [], required, populated)

        assert isinstance(result, ConfidenceBreakdown)
        assert hasattr(result, "rule_match_score")
        assert hasattr(result, "data_confidence")
        assert hasattr(result, "profile_completeness")
        assert hasattr(result, "composite")
        assert hasattr(result, "composite_label")
        assert hasattr(result, "bottleneck")
        assert hasattr(result, "bottleneck_explanation")
        assert hasattr(result, "improvement_actions")

    def test_improvement_actions_non_empty_when_below_high_threshold(self) -> None:
        """When composite < 0.80, improvement_actions must be non-empty."""
        evals = [_eval_mock("FAIL", "VERIFIED")]
        required = {"applicant.age", "location.state"}
        populated = {"applicant.age"}

        breakdown = compute_confidence_breakdown(evals, [], required, populated)

        assert len(breakdown.improvement_actions) > 0

    def test_never_raises_on_empty_input(self) -> None:
        """Empty inputs must not raise — return valid ConfidenceBreakdown with 0.0 composite."""
        result = compute_confidence_breakdown([], [], set(), set())

        assert isinstance(result, ConfidenceBreakdown)
        assert result.composite == 0.0
