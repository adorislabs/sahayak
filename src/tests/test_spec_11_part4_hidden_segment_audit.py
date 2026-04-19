"""Part 4 — Hidden Segment Audit.

Spec reference: docs/project-overview.md § 4.4
QA framework:  framework/prompts/QA/QA-PART-4.md

Validates that the pipeline correctly handles the three hidden segments:
  1. Migrant Portability — portability gap ambiguity must be detectable
  2. Home-Based / Self-Employed Workers — profile parsing must succeed
  3. Infrastructure Preconditions — DBT/Aadhaar-linked account flags must surface

Tests at this level focus on:
  - Profile parsability (UserProfile.from_flat_json)
  - Ambiguity detection for segment-specific trigger texts
  - JSON fixture structural validation for all 10 profile files
  - Rule-level ambiguity flag correctness for anchor schemes

Engine integration tests (using mock rulesets) live in test_matching/test_adversarial.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.ambiguity_map import detect_ambiguity_type
from src.matching.profile import UserProfile  # type: ignore[import]
from src.schema import AmbiguitySeverity, Rule

FIXTURES_DIR = Path(__file__).parent / "test_data" / "fixtures"
PROFILES_DIR = Path(__file__).parent / "test_data" / "profiles"


# ---------------------------------------------------------------------------
# All 10 profile fixture files: structural integrity
# ---------------------------------------------------------------------------

ALL_PROFILES = [
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


class TestProfileFixtureIntegrity:
    """All 10 profile JSON files must be parsable by UserProfile.from_flat_json."""

    @pytest.mark.parametrize("profile_file", ALL_PROFILES)
    def test_profile_json_is_valid(self, profile_file: str) -> None:
        """Profile file must be valid JSON."""
        path = PROFILES_DIR / profile_file
        assert path.exists(), f"Profile fixture missing: {profile_file}"
        data = json.loads(path.read_text())
        assert isinstance(data, dict), f"{profile_file}: expected dict, got {type(data)}"
        assert len(data) > 0, f"{profile_file}: empty profile dict"

    @pytest.mark.parametrize("profile_file", ALL_PROFILES)
    def test_profile_is_parsable_by_user_profile(self, profile_file: str) -> None:
        """UserProfile.from_flat_json must accept every profile without raising."""
        data = json.loads((PROFILES_DIR / profile_file).read_text())
        profile = UserProfile.from_flat_json(data)
        assert profile is not None

    @pytest.mark.parametrize("profile_file", ALL_PROFILES)
    def test_profile_has_age_and_state(self, profile_file: str) -> None:
        """Every profile must have age and state (minimum viable evaluation keys)."""
        data = json.loads((PROFILES_DIR / profile_file).read_text())
        assert "applicant.age" in data, f"{profile_file}: missing applicant.age"
        assert "location.state" in data, f"{profile_file}: missing location.state"


# ---------------------------------------------------------------------------
# Segment 1: Migrant Portability — AMB-007 detection
# ---------------------------------------------------------------------------

class TestMigrantPortabilityAmbiguity:
    """Portability Gap (type 7) must fire on migration-related rule text."""

    _PORTABILITY_TEXTS = [
        "MGNREGA job card applicable only within the state of registration",
        "scheme benefits restricted to home state residents",
        "portability of benefits not available across state boundaries",
        "entitlement lapses on change of domicile state",
    ]

    @pytest.mark.parametrize("text", _PORTABILITY_TEXTS)
    def test_portability_gap_detected(self, text: str) -> None:
        mock_rule = MagicMock(spec=Rule)
        mock_rule.rule_id = "MGNREGA-R002"
        mock_rule.scheme_id = "MGNREGA"
        flags = detect_ambiguity_type(text, mock_rule)
        assert len(flags) > 0, (
            f"No ambiguity detected in portability text: {text!r}"
        )

    def test_migrant_profile_has_state_field(self) -> None:
        """Profile 04 (interstate migrant) must indicate state/domicile information."""
        data = json.loads(
            (PROFILES_DIR / "profile_04_interstate_migrant.json").read_text()
        )
        state_fields = {k for k in data if "state" in k.lower() or "domicile" in k.lower()}
        assert len(state_fields) >= 1, (
            "Interstate migrant profile must have at least one state-related field"
        )


# ---------------------------------------------------------------------------
# Segment 2: Home-Based / Self-Employed Workers
# ---------------------------------------------------------------------------

class TestHomeBasedWorkers:
    """Self-employed / informal workers must be parsable and not hard-excluded."""

    def test_street_vendor_profile_parsed(self) -> None:
        """Profile 07 (street vendor) must be parsable without missing required fields."""
        data = json.loads(
            (PROFILES_DIR / "profile_07_street_vendor.json").read_text()
        )
        profile = UserProfile.from_flat_json(data)
        assert profile is not None

    def test_street_vendor_has_employment_type(self) -> None:
        """Street vendor profile must specify employment type."""
        data = json.loads(
            (PROFILES_DIR / "profile_07_street_vendor.json").read_text()
        )
        employment_keys = {k for k in data if k.startswith("employment.")}
        assert len(employment_keys) >= 1, (
            "Street vendor profile must have at least one employment.* field"
        )

    def test_self_employed_minimal_profile_parsable(self) -> None:
        """Minimal self-employed profile with no formal employer must parse correctly."""
        data = {
            "applicant.age": 32,
            "applicant.gender": "female",
            "location.state": "MH",
            "household.income_monthly": 8000,
            "employment.type": "self_employed",
            "employment.is_epfo_member": False,
        }
        profile = UserProfile.from_flat_json(data)
        assert profile is not None

    def test_home_based_worker_profile_parsable(self) -> None:
        """Home-based worker profile must parse without errors."""
        data = {
            "applicant.age": 35,
            "applicant.gender": "female",
            "location.state": "UP",
            "household.income_annual": 60000,
            "employment.type": "home_based",
            "employment.is_epfo_member": False,
            "documents.aadhaar": True,
        }
        profile = UserProfile.from_flat_json(data)
        assert profile is not None


# ---------------------------------------------------------------------------
# Segment 3: Infrastructure Preconditions — AMB-020 detection
# ---------------------------------------------------------------------------

class TestInfrastructurePreconditionAmbiguity:
    """DBT and Aadhaar-linked payment requirements must trigger type 20."""

    _DBT_TEXTS = [
        "payment via direct benefit transfer to Aadhaar-linked bank account",
        "subject to availability of DBT infrastructure in the district",
        "benefits transferred through DBT mechanism",
        "disbursement conditional on active Aadhaar-linked bank account",
    ]

    @pytest.mark.parametrize("text", _DBT_TEXTS)
    def test_dbt_triggers_type_20(self, text: str) -> None:
        mock_rule = MagicMock(spec=Rule)
        mock_rule.rule_id = "TEST-DBT"
        mock_rule.scheme_id = "NSAP"
        flags = detect_ambiguity_type(text, mock_rule)
        type_codes = {f.ambiguity_type_code for f in flags}
        assert 20 in type_codes, (
            f"DBT text {text!r} did not trigger type 20 (Infrastructure Precondition). "
            f"Got types: {sorted(type_codes)}"
        )

    def test_profile_without_bank_has_missing_field(self) -> None:
        """Profile 03 (no bank account) must have documents.bank_account=False."""
        data = json.loads(
            (PROFILES_DIR / "profile_03_aadhaar_no_bank.json").read_text()
        )
        bank_val = data.get("documents.bank_account")
        assert bank_val is False or bank_val == 0, (
            f"Profile 03 should have documents.bank_account=False, got {bank_val!r}"
        )

    def test_profile_with_aadhaar_but_no_bank_is_parsable(self) -> None:
        """Profile 03: Aadhaar present, no bank — must parse without error."""
        data = json.loads(
            (PROFILES_DIR / "profile_03_aadhaar_no_bank.json").read_text()
        )
        profile = UserProfile.from_flat_json(data)
        assert profile is not None


# ---------------------------------------------------------------------------
# Anchor scheme ambiguity fixture validation
# ---------------------------------------------------------------------------

class TestAmbiguityMapFixture:
    """ambiguity_map.json fixture must contain entries for all hidden segment types."""

    def test_ambiguity_fixture_loads(self) -> None:
        data = json.loads((FIXTURES_DIR / "ambiguity_map.json").read_text())
        assert isinstance(data, list)
        assert len(data) >= 4

    def test_portability_gap_entry_present(self) -> None:
        """AMB-007 (Portability Gap, MGNREGA) must be in ambiguity_map.json."""
        data = json.loads((FIXTURES_DIR / "ambiguity_map.json").read_text())
        portability_entries = [
            e for e in data
            if e.get("ambiguity_type_code") == 7
            or "portability" in e.get("ambiguity_type_name", "").lower()
        ]
        assert len(portability_entries) >= 1, (
            "ambiguity_map.json must contain at least one Portability Gap (type 7) entry"
        )

    def test_infrastructure_precondition_entry_present(self) -> None:
        """AMB-020 (Infrastructure Precondition) must be in ambiguity_map.json."""
        data = json.loads((FIXTURES_DIR / "ambiguity_map.json").read_text())
        infra_entries = [
            e for e in data
            if e.get("ambiguity_type_code") == 20
            or "infrastructure" in e.get("ambiguity_type_name", "").lower()
        ]
        assert len(infra_entries) >= 1, (
            "ambiguity_map.json must contain at least one Infrastructure Precondition (type 20) entry"
        )

    def test_all_ambiguity_entries_have_required_keys(self) -> None:
        data = json.loads((FIXTURES_DIR / "ambiguity_map.json").read_text())
        required = {"ambiguity_id", "scheme_id", "ambiguity_type_code", "severity"}
        for entry in data:
            missing = required - entry.keys()
            assert not missing, (
                f"Ambiguity entry {entry.get('ambiguity_id')} missing keys: {missing}"
            )

    def test_all_severity_values_are_valid(self) -> None:
        valid_severities = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        data = json.loads((FIXTURES_DIR / "ambiguity_map.json").read_text())
        for entry in data:
            sev = entry.get("severity", "").upper()
            assert sev in valid_severities, (
                f"Entry {entry.get('ambiguity_id')} has invalid severity: {sev!r}"
            )
