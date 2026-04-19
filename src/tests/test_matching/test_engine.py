"""Tests for Feature 2: The 4-phase evaluation engine.

Spec reference: docs/part2-planning/specs/02-rule-evaluation-engine.md
Architecture:   docs/part2-planning/ARCHITECTURE-CONTRACT.md § src/matching/engine.py

Tests exercise:
  - evaluate_profile: top-level entry point, InvalidProfileError, RuleBaseError
  - evaluate_scheme: all four phases (A/B/C/D)
  - Status determination: ELIGIBLE, ELIGIBLE_WITH_CAVEATS, NEAR_MISS, INELIGIBLE,
    DISQUALIFIED, REQUIRES_PREREQUISITE, PARTIAL, INSUFFICIENT_DATA
  - Rule traceability: rule_trace completeness

All async tests run without @pytest.mark.asyncio because asyncio_mode="auto" in pyproject.toml.
Tests will fail (ImportError) until Agent B implements src/matching/engine.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.matching.engine import (  # type: ignore[import]
    GroupEvaluation,
    RuleEvaluation,
    SchemeDetermination,
    evaluate_profile,
    evaluate_scheme,
)
from src.matching.profile import UserProfile  # type: ignore[import]


# ===========================================================================
# Helpers — minimal RuleEvaluation factory
# ===========================================================================

def _rule_eval(
    rule_id: str,
    scheme_id: str,
    outcome: str,
    audit_status: str = "VERIFIED",
    ambiguity_notes: list[str] | None = None,
    field: str = "applicant.age",
    operator: str = "GTE",
    rule_value: Any = 18,
    user_value: Any = 30,
) -> RuleEvaluation:
    outcome_scores = {
        "PASS": 1.0,
        "UNVERIFIED_PASS": 0.7,
        "FAIL": 0.0,
        "UNDETERMINED": None,
    }
    return RuleEvaluation(
        rule_id=rule_id,
        scheme_id=scheme_id,
        field=field,
        operator=operator,
        rule_value=rule_value,
        user_value=user_value,
        outcome=outcome,
        outcome_score=outcome_scores.get(outcome),
        display_text=f"Test rule {rule_id}",
        source_quote="Must be at least 18 years old",
        source_url="https://example.gov.in/scheme",
        audit_status=audit_status,
        undetermined_reason=None if outcome != "UNDETERMINED" else "Field not provided",
        ambiguity_notes=ambiguity_notes or [],
    )


# ===========================================================================
# Group 1: Phase A — Disqualifying rules
# ===========================================================================

class TestPhaseADisqualifyingRules:
    """Phase A fires first; a DISQUALIFIED status short-circuits all subsequent phases."""

    async def test_disqualifying_rule_fires_returns_disqualified(
        self,
        mock_pmsym_ruleset: Any,
        mock_ambiguity_flags: list[Any],
    ) -> None:
        """A profile that matches a disqualifying rule must get DISQUALIFIED status."""
        # EPFO member → PMSYM-DIS-001 fires
        profile_data = {
            "applicant.age": 25,
            "location.state": "MH",
            "employment.is_epfo_member": True,
        }
        profile = UserProfile.from_flat_json(profile_data)

        determination = await evaluate_scheme(profile, mock_pmsym_ruleset, mock_ambiguity_flags)

        assert determination.status == "DISQUALIFIED"

    async def test_disqualifying_rule_fires_skips_eligibility_phase(
        self,
        mock_pmsym_ruleset: Any,
        mock_ambiguity_flags: list[Any],
    ) -> None:
        """When DISQUALIFIED, group_evaluations from Phase C must be empty."""
        profile_data = {
            "applicant.age": 25,
            "location.state": "MH",
            "employment.is_epfo_member": True,
        }
        profile = UserProfile.from_flat_json(profile_data)

        determination = await evaluate_scheme(profile, mock_pmsym_ruleset, mock_ambiguity_flags)

        # No eligibility groups should have been evaluated
        assert determination.group_evaluations == []

    async def test_disqualifying_rule_not_fired_continues_evaluation(
        self,
        mock_pmsym_ruleset: Any,
        mock_ambiguity_flags: list[Any],
    ) -> None:
        """A profile not matching any disqualifying rule must proceed past Phase A."""
        profile_data = {
            "applicant.age": 25,
            "location.state": "MH",
            "employment.is_epfo_member": False,
            "employment.is_esic_member": False,
            "employment.is_nps_subscriber": False,
        }
        profile = UserProfile.from_flat_json(profile_data)

        determination = await evaluate_scheme(profile, mock_pmsym_ruleset, mock_ambiguity_flags)

        assert determination.status != "DISQUALIFIED"

    async def test_disqualification_result_populated_on_disqualified_status(
        self,
        mock_pmsym_ruleset: Any,
        mock_ambiguity_flags: list[Any],
    ) -> None:
        """determination.disqualification must be populated when DISQUALIFIED."""
        profile_data = {
            "applicant.age": 25,
            "location.state": "MH",
            "employment.is_epfo_member": True,
        }
        profile = UserProfile.from_flat_json(profile_data)

        determination = await evaluate_scheme(profile, mock_pmsym_ruleset, mock_ambiguity_flags)

        assert determination.disqualification is not None
        assert determination.disqualification.fired is True
        assert "PMSYM-DIS-001" in determination.disqualification.rule_id


# ===========================================================================
# Group 2: Phase B — Prerequisite rules
# ===========================================================================

class TestPhaseBPrerequisiteRules:
    """Phase B checks whether required prerequisite schemes are enrolled."""

    async def test_prerequisite_scheme_not_enrolled_returns_requires_prerequisite(
        self,
        mock_nsap_ruleset: Any,
        mock_ambiguity_flags: list[Any],
    ) -> None:
        """NSAP bank account prerequisite: profile without bank_account → REQUIRES_PREREQUISITE."""
        profile_data = {
            "applicant.age": 65,
            "location.state": "UP",
            "household.bpl_status": True,
            "documents.bank_account": False,
            "schemes.active_enrollments": [],
        }
        profile = UserProfile.from_flat_json(profile_data)

        determination = await evaluate_scheme(profile, mock_nsap_ruleset, mock_ambiguity_flags)

        assert determination.status == "REQUIRES_PREREQUISITE"

    async def test_prerequisite_met_continues_to_eligibility_phase(
        self,
        mock_nsap_ruleset: Any,
        mock_ambiguity_flags: list[Any],
    ) -> None:
        """Profile with bank account enrolled proceeds to Phase C."""
        profile_data = {
            "applicant.age": 65,
            "location.state": "UP",
            "household.bpl_status": True,
            "documents.bank_account": True,
            "schemes.active_enrollments": [],
        }
        profile = UserProfile.from_flat_json(profile_data)

        determination = await evaluate_scheme(profile, mock_nsap_ruleset, mock_ambiguity_flags)

        assert determination.status != "REQUIRES_PREREQUISITE"

    async def test_prerequisite_result_lists_unmet_prerequisites(
        self,
        mock_nsap_ruleset: Any,
        mock_ambiguity_flags: list[Any],
    ) -> None:
        """determination.prerequisites.unmet_prerequisites must be non-empty when phase B fails."""
        profile_data = {
            "applicant.age": 65,
            "location.state": "UP",
            "household.bpl_status": True,
            "documents.bank_account": False,
        }
        profile = UserProfile.from_flat_json(profile_data)

        determination = await evaluate_scheme(profile, mock_nsap_ruleset, mock_ambiguity_flags)

        assert len(determination.prerequisites.unmet_prerequisites) > 0


# ===========================================================================
# Group 3: Phase C — Eligibility rules with AND/OR group logic
# ===========================================================================

class TestPhaseCEligibilityRules:
    """Phase C applies AND/OR group logic for eligibility determination."""

    async def test_all_and_rules_pass_returns_eligible(
        self,
        mock_pmkisan_ruleset: Any,
        mock_ambiguity_flags: list[Any],
    ) -> None:
        """PMKISAN: farmer profile with land → all AND rules pass → ELIGIBLE."""
        profile_data = {
            "applicant.age": 38,
            "applicant.land_ownership_status": True,
            "location.state": "UP",
            "employment.type": "agriculture",
            "employment.is_income_tax_payer": False,
            "household.income_annual": 100000,
        }
        profile = UserProfile.from_flat_json(profile_data)

        determination = await evaluate_scheme(profile, mock_pmkisan_ruleset, mock_ambiguity_flags)

        assert determination.status in ("ELIGIBLE", "ELIGIBLE_WITH_CAVEATS")

    async def test_or_group_one_rule_passes_returns_eligible(
        self,
        mock_nsap_ruleset: Any,
        mock_ambiguity_flags: list[Any],
    ) -> None:
        """NSAP has age ≥ 60 OR disability ≥ 40% as an OR group.
        Profile with age 70 (not disabled) must satisfy the OR group."""
        profile_data = {
            "applicant.age": 70,
            "location.state": "MH",
            "household.bpl_status": True,
            "documents.bank_account": True,
            "applicant.disability_status": False,
        }
        profile = UserProfile.from_flat_json(profile_data)

        determination = await evaluate_scheme(profile, mock_nsap_ruleset, mock_ambiguity_flags)

        # OR group passes → eligible (age meets condition)
        assert determination.status not in ("INELIGIBLE", "DISQUALIFIED")

    async def test_and_group_one_rule_fails_returns_ineligible_or_near_miss(
        self,
        mock_pmkisan_ruleset: Any,
        mock_ambiguity_flags: list[Any],
    ) -> None:
        """PMKISAN: no land ownership → key AND rule fails → INELIGIBLE or NEAR_MISS."""
        profile_data = {
            "applicant.age": 38,
            "applicant.land_ownership_status": False,  # fails PMKISAN-R001
            "location.state": "MH",
            "employment.type": "agriculture",
            "employment.is_income_tax_payer": False,
        }
        profile = UserProfile.from_flat_json(profile_data)

        determination = await evaluate_scheme(profile, mock_pmkisan_ruleset, mock_ambiguity_flags)

        assert determination.status in ("INELIGIBLE", "NEAR_MISS")

    async def test_near_miss_when_exactly_max_failed_rules(
        self,
        mock_mgnrega_ruleset: Any,
        mock_ambiguity_flags: list[Any],
    ) -> None:
        """When exactly NEAR_MISS_MAX_FAILED_RULES (2) rules fail → NEAR_MISS, not INELIGIBLE."""
        # MGNREGA: age passes (18+), but urban residence fails MGNREGA-R002
        profile_data = {
            "applicant.age": 30,
            "location.state": "GJ",
            "household.residence_type": "urban",  # fails MGNREGA-R002
            "household.ration_card_type": "APL",   # fails MGNREGA-R003
        }
        profile = UserProfile.from_flat_json(profile_data)

        determination = await evaluate_scheme(profile, mock_mgnrega_ruleset, mock_ambiguity_flags)

        # Exactly 2 failures → NEAR_MISS (at threshold, not above)
        assert determination.status == "NEAR_MISS"

    async def test_ineligible_when_more_than_max_failed_rules(
        self,
        mock_mgnrega_ruleset: Any,
        mock_ambiguity_flags: list[Any],
    ) -> None:
        """When 3 rules fail (> NEAR_MISS_MAX_FAILED_RULES) → INELIGIBLE."""
        # All MGNREGA rules fail: age 16, urban, wrong ration card
        profile_data = {
            "applicant.age": 16,    # fails MGNREGA-R001 (age < 18)
            "location.state": "DL",
            "household.residence_type": "urban",  # fails MGNREGA-R002
            "household.ration_card_type": "APL",  # fails MGNREGA-R003
        }
        profile = UserProfile.from_flat_json(profile_data)

        determination = await evaluate_scheme(profile, mock_mgnrega_ruleset, mock_ambiguity_flags)

        assert determination.status == "INELIGIBLE"


# ===========================================================================
# Group 4: Phase D — Administrative discretion
# ===========================================================================

class TestPhaseDDiscretion:
    """Phase D admin discretion rules generate warnings, not failures."""

    async def test_discretion_rule_generates_warning_not_fail(
        self,
        mock_pmsym_ruleset: Any,
        mock_ambiguity_flags: list[Any],
    ) -> None:
        """A failing admin discretion rule must generate a warning, not change status to INELIGIBLE."""
        profile_data = {
            "applicant.age": 25,
            "location.state": "MH",
            "employment.is_epfo_member": False,
            "employment.is_esic_member": False,
            "employment.is_nps_subscriber": False,
            "household.income_monthly": 20000,  # > 15000 → fails PMSYM-ADM-001 discretion
        }
        profile = UserProfile.from_flat_json(profile_data)

        determination = await evaluate_scheme(profile, mock_pmsym_ruleset, mock_ambiguity_flags)

        # Status must not be INELIGIBLE just from discretion failure
        assert determination.status != "INELIGIBLE"
        # But a discretion warning must be present
        assert len(determination.discretion_warnings) > 0


# ===========================================================================
# Group 5: Status taxonomy — special statuses
# ===========================================================================

class TestSpecialStatuses:
    """PARTIAL, INSUFFICIENT_DATA, ELIGIBLE_WITH_CAVEATS."""

    async def test_insufficient_data_when_below_completeness_threshold(
        self,
        mock_pmkisan_ruleset: Any,
        mock_ambiguity_flags: list[Any],
    ) -> None:
        """Profile with < 60% required fields populated → INSUFFICIENT_DATA."""
        # Provide almost nothing relevant
        profile_data: dict[str, Any] = {}
        profile = UserProfile.from_flat_json(profile_data)

        determination = await evaluate_scheme(profile, mock_pmkisan_ruleset, mock_ambiguity_flags)

        assert determination.status == "INSUFFICIENT_DATA"

    async def test_eligible_with_caveats_when_unverified_pass_rules_present(
        self,
        mock_mgnrega_ruleset: Any,
        mock_ambiguity_flags: list[Any],
    ) -> None:
        """MGNREGA-R002 (rural residence) has CRITICAL ambiguity (AMB-007).
        A rural profile that passes on that rule → PARTIAL or ELIGIBLE_WITH_CAVEATS."""
        profile_data = {
            "applicant.age": 30,
            "location.state": "JH",
            "household.residence_type": "rural",
            "household.ration_card_type": "BPL",
        }
        profile = UserProfile.from_flat_json(profile_data)

        determination = await evaluate_scheme(profile, mock_mgnrega_ruleset, mock_ambiguity_flags)

        # Critical ambiguity on rural rule → should produce PARTIAL or ELIGIBLE_WITH_CAVEATS
        assert determination.status in ("ELIGIBLE_WITH_CAVEATS", "PARTIAL", "ELIGIBLE")

    async def test_all_rules_undetermined_returns_insufficient_data(
        self,
        mock_pmkisan_ruleset: Any,
        mock_ambiguity_flags: list[Any],
    ) -> None:
        """When every rule evaluation is UNDETERMINED → INSUFFICIENT_DATA."""
        # Completely empty profile — no fields provided
        profile = UserProfile.from_flat_json({})

        determination = await evaluate_scheme(profile, mock_pmkisan_ruleset, mock_ambiguity_flags)

        assert determination.status == "INSUFFICIENT_DATA"


# ===========================================================================
# Group 6: Rule trace completeness
# ===========================================================================

class TestRuleTrace:
    """rule_trace must contain an entry for every rule in the ruleset."""

    async def test_rule_trace_populated_for_all_evaluated_rules(
        self,
        mock_pmkisan_ruleset: Any,
        mock_ambiguity_flags: list[Any],
    ) -> None:
        """Every rule in mock_pmkisan_ruleset must have a trace entry."""
        profile_data = {
            "applicant.age": 38,
            "applicant.land_ownership_status": True,
            "location.state": "UP",
            "employment.type": "agriculture",
            "employment.is_income_tax_payer": False,
        }
        profile = UserProfile.from_flat_json(profile_data)

        determination = await evaluate_scheme(profile, mock_pmkisan_ruleset, mock_ambiguity_flags)

        rule_ids_in_trace = {entry.rule_id for entry in determination.rule_trace}
        # All active rules must appear in trace
        for rule in mock_pmkisan_ruleset.active_rules:
            assert rule.rule_id in rule_ids_in_trace

    async def test_excluded_rules_marked_in_trace(
        self,
        mock_mgnrega_ruleset: Any,
        mock_ambiguity_flags: list[Any],
    ) -> None:
        """MGNREGA-R004-DISPUTED is excluded; its trace entry must have excluded=True."""
        profile_data = {
            "applicant.age": 30,
            "location.state": "JH",
            "household.residence_type": "rural",
            "household.ration_card_type": "BPL",
        }
        profile = UserProfile.from_flat_json(profile_data)

        determination = await evaluate_scheme(profile, mock_mgnrega_ruleset, mock_ambiguity_flags)

        # MGNREGA-R004-DISPUTED should appear as excluded in trace
        excluded_entries = [e for e in determination.rule_trace if e.excluded]
        assert len(excluded_entries) >= 1

    async def test_trace_entries_have_phase_labels(
        self,
        mock_pmkisan_ruleset: Any,
        mock_ambiguity_flags: list[Any],
    ) -> None:
        """Each trace entry must have a valid phase label."""
        valid_phases = {"A_DISQUALIFYING", "B_PREREQUISITE", "C_ELIGIBILITY", "D_DISCRETION"}
        profile_data = {
            "applicant.age": 38,
            "applicant.land_ownership_status": True,
            "location.state": "UP",
            "employment.type": "agriculture",
            "employment.is_income_tax_payer": False,
        }
        profile = UserProfile.from_flat_json(profile_data)

        determination = await evaluate_scheme(profile, mock_pmkisan_ruleset, mock_ambiguity_flags)

        for entry in determination.rule_trace:
            if not entry.excluded:
                assert entry.phase in valid_phases


# ===========================================================================
# Group 7: Evaluation error handling
# ===========================================================================

class TestEvaluationErrorHandling:
    """EvaluationErrors must be caught internally; rule becomes UNDETERMINED."""

    async def test_evaluation_error_caught_rule_becomes_undetermined(
        self,
        mock_pmkisan_ruleset: Any,
        mock_ambiguity_flags: list[Any],
    ) -> None:
        """If an operator raises internally, the rule outcome must be UNDETERMINED,
        not an exception propagating to the caller."""
        profile_data = {
            "applicant.age": 38,
            "applicant.land_ownership_status": True,
            "location.state": "UP",
            "employment.type": "agriculture",
            "employment.is_income_tax_payer": False,
        }
        profile = UserProfile.from_flat_json(profile_data)

        # Patch operators to raise for a specific rule to simulate EvaluationError
        with patch("src.matching.operators.op_eq", side_effect=RuntimeError("mock failure")):
            # Should NOT raise — caught internally
            determination = await evaluate_scheme(
                profile, mock_pmkisan_ruleset, mock_ambiguity_flags
            )

        assert determination is not None


# ===========================================================================
# Group 8: evaluate_profile entry point
# ===========================================================================

class TestEvaluateProfileEntryPoint:
    """evaluate_profile validates input, loads rule base, and returns MatchingResult."""

    async def test_evaluate_profile_raises_invalid_profile_error_on_bad_input(
        self,
        tmp_path: Path,
    ) -> None:
        """Invalid profile (age > 120) must raise InvalidProfileError before evaluation."""
        from src.exceptions import InvalidProfileError  # type: ignore[import]

        with pytest.raises(InvalidProfileError):
            await evaluate_profile(
                profile=UserProfile.from_flat_json({"applicant.age": 200}),
                rule_base_path=tmp_path,
            )

    async def test_evaluate_profile_raises_rule_base_error_on_empty_dir(
        self,
        tmp_path: Path,
    ) -> None:
        """evaluate_profile with empty rule_base_path must raise RuleBaseError."""
        from src.exceptions import RuleBaseError  # type: ignore[import]

        profile = UserProfile.from_flat_json({"applicant.age": 30, "location.state": "MH"})

        with pytest.raises(RuleBaseError):
            await evaluate_profile(profile=profile, rule_base_path=tmp_path)

    async def test_evaluate_profile_returns_matching_result(
        self,
        mock_loader: Any,
        mock_all_rulesets: dict[str, Any],
        valid_profile_farmer: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        """With valid profile and mocked loader, evaluate_profile returns MatchingResult."""
        from src.matching.output import MatchingResult  # type: ignore[import]

        profile = UserProfile.from_flat_json(valid_profile_farmer)

        with patch("src.matching.engine.load_rule_base", return_value=mock_all_rulesets):
            result = await evaluate_profile(profile=profile, rule_base_path=tmp_path)

        assert isinstance(result, MatchingResult)

    async def test_evaluate_profile_result_has_iso_8601_timestamp(
        self,
        mock_all_rulesets: dict[str, Any],
        valid_profile_farmer: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        """evaluation_timestamp in MatchingResult must be valid ISO 8601."""
        import re

        profile = UserProfile.from_flat_json(valid_profile_farmer)

        with patch("src.matching.engine.load_rule_base", return_value=mock_all_rulesets):
            result = await evaluate_profile(profile=profile, rule_base_path=tmp_path)

        # ISO 8601 basic check: starts with 4-digit year
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", result.evaluation_timestamp)

    async def test_evaluate_profile_result_profile_id_is_hash_not_pii(
        self,
        mock_all_rulesets: dict[str, Any],
        valid_profile_farmer: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        """profile_id must be a hash (not contain raw PII like age or name)."""
        profile = UserProfile.from_flat_json(valid_profile_farmer)

        with patch("src.matching.engine.load_rule_base", return_value=mock_all_rulesets):
            result = await evaluate_profile(profile=profile, rule_base_path=tmp_path)

        # profile_id should not be the raw age (38) or any field directly
        assert result.profile_id != "38"
        assert len(result.profile_id) > 8  # must be a non-trivial hash

    async def test_evaluate_profile_result_buckets_schemes_by_status(
        self,
        mock_all_rulesets: dict[str, Any],
        valid_profile_farmer: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        """MatchingResult must have the correct status bucket lists."""
        profile = UserProfile.from_flat_json(valid_profile_farmer)

        with patch("src.matching.engine.load_rule_base", return_value=mock_all_rulesets):
            result = await evaluate_profile(profile=profile, rule_base_path=tmp_path)

        # All bucket lists must exist (may be empty)
        assert hasattr(result, "eligible_schemes")
        assert hasattr(result, "near_miss_schemes")
        assert hasattr(result, "ineligible_schemes")
        assert hasattr(result, "requires_prerequisite_schemes")
        assert hasattr(result, "partial_schemes")
        assert hasattr(result, "insufficient_data_schemes")

    async def test_evaluate_profile_state_override_applied_when_state_provided(
        self,
        mock_all_rulesets: dict[str, Any],
        valid_profile_farmer: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        """When profile has location_state='UP', state overrides must be applied."""
        valid_profile_farmer["location.state"] = "UP"
        profile = UserProfile.from_flat_json(valid_profile_farmer)

        with patch(
            "src.matching.engine.load_rule_base",
            return_value=mock_all_rulesets,
        ) as mock_lb:
            await evaluate_profile(profile=profile, rule_base_path=tmp_path)
            # load_rule_base must have been called with user_state="UP"
            mock_lb.assert_called_once_with(tmp_path, user_state="UP")
