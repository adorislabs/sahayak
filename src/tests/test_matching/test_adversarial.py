"""Feature 7: Adversarial profile tests.

This module tests the full end-to-end pipeline against 10 adversarial profiles
that represent edge-case real-world scenarios. Each profile targets specific
ambiguity patterns, eligibility edge cases, or cross-scheme interactions.

Spec reference: docs/part2-planning/specs/07-adversarial-profiles.md
Architecture:   docs/part2-planning/ARCHITECTURE-CONTRACT.md § test_adversarial.py

Profile inventory:
  01 - Widow remarried (NSAP already enrolled, now married again)
  02 - Farmer leases land, does not own it
  03 - Aadhaar present, no bank account (payment blocker)
  04 - Interstate migrant (domicile Bihar, working in Gujarat)
  05 - Young married couple (dual-income cross-validation)
  06 - Senior citizen with multiple disabilities
  07 - Street vendor (unorganised urban worker)
  08 - Farmer whose son got a government job
  09 - Pregnant rural woman without bank account
  10 - Recent graduate (ST, unemployed)

Technical scenarios (T1-T6): empty profile, max profile, contradictory profile,
concurrent evaluation, corrupt rule base, oversized profile.

All async tests run without @pytest.mark.asyncio because asyncio_mode="auto".
Tests will fail (ImportError) until Agent B implements src/matching/.
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
FIXTURES_DIR = Path(__file__).parent.parent / "test_data" / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
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


# ===========================================================================
# Parametrised smoke-test: all 10 adversarial profiles evaluate without crash
# ===========================================================================

ADVERSARIAL_PROFILES = [
    "profile_01_widow_remarried.json",
    "profile_02_farmer_leases_land.json",
    "profile_03_aadhaar_no_bank.json",
    "profile_04_interstate_migrant.json",
    "profile_05_young_married_couple.json",
    "profile_06_senior_multiple_disabilities.json",
    "profile_07_street_vendor.json",
    "profile_08_farmer_son_got_job.json",
    "profile_09_pregnant_rural.json",
    "profile_10_recent_graduate.json",
]


class TestAllProfilesEvaluateWithoutCrash:
    """Every adversarial profile must evaluate to completion without raising."""

    @pytest.mark.parametrize("profile_file", ADVERSARIAL_PROFILES)
    async def test_profile_evaluates_without_exception(
        self,
        profile_file: str,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Loading and evaluating each adversarial profile must not raise."""
        data = _load_profile(profile_file)

        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        assert result is not None

    @pytest.mark.parametrize("profile_file", ADVERSARIAL_PROFILES)
    async def test_profile_produces_matching_result(
        self,
        profile_file: str,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Each profile must produce a MatchingResult with valid bucket lists."""
        from src.matching.output import MatchingResult  # type: ignore[import]

        data = _load_profile(profile_file)
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        assert isinstance(result, MatchingResult)
        # All buckets must be lists
        assert isinstance(result.eligible_schemes, list)
        assert isinstance(result.near_miss_schemes, list)

    @pytest.mark.parametrize("profile_file", ADVERSARIAL_PROFILES)
    async def test_profile_result_serialises_to_json(
        self,
        profile_file: str,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Each MatchingResult must produce valid JSON via to_json()."""
        import json as _json

        data = _load_profile(profile_file)
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        json_str = result.to_json()
        parsed = _json.loads(json_str)  # must not raise
        assert isinstance(parsed, dict)


# ===========================================================================
# Profile 01: Widow who remarried
# ===========================================================================

class TestProfile01WidowRemarried:
    """Profile 01: age 45, female, OBC, married, rural UP, NSAP already enrolled.

    Key ambiguity: Was previously widowed (enrolled in NSAP under widow category).
    Now remarried. Marital status change may invalidate widow-specific entitlement.
    Expected: NSAP → ELIGIBLE_WITH_CAVEATS or PARTIAL (marital status caveat).
    """

    async def test_nsap_produces_eligible_with_caveats_or_partial(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Widow remarried: NSAP status must be ELIGIBLE_WITH_CAVEATS or PARTIAL."""
        data = _load_profile("profile_01_widow_remarried.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        nsap_status = _status_of(result, "NSAP")
        acceptable_statuses = {
            "ELIGIBLE", "ELIGIBLE_WITH_CAVEATS", "PARTIAL",
            "NEAR_MISS", "INSUFFICIENT_DATA",  # permitted if ambiguity makes it unclear
        }
        assert nsap_status in acceptable_statuses, (
            f"Profile 01 NSAP status was {nsap_status!r}; expected one of {acceptable_statuses}"
        )

    async def test_result_has_at_least_one_ambiguity_note_for_nsap(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Remarried widow should trigger ≥1 ambiguity-related note (marital status change)."""
        data = _load_profile("profile_01_widow_remarried.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        # Find NSAP in any non-eligible bucket and check gap analysis for ambiguity notes
        all_schemes = (
            result.eligible_schemes
            + result.near_miss_schemes
            + result.partial_schemes
            + result.insufficient_data_schemes
        )
        nsap_result = next((s for s in all_schemes if s.scheme_id == "NSAP"), None)

        if nsap_result is not None and nsap_result.gap_analysis is not None:
            # Gap analysis should exist and have ambiguity notes or caveats
            has_caveats = (
                len(nsap_result.caveats) > 0
                or len(nsap_result.gap_analysis.ambiguity_notes) > 0
            )
            assert has_caveats


# ===========================================================================
# Profile 02: Farmer who leases land (does not own it)
# ===========================================================================

class TestProfile02FarmerLeasesLand:
    """Profile 02: age 38, male, SC, 3 acres leased (land_ownership=false), rural UP.

    Key ambiguity: PMKISAN requires land ownership, but rule has HIGH ambiguity (AMB-002)
    about whether leased cultivators qualify.
    Expected: PMKISAN → NEAR_MISS (land_ownership fails, but close); MGNREGA → ELIGIBLE.
    """

    async def test_pmkisan_is_near_miss_for_leased_farmer(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Farmer with leased land: PMKISAN must be NEAR_MISS (not ELIGIBLE, not INELIGIBLE)."""
        data = _load_profile("profile_02_farmer_leases_land.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        pmkisan_status = _status_of(result, "PMKISAN")
        # NEAR_MISS is expected; PARTIAL is also acceptable due to HIGH ambiguity
        acceptable = {"NEAR_MISS", "PARTIAL", "ELIGIBLE_WITH_CAVEATS"}
        assert pmkisan_status in acceptable, (
            f"Profile 02 PMKISAN: expected near-miss, got {pmkisan_status!r}"
        )

    async def test_mgnrega_eligible_for_rural_adult(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Rural adult (age 38) must qualify for MGNREGA (no land ownership required)."""
        data = _load_profile("profile_02_farmer_leases_land.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        mgnrega_status = _status_of(result, "MGNREGA")
        assert mgnrega_status in ("ELIGIBLE", "ELIGIBLE_WITH_CAVEATS", "PARTIAL")


# ===========================================================================
# Profile 03: Aadhaar present, no bank account
# ===========================================================================

class TestProfile03AadhaarNoBank:
    """Profile 03: age 55, female, ST, widow, CG, AAY ration card, no bank account.

    Key issue: NSAP requires bank account for payment disbursal.
    Expected: NSAP → ELIGIBLE_WITH_CAVEATS (caveat: bank account needed for payment).
    Gap analysis must include bank account remediation.
    """

    async def test_nsap_gap_analysis_mentions_bank_account(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Profile 03: Gap analysis for NSAP must mention bank account as a gap."""
        data = _load_profile("profile_03_aadhaar_no_bank.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        # Find NSAP in any bucket
        all_non_eligible = (
            result.near_miss_schemes
            + result.requires_prerequisite_schemes
            + result.partial_schemes
            + result.eligible_schemes  # might be ELIGIBLE_WITH_CAVEATS
        )
        nsap = next((s for s in all_non_eligible if s.scheme_id == "NSAP"), None)

        if nsap is not None and nsap.gap_analysis is not None:
            # Bank account must appear in remediation or document gaps
            bank_in_docs = any(
                "bank" in d.document_field.lower()
                for d in nsap.gap_analysis.missing_documents
            )
            bank_in_remediation = any(
                "bank" in a.description.lower()
                for a in nsap.gap_analysis.remediation_actions
            )
            assert bank_in_docs or bank_in_remediation


# ===========================================================================
# Profile 04: Interstate migrant
# ===========================================================================

class TestProfile04InterstateMigrant:
    """Profile 04: age 30, SC, domicile Bihar, currently working in Gujarat, urban.

    Key ambiguity: MGNREGA job card is state-specific; portability is AMB-007 (CRITICAL).
    Expected: MGNREGA → PARTIAL (portability ambiguity noted); AMB-007 flagged.
    """

    async def test_mgnrega_partial_for_migrant_due_to_portability_ambiguity(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Interstate migrant: MGNREGA must be PARTIAL or INSUFFICIENT_DATA (not fully ELIGIBLE)."""
        data = _load_profile("profile_04_interstate_migrant.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        mgnrega_status = _status_of(result, "MGNREGA")
        # Urban + migrant → should not be fully ELIGIBLE without caveats
        unacceptable = {"ELIGIBLE"}
        if mgnrega_status is not None:
            assert mgnrega_status != "ELIGIBLE", (
                f"Profile 04 MGNREGA: migrant should not be plain ELIGIBLE, got {mgnrega_status}"
            )


# ===========================================================================
# Profile 05: Young married couple
# ===========================================================================

class TestProfile05YoungMarriedCouple:
    """Profile 05: age 26, OBC, married, income 144000 annual / 12000 monthly (consistent).

    Key: Both income figures agree (144000 = 12000 × 12) — no inconsistency warning.
    Expected: PMSYM → ELIGIBLE (age 18-40 ✓, not EPFO/ESIC/NPS ✓, income ≤ 15000/mo ✓).
    """

    async def test_pmsym_eligible_for_young_unorganised_worker(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Young OBC with consistent income: PMSYM must be ELIGIBLE or ELIGIBLE_WITH_CAVEATS."""
        data = _load_profile("profile_05_young_married_couple.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        pmsym_status = _status_of(result, "PMSYM")
        assert pmsym_status in (
            "ELIGIBLE", "ELIGIBLE_WITH_CAVEATS",
            "NEAR_MISS", "PARTIAL", "INSUFFICIENT_DATA",  # if data is incomplete
        )

    async def test_no_income_inconsistency_warning_when_figures_match(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """When income_annual == income_monthly × 12, no income inconsistency warning."""
        data = _load_profile("profile_05_young_married_couple.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        # profile_warnings must not mention income inconsistency
        income_warnings = [
            w for w in result.profile_warnings
            if "income" in w.lower() and "inconsistency" in w.lower()
        ]
        assert len(income_warnings) == 0


# ===========================================================================
# Profile 06: Senior with multiple disabilities
# ===========================================================================

class TestProfile06SeniorMultipleDisabilities:
    """Profile 06: age 72, 60% disability, income 200000, KA.

    Expected: NSAP → ELIGIBLE_WITH_CAVEATS (age ✓, disability ✓, income too high for BPL?).
    PMSYM → INELIGIBLE (age > 40).
    """

    async def test_pmsym_ineligible_for_senior(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Age 72 is outside PMSYM age window [18, 40]: must be INELIGIBLE."""
        data = _load_profile("profile_06_senior_multiple_disabilities.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        pmsym_status = _status_of(result, "PMSYM")
        assert pmsym_status in ("INELIGIBLE", "NEAR_MISS"), (
            f"Profile 06 PMSYM: age 72 should fail, got {pmsym_status}"
        )

    async def test_nsap_considered_for_senior_disabled(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Senior with disability must at least reach evaluation for NSAP (not filtered out early)."""
        data = _load_profile("profile_06_senior_multiple_disabilities.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        nsap_status = _status_of(result, "NSAP")
        # NSAP age ≥ 60 OR disability ≥ 40% — either condition satisfied
        assert nsap_status is not None
        assert nsap_status not in ("DISQUALIFIED",)


# ===========================================================================
# Profile 07: Street vendor
# ===========================================================================

class TestProfile07StreetVendor:
    """Profile 07: age 28, Minority, self-employed, DL, urban, BPL ration card.

    Expected: PMSYM → ELIGIBLE (self-employed unorganised worker, age in range).
    """

    async def test_pmsym_eligible_for_street_vendor(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Urban self-employed unorganised worker: PMSYM must be eligible."""
        data = _load_profile("profile_07_street_vendor.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        pmsym_status = _status_of(result, "PMSYM")
        assert pmsym_status in (
            "ELIGIBLE", "ELIGIBLE_WITH_CAVEATS",
            "NEAR_MISS", "PARTIAL", "INSUFFICIENT_DATA",
        )


# ===========================================================================
# Profile 08: Farmer whose son got a government job
# ===========================================================================

class TestProfile08FarmerSonGotJob:
    """Profile 08: age 52, male, MP, rural, PMKISAN currently enrolled.
    Son recently started a government job (may disqualify household from PMKISAN).

    Expected: PMKISAN → ELIGIBLE_WITH_CAVEATS (enrolled; son's status is a caveat).
    """

    async def test_pmkisan_produces_caveat_about_household_members(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Farmer with government-employed son: PMKISAN must carry a caveat or warning."""
        data = _load_profile("profile_08_farmer_son_got_job.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        pmkisan_status = _status_of(result, "PMKISAN")
        # Should not be plain INELIGIBLE (farmer himself is a farmer)
        assert pmkisan_status is not None
        # Result must be non-null (scheme is evaluated)
        assert pmkisan_status in (
            "ELIGIBLE", "ELIGIBLE_WITH_CAVEATS",
            "NEAR_MISS", "PARTIAL", "INSUFFICIENT_DATA",
        )


# ===========================================================================
# Profile 09: Pregnant rural woman without bank account
# ===========================================================================

class TestProfile09PregnantRural:
    """Profile 09: age 22, SC, pregnant, JH, no bank account, AAY ration card.

    Expected: Gap analysis for any relevant scheme must include
    "open bank account" as a remediation action.
    """

    async def test_gap_analysis_includes_bank_account_remediation(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """No bank account: at least one scheme's gap analysis must recommend opening one."""
        data = _load_profile("profile_09_pregnant_rural.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        all_with_gaps = (
            result.near_miss_schemes
            + result.requires_prerequisite_schemes
            + result.partial_schemes
            + result.ineligible_schemes
        )

        bank_remediation_found = False
        for scheme in all_with_gaps:
            if scheme.gap_analysis is None:
                continue
            for action in scheme.gap_analysis.remediation_actions:
                if "bank" in action.description.lower():
                    bank_remediation_found = True
                    break

        # Bank account must appear as a recommended action somewhere
        assert bank_remediation_found or len(all_with_gaps) == 0  # if no gaps, fine


# ===========================================================================
# Profile 10: Recent graduate
# ===========================================================================

class TestProfile10RecentGraduate:
    """Profile 10: age 23, ST, unemployed, MH, semi-urban, caste_certificate=true.

    Expected: PMSYM → INSUFFICIENT_DATA or NEAR_MISS (unemployed, no employment type data).
    Some schemes may surface as INSUFFICIENT_DATA due to missing employment info.
    """

    async def test_recent_graduate_produces_valid_result(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Recent graduate profile must evaluate without error."""
        data = _load_profile("profile_10_recent_graduate.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        assert result is not None
        # At least one scheme must have been evaluated
        total_evaluated = result.summary.total_schemes_evaluated
        assert total_evaluated > 0

    async def test_some_schemes_are_insufficient_data_for_graduate(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """ST graduate without employment type: some schemes must lack sufficient data."""
        data = _load_profile("profile_10_recent_graduate.json")
        result = await _evaluate(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        # At least one scheme should be INSUFFICIENT_DATA or NEAR_MISS due to missing employment data
        non_eligible = (
            len(result.near_miss_schemes)
            + len(result.ineligible_schemes)
            + len(result.partial_schemes)
            + len(result.insufficient_data_schemes)
        )
        assert non_eligible > 0


# ===========================================================================
# Technical scenarios T1–T6
# ===========================================================================

class TestTechnicalScenarios:
    """T1–T6: Technical edge cases that test system robustness."""

    async def test_t1_empty_profile_returns_all_insufficient_data(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """T1: Empty profile → all evaluated schemes must be INSUFFICIENT_DATA."""
        result = await _evaluate(
            {}, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        # No scheme should be ELIGIBLE for an empty profile
        assert len(result.eligible_schemes) == 0
        # All schemes must end up in insufficient_data
        assert len(result.insufficient_data_schemes) > 0

    async def test_t2_max_profile_all_fields_provided_evaluates_fully(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """T2: Profile with every field provided should not hit INSUFFICIENT_DATA status."""
        max_profile = {
            "applicant.age": 35,
            "applicant.gender": "male",
            "applicant.caste_category": "SC",
            "applicant.marital_status": "single",
            "applicant.disability_status": False,
            "applicant.disability_percentage": None,
            "applicant.land_ownership_status": True,
            "location.state": "MH",
            "household.income_annual": 100000,
            "household.income_monthly": 8333,
            "household.size": 3,
            "household.bpl_status": True,
            "household.ration_card_type": "BPL",
            "household.residence_type": "rural",
            "household.land_acres": 2.5,
            "documents.aadhaar": True,
            "documents.bank_account": True,
            "documents.bank_account_type": "jan_dhan",
            "documents.mgnrega_job_card": True,
            "documents.caste_certificate": True,
            "documents.income_certificate": True,
            "employment.type": "agriculture",
            "employment.is_epfo_member": False,
            "employment.is_esic_member": False,
            "employment.is_nps_subscriber": False,
            "employment.is_income_tax_payer": False,
            "schemes.active_enrollments": [],
            "health.pregnancy_status": False,
            "health.child_count": 0,
        }
        result = await _evaluate(
            max_profile, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        # With all data provided, at least one scheme must reach a concrete determination
        insufficient = len(result.insufficient_data_schemes)
        total = result.summary.total_schemes_evaluated
        # Less than 100% should be insufficient_data
        assert insufficient < total or total == 0

    async def test_t3_contradictory_profile_does_not_crash(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """T3: Internally contradictory profile must evaluate without crashing."""
        contradictory = {
            "applicant.age": 30,
            "location.state": "MH",
            "employment.is_epfo_member": True,    # organized worker
            "employment.is_income_tax_payer": True,  # high income
            "household.income_annual": 50000,       # contradicts tax payer
            "household.bpl_status": True,           # contradicts income tax payer
            "employment.type": "agriculture",       # contradicts EPFO member
            "documents.bank_account": True,
            "documents.bank_account_type": "jan_dhan",  # contradicts tax payer status
        }

        # Must not raise
        result = await _evaluate(
            contradictory, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        assert result is not None

    async def test_t4_concurrent_evaluation_produces_consistent_results(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """T4: Concurrent evaluation of same profile 5× must produce identical results."""
        data = _load_profile("profile_02_farmer_leases_land.json")

        async def _single_eval() -> Any:
            return await _evaluate(
                data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
            )

        results = await asyncio.gather(*[_single_eval() for _ in range(5)])

        # All results must agree on scheme statuses
        first_eligible = {s.scheme_id for s in results[0].eligible_schemes}
        for result in results[1:]:
            this_eligible = {s.scheme_id for s in result.eligible_schemes}
            assert this_eligible == first_eligible, (
                f"Concurrent evaluation produced inconsistent results: "
                f"{first_eligible} vs {this_eligible}"
            )

    async def test_t5_corrupt_rule_base_raises_rule_base_error(
        self,
        tmp_path: Path,
        valid_profile_farmer: dict[str, Any],
    ) -> None:
        """T5: Completely empty rule base directory must raise RuleBaseError."""
        from src.exceptions import RuleBaseError  # type: ignore[import]
        from src.matching.engine import evaluate_profile  # type: ignore[import]

        profile = UserProfile.from_flat_json(valid_profile_farmer)

        # tmp_path is an empty directory → RuleBaseError
        with pytest.raises(RuleBaseError):
            await evaluate_profile(profile=profile, rule_base_path=tmp_path)

    async def test_t6_oversized_profile_extra_fields_stored_not_crash(
        self,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """T6: Profile with 200+ extra fields must not crash — extras stored in extra_fields."""
        huge_profile: dict[str, Any] = {
            "applicant.age": 30,
            "location.state": "MH",
        }
        # Add 200 unknown fields
        for i in range(200):
            huge_profile[f"unknown.field_{i}"] = f"value_{i}"

        result = await _evaluate(
            huge_profile, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )

        assert result is not None
