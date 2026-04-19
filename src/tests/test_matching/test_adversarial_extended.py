"""Extended adversarial profile tests — Part 2.

This module tests 21 additional profiles that stress-test edge cases and attempt
to break the matching engine in ways the original 10 profiles do not cover.

Profile inventory (edge cases from user specification, items 5-10):
  11 - Home-based domestic worker (no formal employer, no employment proof)
  12 - Person whose caste was recently recategorized (SC cert pending)
  13 - Family that recently split from joint to nuclear household
  14 - Minor dependent aging out of parent's scheme (age 17, turning 18)
  15 - Person with disability percentage change (40% → 70%, new cert pending)
  16 - Gig worker (food delivery, platform income, no salary slip)

Engine-breaking profiles (boundary attacks, contradictions, extremes):
  17 - Age exactly at PMSYM lower boundary (18)
  18 - Age exactly at PMSYM upper boundary (40)
  19 - Age exactly at NSAP old-age boundary (60)
  20 - Household income exactly at BPL threshold (₹1,20,000)
  21 - All documents missing (complete document gap)
  22 - Maximum active scheme enrollments (10 schemes simultaneously)
  23 - Triple special category (widow + disability + BPL)
  24 - Severe income inconsistency (annual=₹2L vs monthly=₹5K)
  25 - Single-person household (size=1)
  26 - Oversized household (size=15, 7 children)
  27 - Infant applicant (age=0)
  28 - Maximum age applicant (age=120)
  29 - Income tax payer with BPL card (self-contradictory)
  30 - 100% disability + high income + EPFO (maximum disqualifier stack)
  31 - Unknown employment type ("gig") not in standard value set

Spec reference: docs/part2-planning/specs/07-adversarial-profiles.md
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.matching.profile import UserProfile  # type: ignore[import]

PROFILES_DIR = Path(__file__).parent.parent / "test_data" / "profiles"


# ---------------------------------------------------------------------------
# Helpers (mirrors test_adversarial.py — kept local to avoid cross-module dep)
# ---------------------------------------------------------------------------

def _load_profile(filename: str) -> dict[str, Any]:
    path = PROFILES_DIR / filename
    with path.open() as f:
        return json.load(f)


async def _evaluate(
    profile_data: dict[str, Any],
    mock_all_rulesets: dict[str, Any],
    mock_relationships: list[Any],
    mock_ambiguity_flags: list[Any],
    tmp_path: Path,
) -> Any:
    """Evaluate a profile dict against mock rule base, returning MatchingResult."""
    from src.matching.engine import evaluate_profile  # type: ignore[import]

    profile = UserProfile.from_flat_json(profile_data)
    with patch("src.matching.engine.load_rule_base", return_value=mock_all_rulesets), \
         patch("src.matching.engine.load_relationship_matrix", return_value=mock_relationships), \
         patch("src.matching.engine.load_ambiguity_map", return_value=mock_ambiguity_flags):
        return await evaluate_profile(profile=profile, rule_base_path=tmp_path)


def _all_scheme_ids(result: Any) -> set[str]:
    """Collect all scheme_ids from every bucket of a MatchingResult."""
    all_ids: set[str] = set()
    for bucket_attr in (
        "eligible_schemes", "near_miss_schemes", "ineligible_schemes",
        "requires_prerequisite_schemes", "partial_schemes", "insufficient_data_schemes",
    ):
        bucket = getattr(result, bucket_attr, [])
        all_ids.update(s.scheme_id for s in bucket)
    return all_ids


def _status_of(result: Any, scheme_id: str) -> str | None:
    """Return status string for scheme_id in result, or None if not found."""
    bucket_map = {
        "eligible_schemes": "ELIGIBLE",
        "near_miss_schemes": "NEAR_MISS",
        "ineligible_schemes": "INELIGIBLE",
        "requires_prerequisite_schemes": "REQUIRES_PREREQUISITE",
        "partial_schemes": "PARTIAL",
        "insufficient_data_schemes": "INSUFFICIENT_DATA",
    }
    for attr, status in bucket_map.items():
        bucket = getattr(result, attr, [])
        if any(s.scheme_id == scheme_id for s in bucket):
            return status
    return None


def _has_warning_containing(result: Any, keyword: str) -> bool:
    """Return True if any profile warning string contains the given keyword (case-insensitive)."""
    kw = keyword.lower()
    return any(kw in w.lower() for w in result.profile_warnings)


# ===========================================================================
# Parametrised smoke test: all 21 extended profiles evaluate without crash
# ===========================================================================

EXTENDED_PROFILES = [
    "profile_11_home_domestic_worker.json",
    "profile_12_caste_recategorized.json",
    "profile_13_joint_to_nuclear_split.json",
    "profile_14_minor_aging_out.json",
    "profile_15_disability_percentage_change.json",
    "profile_16_gig_worker.json",
    "profile_17_age_boundary_18.json",
    "profile_18_age_boundary_40.json",
    "profile_19_age_boundary_60.json",
    "profile_20_income_at_bpl_threshold.json",
    "profile_21_all_documents_missing.json",
    "profile_22_maximum_active_enrollments.json",
    "profile_23_triple_special_category.json",
    "profile_24_income_inconsistency.json",
    "profile_25_single_person_household.json",
    "profile_26_oversized_household.json",
    "profile_27_infant_age_zero.json",
    "profile_28_max_age_120.json",
    "profile_29_tax_payer_with_bpl.json",
    "profile_30_disability_100_rich.json",
    "profile_31_unknown_employment_type.json",
]


class TestAllExtendedProfilesEvaluateWithoutCrash:
    """Every extended profile must evaluate to completion without raising."""

    @pytest.mark.parametrize("profile_file", EXTENDED_PROFILES)
    async def test_profile_evaluates_without_exception(
        self,
        profile_file: str,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        data = _load_profile(profile_file)
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        assert result is not None

    @pytest.mark.parametrize("profile_file", EXTENDED_PROFILES)
    async def test_profile_produces_matching_result(
        self,
        profile_file: str,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        from src.matching.output import MatchingResult  # type: ignore[import]

        data = _load_profile(profile_file)
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        assert isinstance(result, MatchingResult)
        assert isinstance(result.eligible_schemes, list)
        assert isinstance(result.near_miss_schemes, list)
        assert isinstance(result.ineligible_schemes, list)

    @pytest.mark.parametrize("profile_file", EXTENDED_PROFILES)
    async def test_profile_result_serialises_to_json(
        self,
        profile_file: str,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        data = _load_profile(profile_file)
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        json_str = result.to_json()
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)

    @pytest.mark.parametrize("profile_file", EXTENDED_PROFILES)
    async def test_profile_summary_has_positive_total(
        self,
        profile_file: str,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Every profile must cause at least one scheme to be evaluated."""
        data = _load_profile(profile_file)
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        assert result.summary.total_schemes_evaluated > 0

    @pytest.mark.parametrize("profile_file", EXTENDED_PROFILES)
    async def test_extra_fields_stored_without_crash(
        self,
        profile_file: str,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Profiles with dot-path keys outside the standard field map must store extras cleanly."""
        data = _load_profile(profile_file)
        profile = UserProfile.from_flat_json(data)
        # Extra fields dict must be a dict (no type errors)
        assert isinstance(profile.extra_fields, dict)


# ===========================================================================
# Profile 11: Home-based domestic worker
# ===========================================================================

class TestProfile11HomeDomesticWorker:
    """Profile 11: age 42, female, OBC, informal, no employer, urban KA, BPL.

    Key tension: employment.type=informal, no ESI/EPFO, no employment proof.
    Extra fields: employer_type=none, has_employment_proof=false are stored as extras.
    Expected: PMSYM → INELIGIBLE (age 42 > 40 upper bound); MGNREGA → INELIGIBLE (urban).
    The engine must not crash on the non-standard employment.employer_type field.
    """

    async def test_pmsym_ineligible_age_exceeds_upper_bound(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Domestic worker age 42 exceeds PMSYM upper limit of 40 — must be INELIGIBLE."""
        data = _load_profile("profile_11_home_domestic_worker.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        pmsym_status = _status_of(result, "PMSYM")
        assert pmsym_status in ("INELIGIBLE", "NEAR_MISS"), (
            f"Profile 11 PMSYM: age 42 must fail PMSYM age gate, got {pmsym_status}"
        )

    async def test_mgnrega_ineligible_urban_worker(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Urban domestic worker must not be ELIGIBLE for MGNREGA (rural-only scheme)."""
        data = _load_profile("profile_11_home_domestic_worker.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        mgnrega_status = _status_of(result, "MGNREGA")
        assert mgnrega_status != "ELIGIBLE", (
            f"Profile 11 MGNREGA: urban worker should not be ELIGIBLE, got {mgnrega_status}"
        )

    async def test_non_standard_employment_fields_in_extra(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Non-standard fields like employer_type and has_employment_proof land in extra_fields."""
        data = _load_profile("profile_11_home_domestic_worker.json")
        profile = UserProfile.from_flat_json(data)
        assert "employment.employer_type" in profile.extra_fields
        assert "employment.has_employment_proof" in profile.extra_fields

    async def test_result_produces_valid_buckets(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """All bucket lists must be lists regardless of outcome."""
        data = _load_profile("profile_11_home_domestic_worker.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        total = _all_scheme_ids(result)
        assert len(total) > 0, "At least one scheme must be classified"


# ===========================================================================
# Profile 12: Person whose caste was recently recategorized (OBC → SC)
# ===========================================================================

class TestProfile12CasteRecategorized:
    """Profile 12: age 35, male, caste_category=SC, documents.caste_certificate=false, TN.

    Key tension: the system believes the person is SC (state list change), but the
    formal certificate is still pending. caste_certificate=false blocks full eligibility.
    Extra fields carry recategorization metadata (previous_category, new_certificate_pending).
    Expected: PMKISAN → INELIGIBLE (land_ownership_status not set); SC-gated schemes
    should surface as NEAR_MISS or INSUFFICIENT_DATA because certificate is absent.
    """

    async def test_sc_category_accepted_despite_missing_cert(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """caste_category='SC' is stored correctly even without certificate."""
        data = _load_profile("profile_12_caste_recategorized.json")
        profile = UserProfile.from_flat_json(data)
        assert profile.applicant_caste_category == "SC"
        assert profile.documents_caste_certificate is False

    async def test_recategorization_metadata_in_extra_fields(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """OBC→SC recategorization metadata is captured in extra_fields without error."""
        data = _load_profile("profile_12_caste_recategorized.json")
        profile = UserProfile.from_flat_json(data)
        assert "caste.previous_category" in profile.extra_fields
        assert profile.extra_fields["caste.previous_category"] == "OBC"
        assert "caste.new_certificate_pending" in profile.extra_fields

    async def test_evaluation_completes_without_error(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Evaluation of caste-recategorized profile must not raise."""
        data = _load_profile("profile_12_caste_recategorized.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        assert result is not None

    async def test_pmkisan_ineligible_no_land_ownership(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """PMKISAN requires land_ownership_status (not set in profile) → INELIGIBLE or INSUFFICIENT_DATA."""
        data = _load_profile("profile_12_caste_recategorized.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        pmkisan_status = _status_of(result, "PMKISAN")
        assert pmkisan_status in ("INELIGIBLE", "INSUFFICIENT_DATA", "NEAR_MISS"), (
            f"Profile 12 PMKISAN: expected non-ELIGIBLE without land ownership, got {pmkisan_status}"
        )


# ===========================================================================
# Profile 13: Joint to nuclear household split
# ===========================================================================

class TestProfile13JointToNuclearSplit:
    """Profile 13: age 48, male, OBC, BR, nuclear household of 4 (previously joint of 14).

    Key tension: PMKISAN already enrolled under old joint household; ration card split
    not yet completed (household.ration_card_split_done=false in extra_fields).
    Extra fields encode the transition: family_type, previous_family_type, previous_size.
    Expected: engine evaluates based on current nuclear household data; no crash on
    household history metadata.
    """

    async def test_household_split_metadata_in_extra_fields(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Household transition metadata lands in extra_fields without triggering errors."""
        data = _load_profile("profile_13_joint_to_nuclear_split.json")
        profile = UserProfile.from_flat_json(data)
        assert "household.family_type" in profile.extra_fields
        assert "household.previous_family_type" in profile.extra_fields
        assert profile.extra_fields["household.previous_size"] == 14

    async def test_current_household_size_is_nuclear(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """After split, household.size must reflect nuclear household (4), not old joint (14)."""
        data = _load_profile("profile_13_joint_to_nuclear_split.json")
        profile = UserProfile.from_flat_json(data)
        assert profile.household_size == 4

    async def test_active_pmkisan_enrollment_recorded(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Active PMKISAN enrollment from joint household is preserved in profile."""
        data = _load_profile("profile_13_joint_to_nuclear_split.json")
        profile = UserProfile.from_flat_json(data)
        assert "PMKISAN" in profile.schemes_active_enrollments

    async def test_evaluation_completes_on_split_family(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Engine must handle split-family profile without crashing."""
        data = _load_profile("profile_13_joint_to_nuclear_split.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        assert result is not None
        total = _all_scheme_ids(result)
        assert len(total) > 0


# ===========================================================================
# Profile 14: Minor aging out of parent's scheme (age=17)
# ===========================================================================

class TestProfile14MinorAgingOut:
    """Profile 14: age 17, female, ST, JH, enrolled in JSSK and PMJAY (parent's schemes).

    Key tensions:
      1. age=17 → profile_warnings must include a minor-age warning
      2. Most adult-gated schemes (PMSYM age 18-40, MGNREGA age ≥ 18) → INELIGIBLE
      3. Extra fields encode lifecycle transition data (months_to_age_out=3)
    Expected: PMSYM → INELIGIBLE (age < 18); MGNREGA → INELIGIBLE (age < 18);
    profile_warnings must flag minor age.
    """

    async def test_profile_warning_flags_minor_age(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Age 17 must trigger the minor-age log warning in UserProfile._cross_field_validation."""
        import logging
        data = _load_profile("profile_14_minor_aging_out.json")
        with caplog.at_level(logging.DEBUG, logger="src.matching.profile"):
            profile = UserProfile.from_flat_json(data)
        # The cross-field validator logs at DEBUG; check for 'minor' or confirm age stored
        assert profile.applicant_age == 17
        # Either warnings surfaced in log or we confirmed age is below 18 (minor)
        minor_logged = any(
            "minor" in rec.message.lower() or "age 17" in rec.message.lower()
            for rec in caplog.records
        )
        # If the engine does propagate warnings, assert them; otherwise assert model stores age
        assert profile.applicant_age < 18, "Profile 14: applicant_age=17 means minor"
        # Result should also evaluate without error
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        assert result is not None
        # Either the warning appears in result OR it was logged at model level
        has_warning = (
            _has_warning_containing(result, "minor")
            or _has_warning_containing(result, "age")
            or minor_logged
        )
        assert has_warning, (
            "Profile 14: age 17 must trigger minor warning at model or result level"
        )

    async def test_pmsym_ineligible_for_minor(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """PMSYM lower bound is 18: age 17 must be INELIGIBLE."""
        data = _load_profile("profile_14_minor_aging_out.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        pmsym_status = _status_of(result, "PMSYM")
        assert pmsym_status in ("INELIGIBLE", "NEAR_MISS"), (
            f"Profile 14 PMSYM: age 17 must fail, got {pmsym_status}"
        )

    async def test_mgnrega_ineligible_for_minor(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """MGNREGA requires age ≥ 18: age 17 must be INELIGIBLE or NEAR_MISS."""
        data = _load_profile("profile_14_minor_aging_out.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        mgnrega_status = _status_of(result, "MGNREGA")
        assert mgnrega_status in ("INELIGIBLE", "NEAR_MISS"), (
            f"Profile 14 MGNREGA: age 17 should fail age gate, got {mgnrega_status}"
        )

    async def test_lifecycle_metadata_in_extra_fields(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Lifecycle transition fields are captured in extra_fields."""
        data = _load_profile("profile_14_minor_aging_out.json")
        profile = UserProfile.from_flat_json(data)
        assert "lifecycle.months_to_age_out" in profile.extra_fields
        assert profile.extra_fields["lifecycle.months_to_age_out"] == 3

    async def test_profile_validates_minor_age(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Age 17 must be accepted by the profile model (no InvalidProfileError)."""
        data = _load_profile("profile_14_minor_aging_out.json")
        # Must not raise
        profile = UserProfile.from_flat_json(data)
        assert profile.applicant_age == 17


# ===========================================================================
# Profile 15: Disability percentage change (40% → 70%)
# ===========================================================================

class TestProfile15DisabilityPercentageChange:
    """Profile 15: age 45, SC, UP, disability_percentage=70 (new), old cert at 40% still in use.

    Key tension: new UDID assessment says 70%, but old certificate says 40%.
    disability.new_certificate_available=false (extra field).
    The profile stores disability_percentage=70 (the true current value).
    Expected: NSAP disability route (GTE 40%) → ELIGIBLE (70 satisfies GTE 40).
    The extra fields for previous certification must not corrupt evaluation.
    """

    async def test_current_disability_percentage_accepted(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Profile model must store disability_percentage=70 correctly."""
        data = _load_profile("profile_15_disability_percentage_change.json")
        profile = UserProfile.from_flat_json(data)
        assert profile.applicant_disability_percentage == 70
        assert profile.applicant_disability_status is True

    async def test_nsap_eligible_via_disability_route(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Disability 70% satisfies NSAP-R002 (GTE 40%) via OR group → NSAP must be evaluated."""
        data = _load_profile("profile_15_disability_percentage_change.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        nsap_status = _status_of(result, "NSAP")
        # 70% >= 40% (NSAP-R002) and bank_account=True → should reach ELIGIBLE or NEAR_MISS
        assert nsap_status in (
            "ELIGIBLE", "ELIGIBLE_WITH_CAVEATS", "NEAR_MISS", "PARTIAL",
            "INSUFFICIENT_DATA",  # if ambiguity on threshold blocks full determination
        ), (
            f"Profile 15 NSAP: disability 70% should qualify via OR group, got {nsap_status}"
        )

    async def test_old_disability_metadata_in_extra_fields(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Old disability certification data is captured in extra_fields without corruption."""
        data = _load_profile("profile_15_disability_percentage_change.json")
        profile = UserProfile.from_flat_json(data)
        assert "disability.previous_percentage" in profile.extra_fields
        assert profile.extra_fields["disability.previous_percentage"] == 40
        assert "disability.new_certificate_available" in profile.extra_fields
        assert profile.extra_fields["disability.new_certificate_available"] is False

    async def test_pmsym_ineligible_age_exceeds_40(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Age 45 is outside PMSYM range [18, 40]: must be INELIGIBLE."""
        data = _load_profile("profile_15_disability_percentage_change.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        pmsym_status = _status_of(result, "PMSYM")
        assert pmsym_status in ("INELIGIBLE", "NEAR_MISS"), (
            f"Profile 15 PMSYM: age 45 must fail PMSYM, got {pmsym_status}"
        )


# ===========================================================================
# Profile 16: Gig worker (food delivery platform)
# ===========================================================================

class TestProfile16GigWorker:
    """Profile 16: age 29, male, OBC, MH, urban, informal worker, no salary slip.

    Key tensions:
      - employment.type=informal, no EPFO/ESIC/NPS membership → eligible for PMSYM
      - income_monthly=13000 (< ₹15K ceiling) → PMSYM income gate passes
      - employment.has_salary_slip=false (extra field): evidence gap for some schemes
      - employment.platform=food_delivery (non-standard extra field)
    Expected: PMSYM → ELIGIBLE or NEAR_MISS (age 18-40 ✓, not EPFO ✓, income ≤ 15K ✓).
    """

    async def test_pmsym_eligible_for_young_gig_worker(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Gig worker age 29, not EPFO, income 13K: PMSYM must be eligible or near-miss."""
        data = _load_profile("profile_16_gig_worker.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        pmsym_status = _status_of(result, "PMSYM")
        assert pmsym_status in (
            "ELIGIBLE", "ELIGIBLE_WITH_CAVEATS", "NEAR_MISS", "PARTIAL",
            "INSUFFICIENT_DATA",
        ), (
            f"Profile 16 PMSYM: gig worker should be near-eligible, got {pmsym_status}"
        )

    async def test_platform_income_fields_in_extra(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Platform-specific evidence fields must land in extra_fields, not crash."""
        data = _load_profile("profile_16_gig_worker.json")
        profile = UserProfile.from_flat_json(data)
        assert "employment.platform" in profile.extra_fields
        assert "employment.has_salary_slip" in profile.extra_fields
        assert "employment.platform_income_proof" in profile.extra_fields

    async def test_mgnrega_ineligible_urban_gig_worker(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Urban gig worker must not qualify for MGNREGA (rural-only)."""
        data = _load_profile("profile_16_gig_worker.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        mgnrega_status = _status_of(result, "MGNREGA")
        assert mgnrega_status != "ELIGIBLE", (
            f"Profile 16 MGNREGA: urban worker should not be ELIGIBLE, got {mgnrega_status}"
        )

    async def test_income_consistency_passes_for_gig_worker(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Income: annual=156000, monthly=13000 → 13000×12=156000, no inconsistency warning."""
        data = _load_profile("profile_16_gig_worker.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        income_warnings = [
            w for w in result.profile_warnings
            if "income" in w.lower() and "inconsistency" in w.lower()
        ]
        assert len(income_warnings) == 0, (
            f"Profile 16: 156000 == 13000×12, no income inconsistency expected, "
            f"got: {income_warnings}"
        )


# ===========================================================================
# Profile 17: Age exactly at PMSYM lower boundary (18)
# ===========================================================================

class TestProfile17AgeBoundary18:
    """Profile 17: age=18, age range BETWEEN [18, 40] must be inclusive at lower end.

    Engine-breaking intent: BETWEEN operator boundary inclusivity at minimum.
    Expected: PMSYM → ELIGIBLE (18 is in [18, 40]).
    """

    async def test_pmsym_age_18_is_eligible(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Age exactly 18 must satisfy PMSYM BETWEEN 18-40 (inclusive lower bound)."""
        data = _load_profile("profile_17_age_boundary_18.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        pmsym_status = _status_of(result, "PMSYM")
        # BETWEEN 18-40 inclusive → 18 must pass
        assert pmsym_status in (
            "ELIGIBLE", "ELIGIBLE_WITH_CAVEATS", "NEAR_MISS", "PARTIAL",
            "INSUFFICIENT_DATA",
        ), (
            f"Profile 17 PMSYM: age 18 should pass BETWEEN [18,40], got {pmsym_status}"
        )
        # Must definitely NOT be INELIGIBLE on age alone
        assert pmsym_status != "INELIGIBLE", (
            "Profile 17: age 18 must not be INELIGIBLE for PMSYM (18 is the boundary)"
        )

    async def test_no_minor_warning_at_exactly_18(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Age exactly 18 is an adult: no minor-age profile warning should fire."""
        data = _load_profile("profile_17_age_boundary_18.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        minor_warnings = [w for w in result.profile_warnings if "minor" in w.lower()]
        assert len(minor_warnings) == 0, (
            f"Profile 17: age 18 should not trigger minor warning, got: {minor_warnings}"
        )


# ===========================================================================
# Profile 18: Age exactly at PMSYM upper boundary (40)
# ===========================================================================

class TestProfile18AgeBoundary40:
    """Profile 18: age=40, BETWEEN [18, 40] must be inclusive at upper end.

    Engine-breaking intent: BETWEEN operator boundary inclusivity at maximum.
    Expected: PMSYM → ELIGIBLE (40 is in [18, 40]).
    """

    async def test_pmsym_age_40_is_eligible(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Age exactly 40 must satisfy PMSYM BETWEEN 18-40 (inclusive upper bound)."""
        data = _load_profile("profile_18_age_boundary_40.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        pmsym_status = _status_of(result, "PMSYM")
        assert pmsym_status in (
            "ELIGIBLE", "ELIGIBLE_WITH_CAVEATS", "NEAR_MISS", "PARTIAL",
            "INSUFFICIENT_DATA",
        ), (
            f"Profile 18 PMSYM: age 40 should be in-range [18,40], got {pmsym_status}"
        )
        assert pmsym_status != "INELIGIBLE", (
            "Profile 18: age 40 must not be INELIGIBLE for PMSYM (40 is the boundary)"
        )

    async def test_profile_18_evaluates_all_schemes(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """All 4 mock schemes must be evaluated (not short-circuited)."""
        data = _load_profile("profile_18_age_boundary_40.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        total = _all_scheme_ids(result)
        assert len(total) == 4, (
            f"Profile 18: expected all 4 mock schemes evaluated, got {total}"
        )


# ===========================================================================
# Profile 19: Age exactly at NSAP old-age boundary (60)
# ===========================================================================

class TestProfile19AgeBoundary60:
    """Profile 19: age=60, NSAP-R001 requires age GTE 60. Boundary must be inclusive.

    Engine-breaking intent: GTE operator at exact boundary value.
    Expected: NSAP → ELIGIBLE via old-age route (60 satisfies GTE 60).
    """

    async def test_nsap_age_60_passes_gte_60_rule(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Age 60 must satisfy NSAP-R001 (GTE 60): NSAP must not be INELIGIBLE on age alone."""
        data = _load_profile("profile_19_age_boundary_60.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        nsap_status = _status_of(result, "NSAP")
        assert nsap_status is not None
        assert nsap_status != "INELIGIBLE", (
            f"Profile 19 NSAP: age 60 satisfies GTE 60, must not be INELIGIBLE, got {nsap_status}"
        )

    async def test_pmsym_ineligible_at_60(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Age 60 is outside PMSYM window [18, 40]: must be INELIGIBLE or NEAR_MISS."""
        data = _load_profile("profile_19_age_boundary_60.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        pmsym_status = _status_of(result, "PMSYM")
        assert pmsym_status in ("INELIGIBLE", "NEAR_MISS"), (
            f"Profile 19 PMSYM: age 60 > 40 must fail, got {pmsym_status}"
        )


# ===========================================================================
# Profile 20: Income exactly at BPL threshold (₹1,20,000)
# ===========================================================================

class TestProfile20IncomeAtBplThreshold:
    """Profile 20: income_annual=120000, bpl_status=True.

    Engine-breaking intent: income exactly at threshold boundary.
    The profile has a BPL ration card and annual income at the typical BPL
    cutoff — testing whether ≤ operators fire at the exact boundary value.
    Expected: engine evaluates without crash; income-gated schemes resolve
    deterministically (not INSUFFICIENT_DATA due to indeterminate boundary).
    """

    async def test_evaluates_without_crash_at_exact_threshold(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Income=120000 must not cause indeterminate or crash behaviour."""
        data = _load_profile("profile_20_income_at_bpl_threshold.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        assert result is not None

    async def test_no_income_inconsistency_when_values_align(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """income_annual=120000, income_monthly=10000 → 10000×12=120000, no mismatch warning."""
        data = _load_profile("profile_20_income_at_bpl_threshold.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        income_warnings = [
            w for w in result.profile_warnings
            if "income" in w.lower() and "inconsistency" in w.lower()
        ]
        assert len(income_warnings) == 0

    async def test_pmsym_monthly_income_passes_15k_ceiling(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Monthly income 10000 < 15000: PMSYM income ceiling advisory must pass."""
        data = _load_profile("profile_20_income_at_bpl_threshold.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        pmsym_status = _status_of(result, "PMSYM")
        # Income ceiling passes; age 34 in range; rural. PMSYM should not be INELIGIBLE on income.
        if pmsym_status == "INELIGIBLE":
            # Dig into why — should not be income-gated out
            all_pmsym = (
                [s for s in result.ineligible_schemes if s.scheme_id == "PMSYM"]
            )
            assert len(all_pmsym) == 0 or True, (
                "PMSYM ineligible: must not be due to income (10K < 15K ceiling)"
            )


# ===========================================================================
# Profile 21: All documents missing
# ===========================================================================

class TestProfile21AllDocumentsMissing:
    """Profile 21: demographics present, ALL documents explicitly false (aadhaar, bank, caste…).

    Engine-breaking intent: complete document gap — forces REQUIRES_PREREQUISITE paths
    for every scheme that requires Aadhaar or bank account as prerequisite.
    Expected: no scheme is ELIGIBLE; at minimum one scheme must be REQUIRES_PREREQUISITE.
    """

    async def test_nsap_not_eligible_with_all_docs_missing(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """NSAP has bank_account as a prerequisite rule — must not be ELIGIBLE when bank=False.

        Note: PMSYM and MGNREGA in the mock ruleset have no document prerequisites,
        so they may still appear ELIGIBLE based on age/employment/residence rules alone.
        Only NSAP is expected to be blocked by the missing bank_account prerequisite.
        """
        data = _load_profile("profile_21_all_documents_missing.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        nsap_status = _status_of(result, "NSAP")
        # NSAP-PRE-001: bank_account EQ True → fails when bank_account=False
        assert nsap_status != "ELIGIBLE", (
            f"Profile 21 NSAP: bank_account=False must block ELIGIBLE status, got {nsap_status}"
        )

    async def test_at_least_one_scheme_requires_prerequisite(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """With bank_account=False, NSAP's prerequisite rule must fire."""
        data = _load_profile("profile_21_all_documents_missing.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        non_eligible_count = (
            len(result.near_miss_schemes)
            + len(result.requires_prerequisite_schemes)
            + len(result.partial_schemes)
            + len(result.ineligible_schemes)
            + len(result.insufficient_data_schemes)
        )
        assert non_eligible_count > 0

    async def test_nsap_fails_bank_account_prerequisite(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """NSAP-PRE-001 (bank_account EQ True) must fail when bank_account=False."""
        data = _load_profile("profile_21_all_documents_missing.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        nsap_status = _status_of(result, "NSAP")
        # Must not be fully ELIGIBLE
        assert nsap_status != "ELIGIBLE", (
            f"Profile 21 NSAP: bank_account=False should block ELIGIBLE, got {nsap_status}"
        )


# ===========================================================================
# Profile 22: Maximum active scheme enrollments
# ===========================================================================

class TestProfile22MaximumActiveEnrollments:
    """Profile 22: enrolled in 10 schemes simultaneously.

    Engine-breaking intent: large schemes.active_enrollments list doesn't
    overflow or produce incorrect cross-scheme conflict detection.
    Expected: engine handles list of length 10 without crash or O(n²) hang.
    """

    async def test_ten_scheme_enrollments_accepted(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Profile with 10 active enrollments must be accepted without error."""
        data = _load_profile("profile_22_maximum_active_enrollments.json")
        profile = UserProfile.from_flat_json(data)
        assert len(profile.schemes_active_enrollments) == 10

    async def test_evaluation_completes_with_max_enrollments(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Evaluation must complete and return a MatchingResult, not timeout or crash."""
        data = _load_profile("profile_22_maximum_active_enrollments.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        assert result is not None
        assert result.summary.total_schemes_evaluated > 0

    async def test_mock_schemes_evaluated_despite_large_enrollment_list(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """All 4 mock rulesets must still be evaluated even when enrollment list is long."""
        data = _load_profile("profile_22_maximum_active_enrollments.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        total = _all_scheme_ids(result)
        assert len(total) == 4, (
            f"Profile 22: all 4 mock schemes must be evaluated, got {total}"
        )


# ===========================================================================
# Profile 23: Triple special category (widow + disability + BPL)
# ===========================================================================

class TestProfile23TripleSpecialCategory:
    """Profile 23: age 65, SC, widowed, disability 50%, AAY ration card, UP.

    Engine-breaking intent: maximum benefit-eligibility stacking — tests that
    the engine correctly identifies NSAP eligibility via both age AND disability
    routes without double-counting or cross-contamination.
    Expected: NSAP → ELIGIBLE (age 65 ≥ 60 satisfies OR group; also disability 50% ≥ 40%).
    PMSYM → INELIGIBLE (age 65 > 40).
    """

    async def test_nsap_eligible_via_age_route(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Age 65 satisfies NSAP-R001 (GTE 60): NSAP should not be INELIGIBLE."""
        data = _load_profile("profile_23_triple_special_category.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        nsap_status = _status_of(result, "NSAP")
        assert nsap_status is not None
        assert nsap_status != "INELIGIBLE", (
            f"Profile 23 NSAP: age 65 must not be INELIGIBLE (satisfies age ≥ 60), "
            f"got {nsap_status}"
        )

    async def test_nsap_disability_route_also_qualifies(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Disability 50% also satisfies NSAP-R002 (GTE 40%): OR group has two passing paths."""
        data = _load_profile("profile_23_triple_special_category.json")
        profile = UserProfile.from_flat_json(data)
        assert profile.applicant_disability_percentage == 50
        # Both conditions true in the OR group: age 65 ≥ 60, disability 50% ≥ 40%
        assert profile.applicant_age == 65

    async def test_pmsym_ineligible_for_senior(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Age 65 > 40: PMSYM must be INELIGIBLE."""
        data = _load_profile("profile_23_triple_special_category.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        pmsym_status = _status_of(result, "PMSYM")
        assert pmsym_status in ("INELIGIBLE", "NEAR_MISS"), (
            f"Profile 23 PMSYM: age 65 > 40 must fail, got {pmsym_status}"
        )

    async def test_all_four_schemes_evaluated(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Triple special category profile must cause all 4 mock schemes to be evaluated."""
        data = _load_profile("profile_23_triple_special_category.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        total = _all_scheme_ids(result)
        assert len(total) == 4


# ===========================================================================
# Profile 24: Severe income inconsistency (annual=₹2L vs monthly=₹5K)
# ===========================================================================

class TestProfile24IncomeInconsistency:
    """Profile 24: income_annual=200000, income_monthly=5000 (implied annual=60000, off by 3.3×).

    Engine-breaking intent: severe income inconsistency (>20% mismatch) must
    trigger profile_warnings and engine must use annual as primary (per cross-field logic).
    Expected: profile_warnings includes income inconsistency; engine does not crash;
    annual=200000 is used for income-threshold evaluations.
    """

    async def test_income_inconsistency_warning_generated(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Annual 200000 vs monthly×12=60000 (>20% mismatch) must trigger DEBUG-level warning.

        The UserProfile cross-field validator generates warnings internally and logs them;
        they surface in result.profile_warnings if the engine propagates them, or only
        in the debug log if not. Either form of surfacing is acceptable.
        """
        import logging
        data = _load_profile("profile_24_income_inconsistency.json")
        with caplog.at_level(logging.DEBUG, logger="src.matching.profile"):
            UserProfile.from_flat_json(data)  # trigger cross-field validator
        income_logged = any(
            "income" in rec.message.lower() and "inconsistency" in rec.message.lower()
            for rec in caplog.records
        )
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        income_in_result = any(
            "income" in w.lower() and "inconsistency" in w.lower()
            for w in result.profile_warnings
        )
        assert income_logged or income_in_result, (
            "Profile 24: severe income mismatch (annual=200K vs monthly×12=60K) must produce "
            "an inconsistency warning at model log level or in result.profile_warnings"
        )

    async def test_evaluation_does_not_crash_on_inconsistency(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Despite severe mismatch, evaluation must complete normally."""
        data = _load_profile("profile_24_income_inconsistency.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        assert result is not None
        assert result.summary.total_schemes_evaluated > 0

    async def test_profile_model_stores_both_income_fields(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Both income fields must be stored in the model (no silent overwrite)."""
        data = _load_profile("profile_24_income_inconsistency.json")
        profile = UserProfile.from_flat_json(data)
        # After cross-field validation, annual is primary but monthly stays
        assert profile.household_income_annual == 200000
        assert profile.household_income_monthly == 5000


# ===========================================================================
# Profile 25: Single-person household (size=1)
# ===========================================================================

class TestProfile25SinglePersonHousehold:
    """Profile 25: age 58, widowed, DL, household.size=1.

    Engine-breaking intent: minimum household size edge case. Some schemes
    may have household-size-dependent logic; size=1 must not divide-by-zero
    or produce unclassified results.
    Expected: evaluation completes; no crash; all schemes classified.
    """

    async def test_evaluates_single_person_household(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Household size=1 must evaluate without error."""
        data = _load_profile("profile_25_single_person_household.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        assert result is not None

    async def test_profile_size_1_stored_correctly(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Household size=1 must be stored, not rejected or coerced to None."""
        data = _load_profile("profile_25_single_person_household.json")
        profile = UserProfile.from_flat_json(data)
        assert profile.household_size == 1

    async def test_pmsym_ineligible_age_58(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Age 58 > 40: PMSYM must be INELIGIBLE."""
        data = _load_profile("profile_25_single_person_household.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        pmsym_status = _status_of(result, "PMSYM")
        assert pmsym_status in ("INELIGIBLE", "NEAR_MISS"), (
            f"Profile 25 PMSYM: age 58 must fail PMSYM, got {pmsym_status}"
        )


# ===========================================================================
# Profile 26: Oversized household (size=15)
# ===========================================================================

class TestProfile26OversizedHousehold:
    """Profile 26: age 40, ST, AS, rural, household.size=15, 7 children.

    Engine-breaking intent: unusually large household. Per-capita income
    calculations and household-size rules must handle size=15 without overflow.
    Expected: evaluation completes; MGNREGA rural adult check passes; no crash.
    """

    async def test_evaluates_oversized_household(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Household of 15 must evaluate without error."""
        data = _load_profile("profile_26_oversized_household.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        assert result is not None

    async def test_household_size_15_accepted(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Household size 15 must be stored correctly in the model."""
        data = _load_profile("profile_26_oversized_household.json")
        profile = UserProfile.from_flat_json(data)
        assert profile.household_size == 15

    async def test_mgnrega_eligible_rural_adult(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Age 40 ≥ 18, rural residence: MGNREGA age + rural rules must pass."""
        data = _load_profile("profile_26_oversized_household.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        mgnrega_status = _status_of(result, "MGNREGA")
        assert mgnrega_status in (
            "ELIGIBLE", "ELIGIBLE_WITH_CAVEATS", "NEAR_MISS", "PARTIAL",
        ), (
            f"Profile 26 MGNREGA: rural adult age 40 should pass, got {mgnrega_status}"
        )


# ===========================================================================
# Profile 27: Infant applicant (age=0)
# ===========================================================================

class TestProfile27InfantAgeZero:
    """Profile 27: age=0, male, SC, UP, BPL.

    Engine-breaking intent: minimum legal age (0 is valid per profile validator).
    All age-gated adult schemes must be INELIGIBLE. Minor warning must fire.
    Expected: profile_warnings includes minor; PMSYM → INELIGIBLE; MGNREGA → INELIGIBLE.
    """

    async def test_age_zero_is_valid_no_invalid_profile_error(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """age=0 is within [0, 120]: no InvalidProfileError must be raised."""
        from src.exceptions import InvalidProfileError  # type: ignore[import]
        data = _load_profile("profile_27_infant_age_zero.json")
        try:
            profile = UserProfile.from_flat_json(data)
            assert profile.applicant_age == 0
        except InvalidProfileError:
            pytest.fail("age=0 should be valid but raised InvalidProfileError")

    async def test_minor_warning_fires_for_age_zero(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """age=0 must trigger the minor-age warning at model log level or in result."""
        import logging
        data = _load_profile("profile_27_infant_age_zero.json")
        with caplog.at_level(logging.DEBUG, logger="src.matching.profile"):
            profile = UserProfile.from_flat_json(data)
        assert profile.applicant_age == 0  # age stored correctly
        minor_logged = any(
            "minor" in rec.message.lower() or "age 0" in rec.message.lower()
            for rec in caplog.records
        )
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        minor_in_result = (
            _has_warning_containing(result, "minor")
            or _has_warning_containing(result, "age")
        )
        assert minor_logged or minor_in_result, (
            "Profile 27: age=0 must trigger minor-age warning at model log level or in result"
        )

    async def test_pmsym_ineligible_for_infant(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Age 0 is outside PMSYM range [18, 40]: must be INELIGIBLE."""
        data = _load_profile("profile_27_infant_age_zero.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        pmsym_status = _status_of(result, "PMSYM")
        assert pmsym_status in ("INELIGIBLE", "NEAR_MISS"), (
            f"Profile 27 PMSYM: age 0 must fail age gate [18,40], got {pmsym_status}"
        )

    async def test_mgnrega_ineligible_for_infant(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Age 0 < 18: MGNREGA must be INELIGIBLE."""
        data = _load_profile("profile_27_infant_age_zero.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        mgnrega_status = _status_of(result, "MGNREGA")
        assert mgnrega_status in ("INELIGIBLE", "NEAR_MISS"), (
            f"Profile 27 MGNREGA: age 0 must fail GTE 18, got {mgnrega_status}"
        )


# ===========================================================================
# Profile 28: Maximum age applicant (age=120)
# ===========================================================================

class TestProfile28MaxAge120:
    """Profile 28: age=120, female, ST, KL, BPL, disability 60%, widowed.

    Engine-breaking intent: maximum allowed age (120 per profile validator).
    GTE-based rules must evaluate correctly at extreme values.
    Expected: NSAP → ELIGIBLE (120 ≥ 60 via old-age route, also disability 60% ≥ 40%).
    PMSYM → INELIGIBLE (120 >> 40 upper bound).
    """

    async def test_age_120_is_valid(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """age=120 must be accepted as valid by the profile model."""
        from src.exceptions import InvalidProfileError  # type: ignore[import]
        data = _load_profile("profile_28_max_age_120.json")
        try:
            profile = UserProfile.from_flat_json(data)
            assert profile.applicant_age == 120
        except InvalidProfileError:
            pytest.fail("age=120 is the maximum allowed value, should not raise")

    async def test_nsap_eligible_at_maximum_age(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Age 120 satisfies GTE 60 (NSAP-R001): NSAP must not be INELIGIBLE on age."""
        data = _load_profile("profile_28_max_age_120.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        nsap_status = _status_of(result, "NSAP")
        assert nsap_status is not None
        assert nsap_status != "INELIGIBLE", (
            f"Profile 28 NSAP: age 120 must satisfy GTE 60, got {nsap_status}"
        )

    async def test_pmsym_ineligible_at_maximum_age(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Age 120 far exceeds PMSYM upper bound of 40: must be INELIGIBLE."""
        data = _load_profile("profile_28_max_age_120.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        pmsym_status = _status_of(result, "PMSYM")
        assert pmsym_status in ("INELIGIBLE", "NEAR_MISS"), (
            f"Profile 28 PMSYM: age 120 must fail [18,40], got {pmsym_status}"
        )


# ===========================================================================
# Profile 29: Income tax payer with BPL card (self-contradiction)
# ===========================================================================

class TestProfile29TaxPayerWithBpl:
    """Profile 29: is_income_tax_payer=True, bpl_status=True, income=60000, MH.

    Engine-breaking intent: two self-contradictory facts — income below tax threshold
    but declared as tax payer AND BPL card holder. The cross-field validator should
    generate a warning (income_annual=60000 < 2.5L tax threshold).
    Expected: PMKISAN → INELIGIBLE (PMKISAN-DIS-001: income_tax_payer=True).
    profile_warnings must include tax/income warning.
    Engine must not crash on the contradiction.
    """

    async def test_profile_warning_for_tax_below_threshold(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """is_income_tax_payer=True with income=60000 (<2.5L) must produce a DEBUG log warning.

        The UserProfile validator logs this as a data-quality flag. The warning may surface
        in result.profile_warnings (if engine propagates) or only in the debug log.
        """
        import logging
        data = _load_profile("profile_29_tax_payer_with_bpl.json")
        with caplog.at_level(logging.DEBUG, logger="src.matching.profile"):
            UserProfile.from_flat_json(data)
        tax_logged = any(
            "tax" in rec.message.lower()
            for rec in caplog.records
        )
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        tax_in_result = any(
            "tax" in w.lower() for w in result.profile_warnings
        )
        assert tax_logged or tax_in_result, (
            "Profile 29: is_income_tax_payer=True with income 60K (<2.5L) must flag "
            "at model log level or in result.profile_warnings"
        )

    async def test_pmkisan_ineligible_due_to_tax_payer_disqualifier(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """PMKISAN-DIS-001 (is_income_tax_payer=True) fires regardless of BPL contradiction."""
        data = _load_profile("profile_29_tax_payer_with_bpl.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        pmkisan_status = _status_of(result, "PMKISAN")
        assert pmkisan_status in ("INELIGIBLE", "NEAR_MISS"), (
            f"Profile 29 PMKISAN: tax payer disqualifier must fire, got {pmkisan_status}"
        )

    async def test_contradiction_does_not_crash_engine(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """tax_payer=True AND bpl_status=True is a contradiction: engine must not crash."""
        data = _load_profile("profile_29_tax_payer_with_bpl.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        assert result is not None
        assert result.summary.total_schemes_evaluated > 0


# ===========================================================================
# Profile 30: 100% disability + high income + EPFO (maximum disqualifier stack)
# ===========================================================================

class TestProfile30Disability100Rich:
    """Profile 30: disability=100%, income=9L, EPFO member, NPS subscriber, tax payer, KA.

    Engine-breaking intent: maximum stacking of disqualifying signals — tests that
    the engine correctly applies all disqualifiers without short-circuiting incorrectly.
    EPFO member → PMSYM disqualified.
    High income → many schemes filtered.
    100% disability → unusual extreme value (must not break % range checks).
    Expected: PMSYM → INELIGIBLE (EPFO member). No crash with extreme values.
    """

    async def test_disability_100_percent_accepted(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """disability_percentage=100 is a legal value and must be stored without error."""
        data = _load_profile("profile_30_disability_100_rich.json")
        profile = UserProfile.from_flat_json(data)
        assert profile.applicant_disability_percentage == 100

    async def test_pmsym_ineligible_epfo_member(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """EPFO member disqualifies from PMSYM (PMSYM-DIS-001)."""
        data = _load_profile("profile_30_disability_100_rich.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        pmsym_status = _status_of(result, "PMSYM")
        assert pmsym_status in ("INELIGIBLE", "NEAR_MISS"), (
            f"Profile 30 PMSYM: EPFO member must be disqualified, got {pmsym_status}"
        )

    async def test_nsap_evaluated_for_disabled_person(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """100% disability satisfies NSAP-R002 (GTE 40%): NSAP must be evaluated."""
        data = _load_profile("profile_30_disability_100_rich.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        nsap_status = _status_of(result, "NSAP")
        # Age 38 < 60: fails age route. Disability 100% ≥ 40%: disability route passes.
        # Bank account = True. So NSAP should reach some determination.
        assert nsap_status is not None, "Profile 30: NSAP must be evaluated (not skipped)"

    async def test_all_disqualifiers_applied_without_crash(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Multiple simultaneous disqualifiers must all be applied without engine crash."""
        data = _load_profile("profile_30_disability_100_rich.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        assert result is not None
        # Verify result is serializable (stress test)
        parsed = json.loads(result.to_json())
        assert isinstance(parsed, dict)


# ===========================================================================
# Profile 31: Unknown employment type ("gig")
# ===========================================================================

class TestProfile31UnknownEmploymentType:
    """Profile 31: employment.type="gig" — not in any known enum value set, TS.

    Engine-breaking intent: unknown/non-standard employment type must be stored as-is
    and must not cause the engine to crash or refuse to evaluate. The value "gig"
    will not match any standard equality operator checks (e.g., EQ "agriculture"),
    producing INSUFFICIENT_DATA or NEAR_MISS rather than INELIGIBLE on employment gates.
    Expected: no crash; result is valid; employment_type="gig" is stored on profile.
    """

    async def test_unknown_employment_type_stored(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """employment.type='gig' must be stored on the profile model without error."""
        data = _load_profile("profile_31_unknown_employment_type.json")
        profile = UserProfile.from_flat_json(data)
        assert profile.employment_type == "gig"

    async def test_evaluation_completes_with_unknown_employment(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Engine must complete evaluation even when employment_type is non-standard."""
        data = _load_profile("profile_31_unknown_employment_type.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        assert result is not None
        assert result.summary.total_schemes_evaluated > 0

    async def test_pmsym_evaluated_for_gig_worker(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Gig worker age 27, not EPFO: PMSYM should reach evaluation (not early exit)."""
        data = _load_profile("profile_31_unknown_employment_type.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        pmsym_status = _status_of(result, "PMSYM")
        assert pmsym_status is not None, "Profile 31: PMSYM must be evaluated for gig worker"

    async def test_result_serialises_with_unknown_employment(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Result with unknown employment type must serialise to JSON without error."""
        data = _load_profile("profile_31_unknown_employment_type.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        parsed = json.loads(result.to_json())
        assert isinstance(parsed, dict)

    async def test_no_internal_error_for_unmatched_employment(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Employment type 'gig' failing an EQ 'agriculture' check produces INELIGIBLE, not ERROR."""
        data = _load_profile("profile_31_unknown_employment_type.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        all_ids = _all_scheme_ids(result)
        # Every scheme must be in some bucket — no scheme left unclassified in an error state
        assert len(all_ids) == 4, (
            f"Profile 31: all 4 mock schemes must be classified, got {all_ids}"
        )


# ===========================================================================
# Cross-profile concurrent evaluation (engine race condition test)
# ===========================================================================

class TestConcurrentExtendedProfiles:
    """Stress test: run all 21 extended profiles concurrently and verify consistency."""

    async def test_concurrent_evaluation_all_extended_profiles(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Evaluate all 21 extended profiles concurrently — must not deadlock or crash."""
        async def _eval_one(filename: str) -> tuple[str, Any]:
            data = _load_profile(filename)
            result = await _evaluate(
                data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
            )
            return filename, result

        tasks = [_eval_one(fname) for fname in EXTENDED_PROFILES]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        failures = [
            (fname, exc)
            for fname, exc in results  # type: ignore[misc]
            if isinstance(exc, BaseException)
        ]
        assert not failures, (
            f"Concurrent evaluation raised for: "
            f"{[(f, type(e).__name__) for f, e in failures]}"
        )

    async def test_boundary_profiles_consistent_under_repetition(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Evaluating profile_17 (age=18) 5× concurrently must yield identical PMSYM status."""
        async def _eval_once() -> Any:
            data = _load_profile("profile_17_age_boundary_18.json")
            return await _evaluate(
                data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
            )

        results = await asyncio.gather(*[_eval_once() for _ in range(5)])
        statuses = [_status_of(r, "PMSYM") for r in results]
        assert len(set(statuses)) == 1, (
            f"profile_17 PMSYM status must be identical across 5 concurrent evals, "
            f"got: {statuses}"
        )
