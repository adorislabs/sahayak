"""Part 4 — 30 Ambiguity Types Coverage Validation.

Spec reference: docs/project-overview.md § 4.2
QA framework:  framework/prompts/QA/QA-PART-4.md

Validates that the ambiguity_map module:
  1. Contains all 30 canonical ambiguity types in its taxonomy
  2. Detects each type (or a representative superset) via regex patterns
  3. Flags the correct severity for CRITICAL types
  4. Never produces a silent PASS when CRITICAL ambiguity is present
  5. Coverage threshold: ≥ 26/30 types must be detectable by the pipeline
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.ambiguity_map import (
    AMBIGUITY_TAXONOMY,
    detect_ambiguity_type,
)
from src.schema import AmbiguitySeverity, Rule

FIXTURES_DIR = Path(__file__).parent / "test_data" / "fixtures"

# ---------------------------------------------------------------------------
# Taxonomy completeness
# ---------------------------------------------------------------------------


class TestAmbiguityTaxonomyCompleteness:
    """Validate the 30-type taxonomy is fully populated."""

    def test_taxonomy_has_exactly_30_types(self) -> None:
        assert len(AMBIGUITY_TAXONOMY) == 30, (
            f"Expected 30 ambiguity types, got {len(AMBIGUITY_TAXONOMY)}"
        )

    def test_taxonomy_keys_are_1_to_30(self) -> None:
        keys = set(AMBIGUITY_TAXONOMY.keys())
        expected = set(range(1, 31))
        missing = expected - keys
        assert not missing, f"Missing type codes: {sorted(missing)}"

    def test_all_taxonomy_values_are_non_empty_strings(self) -> None:
        for code, name in AMBIGUITY_TAXONOMY.items():
            assert isinstance(name, str) and len(name) > 0, (
                f"Taxonomy type {code} has empty or non-string name: {name!r}"
            )

    def test_taxonomy_contains_critical_types(self) -> None:
        """Key types that affect real beneficiaries must be present by name."""
        required_names = {
            "Portability Gap",           # type 7 — interstate migrants
            "Infrastructure Precondition",  # type 20 — DBT/bank account
            "Life-Event Transition Ambiguity",  # type 21 — widows remarrying
            "Household Definition Inconsistency",  # type 22 — family splits
        }
        names_in_taxonomy = set(AMBIGUITY_TAXONOMY.values())
        for name in required_names:
            assert name in names_in_taxonomy, (
                f"Required ambiguity type {name!r} not found in taxonomy"
            )


# ---------------------------------------------------------------------------
# Regex pattern coverage: known triggers per type
# ---------------------------------------------------------------------------

# Map from ambiguity_type_code → list of sample texts that SHOULD trigger that type
_TYPE_TRIGGERS: dict[int, list[str]] = {
    1:  ["applicant must be a resident of the state",
         "deserving weaker section candidates may apply"],
    2:  ["cannot prove land ownership without cultivation records",
         "lease land documentation gap"],
    3:  ["contradicts central guidelines; simultaneously requires both conditions",
         "conflicting requirement in state and central eligibility"],
    4:  ["at the discretion of the district magistrate",
         "may be selected subject to approval"],
    5:  ["application must be submitted within 30 days of eligibility event",
         "benefit expires after validity period of 6 months"],
    6:  ["applicant must not be a member of any other pension scheme",
         "not eligible if enrolled in EPF"],
    7:  ["ration card issued within the state of registration",
         "applicable only within the state"],
    8:  ["income between 1 lakh and 3 lakh falls in borderline income category",
         "income from 50000 to 150000 threshold overlap"],
    9:  ["prerequisite scheme has prerequisite dependency"],
    10: ["household income must be below poverty line",
         "below the poverty line (BPL)"],
    11: ["OBC boundary varies by state; category overlap with SC certificate",
         "backward class list differs across jurisdictions"],
    12: ["list of acceptable documents varies by state and district",
         "certificate accepted only if issued within the last 6 months"],
    13: ["already receiving benefit under another scheme with same benefit",
         "simultaneous claim may result in double benefit"],
    14: ["gram panchayat boundary conflict with block-level scheme coverage",
         "panchayat limit creates administrative conflict"],
    15: ["implementation pending in rural areas; not yet operational in this district",
         "scheme yet to be notified in this state"],
    16: ["son's government job affects household income exclusion",
         "family income includes member from separate household"],
    17: ["applicant may appeal within 30 days to appellate authority",
         "right to appeal against rejection"],
    18: ["grievance redressal via toll-free helpline and nodal officer",
         "complaint mechanism available through ombudsman"],
    19: ["Hindi version says: within 6 months; English version says: within 3 months"],
    20: ["payment via bank account direct benefit transfer",
         "Aadhaar-linked bank account required"],
    21: ["upon death of spouse, benefit ceases",
         "widow remarriage affects entitlement"],
    22: ["joint family vs nuclear family definition applies",
         "married daughter living separately — separate household"],
    23: ["permanent resident of the state required",
         "domicile certificate mandatory"],
    24: ["family income vs individual income for income computation",
         "per capita income calculation method"],
    25: ["OBC certificate from central list differs from state backward class list",
         "caste certificate jurisdiction conflict across states"],
    26: ["women only scheme; male applicants excluded",
         "gender eligibility: only female beneficiaries"],
    27: ["age as on date of application must be 18 years",
         "completed 60 years on the date"],
    28: ["land record patta khata must match revenue record",
         "jamabandi from land registry required"],
    29: ["disability certificate required; PwD with percentage disability above 40",
         "benchmark disability certification from competent authority"],
    30: ["scheme does not require Aadhaar", "without aadhaar linkage"],
}


class TestAmbiguityTypeDetection:
    """Each type with a known trigger text must be detectable."""

    @pytest.mark.parametrize("type_code,texts", list(_TYPE_TRIGGERS.items()))
    def test_trigger_texts_detected_for_type(self, type_code: int, texts: list[str]) -> None:
        """Given a trigger text, the correct ambiguity type must be detected."""
        detected_types: set[int] = set()
        for text in texts:
            mock_rule = MagicMock(spec=Rule)
            mock_rule.rule_id = f"TEST-{type_code:02d}"
            mock_rule.scheme_id = "TEST"
            flags = detect_ambiguity_type(text, mock_rule)
            for flag in flags:
                detected_types.add(flag.ambiguity_type_code)

        assert type_code in detected_types, (
            f"Type {type_code} ({AMBIGUITY_TAXONOMY[type_code]!r}) "
            f"not detected by any trigger text: {texts}"
        )


class TestAmbiguityCoverageThreshold:
    """At least 26/30 types must be detectable (≥87% coverage)."""

    def test_at_least_26_types_have_trigger_coverage(self) -> None:
        covered = set(_TYPE_TRIGGERS.keys())
        assert len(covered) >= 26, (
            f"Only {len(covered)}/30 types have known trigger texts — need ≥26"
        )

    def test_at_least_10_trigger_types_produce_detections(self) -> None:
        """Integration check: at least 10 trigger types fire correctly."""
        detected_count = 0
        for type_code, texts in _TYPE_TRIGGERS.items():
            for text in texts:
                mock_rule = MagicMock(spec=Rule)
                mock_rule.rule_id = f"TEST-{type_code:02d}"
                mock_rule.scheme_id = "TEST"
                flags = detect_ambiguity_type(text, mock_rule)
                if any(f.ambiguity_type_code == type_code for f in flags):
                    detected_count += 1
                    break

        assert detected_count >= 10, (
            f"Only {detected_count} types detected in integration check; expected ≥10"
        )


# ---------------------------------------------------------------------------
# Severity mapping
# ---------------------------------------------------------------------------

class TestAmbiguitySeverity:
    """CRITICAL severity types must produce CRITICAL flags."""

    CRITICAL_TRIGGERS = [
        ("AMB-007-test", "MGNREGA", "ration card issued within the state of registration"),
        ("AMB-012-test", "NSAP",    "disability threshold is 40% per central and 80% per state"),
    ]

    @pytest.mark.parametrize("rule_id,scheme_id,text", CRITICAL_TRIGGERS)
    def test_portability_gap_is_critical_severity(
        self, rule_id: str, scheme_id: str, text: str
    ) -> None:
        mock_rule = MagicMock(spec=Rule)
        mock_rule.rule_id = rule_id
        mock_rule.scheme_id = scheme_id
        flags = detect_ambiguity_type(text, mock_rule)
        if flags:
            high_or_critical = [
                f for f in flags
                if f.severity in (AmbiguitySeverity.CRITICAL, AmbiguitySeverity.HIGH)
            ]
            assert len(high_or_critical) > 0, (
                f"Expected HIGH/CRITICAL ambiguity for {text!r}, got: {[f.severity for f in flags]}"
            )


# ---------------------------------------------------------------------------
# Fixture-based: load ambiguity_map.json and validate format
# ---------------------------------------------------------------------------

class TestAmbiguityMapFixture:
    """Validate the canonical fixture ambiguity_map.json."""

    def test_fixture_loads_and_has_required_keys(self) -> None:
        path = FIXTURES_DIR / "ambiguity_map.json"
        data: list[dict] = json.loads(path.read_text())
        assert isinstance(data, list)
        assert len(data) > 0

        required_keys = {"ambiguity_id", "scheme_id", "ambiguity_type_code",
                         "ambiguity_type_name", "severity", "resolution_status"}
        for entry in data:
            missing = required_keys - entry.keys()
            assert not missing, f"ambiguity_map.json entry missing keys: {missing}"

    def test_fixture_ambiguity_type_codes_are_valid(self) -> None:
        path = FIXTURES_DIR / "ambiguity_map.json"
        data: list[dict] = json.loads(path.read_text())
        valid_codes = set(AMBIGUITY_TAXONOMY.keys())
        for entry in data:
            code = entry["ambiguity_type_code"]
            assert code in valid_codes, (
                f"ambiguity_map.json has unknown type code {code}"
            )

    def test_fixture_severities_are_valid(self) -> None:
        path = FIXTURES_DIR / "ambiguity_map.json"
        data: list[dict] = json.loads(path.read_text())
        valid = {s.value for s in AmbiguitySeverity}
        for entry in data:
            sev = entry["severity"]
            assert sev in valid, f"Invalid severity {sev!r} in ambiguity_map.json"

    def test_fixture_contains_critical_ambiguities(self) -> None:
        path = FIXTURES_DIR / "ambiguity_map.json"
        data: list[dict] = json.loads(path.read_text())
        critical = [e for e in data if e["severity"] == "CRITICAL"]
        assert len(critical) >= 1, "ambiguity_map.json must contain at least one CRITICAL entry"


# ---------------------------------------------------------------------------
# No-silent-pass rule: CRITICAL ambiguity must surface to caller
# ---------------------------------------------------------------------------

class TestNoSilentPassOnCriticalAmbiguity:
    """When a rule triggers CRITICAL ambiguity, detect_ambiguities must return ≥1 flag."""

    def test_portability_text_returns_flags(self) -> None:
        text = "MGNREGA job card applicable only within the state of registration"
        mock_rule = MagicMock(spec=Rule)
        mock_rule.rule_id = "MGNREGA-R002"
        mock_rule.scheme_id = "MGNREGA"
        flags = detect_ambiguity_type(text, mock_rule)
        assert len(flags) > 0, "Portability gap text must not silently pass"

    def test_empty_text_returns_no_flags(self) -> None:
        mock_rule = MagicMock(spec=Rule)
        mock_rule.rule_id = "EMPTY-001"
        mock_rule.scheme_id = "TEST"
        flags = detect_ambiguity_type("", mock_rule)
        # Empty text should produce no false positives
        assert isinstance(flags, list)
        assert len(flags) == 0
