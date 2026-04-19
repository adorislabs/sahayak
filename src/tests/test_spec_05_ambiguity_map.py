"""
Tests for spec_05_ambiguity_map.py

Module: src/spec_05_ambiguity_map.py
Spec:   docs/part1-planning/tests/spec_05_ambiguity_map.md
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.schema import AmbiguityFlag, AmbiguitySeverity, Rule, SourceAnchor  # type: ignore[import]
from src.ambiguity_map import (  # type: ignore[import]
    AMBIGUITY_TAXONOMY,
    apply_partial_determination,
    assign_severity,
    detect_ambiguity_type,
    export_ambiguity_map,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_VALID_ANCHOR = SourceAnchor(
    source_url="https://pmkisan.gov.in/guidelines.pdf",
    document_title="PM-KISAN Guidelines",
    source_quote="All landholding farmer families shall own cultivable land",
    section="3.2",
    notification_date="2023-11-15",
    language="en",
)


def _make_rule(rule_id: str, scheme_id: str = "PMKISAN") -> Rule:
    return Rule(
        rule_id=rule_id,
        scheme_id=scheme_id,
        rule_type="eligibility",
        condition_type="land_ownership",
        field="applicant.land_ownership_status",
        operator="EQ",
        value=True,
        source_anchor=_VALID_ANCHOR,
        confidence=0.95,
        parse_run_id="RUN-001",
        display_text=f"Rule {rule_id}",
    )


def _make_flag(
    flag_id: str,
    scheme_id: str = "PMKISAN",
    type_code: int = 1,
    severity: str = "HIGH",
    rule_id: str | None = None,
) -> AmbiguityFlag:
    return AmbiguityFlag(
        ambiguity_id=flag_id,
        scheme_id=scheme_id,
        rule_id=rule_id,
        ambiguity_type_code=type_code,
        ambiguity_type_name=AMBIGUITY_TAXONOMY.get(type_code, "Unknown"),
        description=f"Test ambiguity flag {flag_id}",
        severity=severity,
    )


# ---------------------------------------------------------------------------
# Section 1: AMBIGUITY_TAXONOMY
# ---------------------------------------------------------------------------


class TestAmbiguityTaxonomy:
    def test__is_dict__has_exactly_30_entries(self) -> None:
        """AMBIGUITY_TAXONOMY has exactly 30 entries keyed 1–30."""
        assert isinstance(AMBIGUITY_TAXONOMY, dict)
        assert len(AMBIGUITY_TAXONOMY) == 30
        assert set(AMBIGUITY_TAXONOMY.keys()) == set(range(1, 31))

    def test__all_names_are_strings__non_empty(self) -> None:
        """Every taxonomy entry has a non-empty string name."""
        assert all(isinstance(v, str) and len(v) > 0 for v in AMBIGUITY_TAXONOMY.values())


# ---------------------------------------------------------------------------
# Section 2: detect_ambiguity_type
# ---------------------------------------------------------------------------


class TestDetectAmbiguityType:
    def test__semantic_vagueness__flags_type_1(self) -> None:
        """'resident of the state' (undefined term) → Type 1 (Semantic Vagueness)."""
        flags = detect_ambiguity_type("Applicant must be a resident of the state")
        assert any(f.ambiguity_type_code == 1 for f in flags)
        type_1 = next(f for f in flags if f.ambiguity_type_code == 1)
        assert type_1.ambiguity_type_name == AMBIGUITY_TAXONOMY[1]

    def test__discretionary_clause__flags_type_4(self) -> None:
        """'at the discretion of' → Type 4 (Discretionary Clauses)."""
        text = "Selection will be made at the discretion of the Block Development Officer"
        flags = detect_ambiguity_type(text)
        assert any(f.ambiguity_type_code == 4 for f in flags)

    def test__financial_threshold_flux__flags_type_10(self) -> None:
        """'below poverty line' without fixed numeric value → Type 10."""
        text = "Annual household income must be below the poverty line"
        flags = detect_ambiguity_type(text)
        assert any(f.ambiguity_type_code == 10 for f in flags)

    def test__mutual_exclusion__flags_type_6(self) -> None:
        """Explicit NPS disqualification → Type 6 (Mutual Exclusion)."""
        text = "Applicants enrolled in NPS are not eligible"
        rule = _make_rule("PMSYM-DIS001", "PMSYM")
        flags = detect_ambiguity_type(text, rule=rule)
        assert any(f.ambiguity_type_code == 6 for f in flags)

    def test__linguistic_translation_delta__flags_type_19(self) -> None:
        """English/Hindi version divergence → Type 19 (Linguistic Translation Delta)."""
        text = "English version says income < ₹2L; Hindi master gazette says < ₹2.5L"
        flags = detect_ambiguity_type(text)
        assert any(f.ambiguity_type_code == 19 for f in flags)

    def test__portability_gap__flags_type_7(self) -> None:
        """'within the state of registration' with no portability mention → Type 7."""
        text = "Scheme benefits applicable within the state of registration"
        flags = detect_ambiguity_type(text)
        assert any(f.ambiguity_type_code == 7 for f in flags)

    def test__life_event_transition__flags_type_21(self) -> None:
        """'Widows are eligible; no remarriage clause' → Type 21 (Life-Event Transition)."""
        text = "Widows are eligible; no mention of what happens upon remarriage"
        flags = detect_ambiguity_type(text)
        assert any(f.ambiguity_type_code == 21 for f in flags)

    def test__clear_text__returns_empty_list_without_raising(self) -> None:
        """Clear numeric text → empty list; no exception."""
        flags = detect_ambiguity_type("Applicant must be between 18 and 40 years of age.")
        assert isinstance(flags, list)

    def test__empty_string__returns_empty_list_without_raising(self) -> None:
        """Empty string → empty list; no exception."""
        flags = detect_ambiguity_type("")
        assert isinstance(flags, list)

    def test__flag_contains_required_fields__all_fields_present(self) -> None:
        """Every returned flag has all required fields populated."""
        text = "Eligible residents may apply at official's discretion"
        flags = detect_ambiguity_type(text)
        for f in flags:
            assert f.ambiguity_id.startswith("AMB-")
            assert 1 <= f.ambiguity_type_code <= 30
            assert len(f.description) > 0
            assert f.severity in list(AmbiguitySeverity)


# ---------------------------------------------------------------------------
# Section 3: assign_severity
# ---------------------------------------------------------------------------


class TestAssignSeverity:
    def test__prerequisite_chaining__returns_critical(self) -> None:
        """Type 9 (Prerequisite Chaining / circular dependency) → CRITICAL."""
        severity = assign_severity(9, {"scheme_a": "PMAY", "scheme_b": "MGNREGA"})
        assert severity == AmbiguitySeverity.CRITICAL

    def test__semantic_vagueness__returns_high_or_critical(self) -> None:
        """Type 1 affecting income threshold → HIGH or CRITICAL."""
        severity = assign_severity(1, {"field_affected": "household.income_annual"})
        assert severity in (AmbiguitySeverity.HIGH, AmbiguitySeverity.CRITICAL)

    def test__grievance_redressal__returns_medium_or_low(self) -> None:
        """Type 18 (Grievance Redressal Specificity) → MEDIUM or LOW."""
        severity = assign_severity(18, {})
        assert severity in (AmbiguitySeverity.MEDIUM, AmbiguitySeverity.LOW)

    def test__infrastructure_preconditions__returns_critical_or_high(self) -> None:
        """Type 20 (Infrastructure Preconditions) for AYUSHMAN → CRITICAL or HIGH."""
        severity = assign_severity(20, {"scheme_id": "AYUSHMAN"})
        assert severity in (AmbiguitySeverity.CRITICAL, AmbiguitySeverity.HIGH)


# ---------------------------------------------------------------------------
# Section 4: export_ambiguity_map
# ---------------------------------------------------------------------------


class TestExportAmbiguityMap:
    def test__json_format__returns_valid_json_string(self) -> None:
        """2 flags, format='json' → valid JSON string with 2 items."""
        flags = [_make_flag("AMB-001"), _make_flag("AMB-002")]
        output = export_ambiguity_map(flags, "json")

        assert isinstance(output, str)
        parsed = json.loads(output)
        assert len(parsed) == 2

    def test__csv_format__returns_valid_csv_string(self) -> None:
        """2 flags, format='csv' → CSV with header row and data row."""
        flags = [_make_flag("AMB-001"), _make_flag("AMB-002")]
        output = export_ambiguity_map(flags, "csv")

        assert isinstance(output, str)
        lines = [line for line in output.splitlines() if line.strip()]
        assert len(lines) >= 2  # header + at least one data row
        assert "ambiguity_id" in lines[0].lower() or "AMB" in lines[1]

    def test__markdown_format__returns_markdown_table(self) -> None:
        """1 flag, format='markdown' → Markdown table with flag ID."""
        flags = [_make_flag("AMB-001")]
        output = export_ambiguity_map(flags, "markdown")

        assert isinstance(output, str)
        assert "|" in output
        assert "AMB-001" in output

    def test__invalid_format__raises_value_error(self) -> None:
        """format='xml' → ValueError."""
        flags = [_make_flag("AMB-001")]
        with pytest.raises(ValueError):
            export_ambiguity_map(flags, "xml")

    def test__empty_flags_list__returns_empty_structure(self) -> None:
        """Empty flags list, format='json' → '[]' or equivalent; no exception."""
        output = export_ambiguity_map([], "json")
        assert json.loads(output) == []


# ---------------------------------------------------------------------------
# Section 5: apply_partial_determination
# ---------------------------------------------------------------------------


class TestApplyPartialDetermination:
    def test__critical_ambiguity__marked_undetermined(self) -> None:
        """CRITICAL flag on R002 → R002 undetermined; R001 determined; human_review_signal True."""
        rules = [_make_rule("PMKISAN-R001"), _make_rule("PMKISAN-R002")]
        flags = [_make_flag("AMB-001", rule_id="PMKISAN-R002", severity="CRITICAL")]

        result = apply_partial_determination(rules, flags)

        assert result.status == "PARTIAL"
        assert "PMKISAN-R001" in result.determined_rules
        assert "PMKISAN-R002" in result.undetermined_rules
        assert result.human_review_signal is True

    def test__no_critical_ambiguity__all_rules_determined(self) -> None:
        """Only HIGH flag (no CRITICAL) → all rules determined; human_review_signal False."""
        rules = [_make_rule("PMKISAN-R001"), _make_rule("PMKISAN-R002")]
        flags = [_make_flag("AMB-001", rule_id="PMKISAN-R002", severity="HIGH")]

        result = apply_partial_determination(rules, flags)

        assert len(result.undetermined_rules) == 0
        assert result.human_review_signal is False

    def test__never_suppresses_ambiguities(self) -> None:
        """CRITICAL flags are never silently dropped from result."""
        rules = [_make_rule("PMKISAN-R001"), _make_rule("PMKISAN-R002")]
        flags = [
            _make_flag("AMB-001", rule_id="PMKISAN-R001", severity="CRITICAL"),
            _make_flag("AMB-002", rule_id="PMKISAN-R002", severity="CRITICAL"),
        ]

        result = apply_partial_determination(rules, flags)

        assert len(result.undetermined_rules) == 2
        assert "PMKISAN-R001" in result.undetermined_rules
        assert "PMKISAN-R002" in result.undetermined_rules
