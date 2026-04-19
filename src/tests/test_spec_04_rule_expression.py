"""
Tests for spec_04_rule_expression.py (DSL)

Module: src/spec_04_rule_expression.py
Spec:   docs/part1-planning/tests/spec_04_rule_expression.md
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.exceptions import ValidationError  # type: ignore[import]
from src.schema import Operator, Rule, SourceAnchor  # type: ignore[import]
from src.rule_expression import (  # type: ignore[import]
    FIELD_NAMESPACE,
    build_atomic_rule,
    build_rule_group,
    render_dmn_row,
    render_dmn_table,
)


_VALID_ANCHOR = SourceAnchor(
    source_url="https://pmkisan.gov.in/guidelines.pdf",
    document_title="PM-KISAN Guidelines",
    source_quote="All landholding farmer families shall own cultivable land",
    section="3.2",
    notification_date="2023-11-15",
    language="en",
)


# ---------------------------------------------------------------------------
# Section 1: build_atomic_rule
# ---------------------------------------------------------------------------


class TestBuildAtomicRule:
    def test__all_required_args__returns_valid_rule(self) -> None:
        """All required args → valid Rule with correct operator and field."""
        rule = build_atomic_rule(
            rule_id="PMKISAN-R001",
            scheme_id="PMKISAN",
            field="applicant.land_ownership_status",
            operator=Operator.EQ,
            value=True,
            source_anchor=_VALID_ANCHOR,
            parse_run_id="RUN-001",
        )
        assert isinstance(rule, Rule)
        assert rule.operator == Operator.EQ
        assert rule.field == "applicant.land_ownership_status"
        assert rule.value is True

    def test__all_fourteen_operators__each_builds_successfully(self) -> None:
        """All 14 Operator values → valid Rule objects from build_atomic_rule."""
        test_cases: list[tuple[Operator, dict[str, Any]]] = [
            (Operator.EQ, {"value": True}),
            (Operator.NEQ, {"value": False}),
            (Operator.LT, {"value": 18}),
            (Operator.LTE, {"value": 40}),
            (Operator.GT, {"value": 0}),
            (Operator.GTE, {"value": 18}),
            (Operator.BETWEEN, {"value_min": 18.0, "value_max": 40.0}),
            (Operator.IN, {"values": ["SC", "ST"]}),
            (Operator.NOT_IN, {"values": ["GENERAL"]}),
            (Operator.NOT_MEMBER, {"values": ["EPFO", "NPS"]}),
            (Operator.IS_NULL, {}),
            (Operator.IS_NOT_NULL, {}),
            (Operator.CONTAINS, {"value": "rural"}),
            (Operator.MATCHES, {"value": r"^\d{12}$"}),
        ]
        for op, extra in test_cases:
            rule = build_atomic_rule(
                rule_id=f"TEST-{op.value}",
                scheme_id="TEST",
                field="applicant.land_ownership_status",
                operator=op,
                value=extra.get("value"),
                source_anchor=_VALID_ANCHOR,
                parse_run_id="RUN-001",
                **{k: v for k, v in extra.items() if k != "value"},
            )
            assert rule.operator == op

    def test__invalid_operator__raises_validation_error(self) -> None:
        """operator='LIKE' → ValidationError mentioning operator/LIKE."""
        with pytest.raises(ValidationError) as exc_info:
            build_atomic_rule(
                rule_id="TEST-R001",
                scheme_id="TEST",
                field="applicant.age",
                operator="LIKE",  # type: ignore[arg-type]
                value=None,
                source_anchor=_VALID_ANCHOR,
                parse_run_id="RUN-001",
            )
        msg = str(exc_info.value).lower()
        assert "operator" in msg or "like" in msg

    def test__field_not_in_namespace__raises_validation_error(self) -> None:
        """Field path not in FIELD_NAMESPACE → ValidationError mentioning 'field namespace'."""
        with pytest.raises(ValidationError) as exc_info:
            build_atomic_rule(
                rule_id="TEST-R001",
                scheme_id="TEST",
                field="applicant.shoe_size",
                operator=Operator.EQ,
                value=10,
                source_anchor=_VALID_ANCHOR,
                parse_run_id="RUN-001",
            )
        assert "namespace" in str(exc_info.value).lower() or "field" in str(exc_info.value).lower()

    def test__between_operator_with_min_max__sets_value_min_max(self) -> None:
        """BETWEEN with value_min=18, value_max=40 → rule.value_min/max set; value=None."""
        rule = build_atomic_rule(
            rule_id="PMSYM-R001",
            scheme_id="PMSYM",
            field="applicant.age",
            operator=Operator.BETWEEN,
            value=None,
            source_anchor=_VALID_ANCHOR,
            parse_run_id="RUN-001",
            value_min=18,
            value_max=40,
        )
        assert rule.value_min == 18
        assert rule.value_max == 40
        assert rule.value is None

    def test__in_operator_with_values__sets_values_list(self) -> None:
        """IN operator with values list → rule.values correct."""
        rule = build_atomic_rule(
            rule_id="AYUSHMAN-R001",
            scheme_id="AYUSHMAN",
            field="applicant.caste_category",
            operator=Operator.IN,
            value=None,
            source_anchor=_VALID_ANCHOR,
            parse_run_id="RUN-001",
            values=["SC", "ST", "OBC"],
        )
        assert rule.values == ["SC", "ST", "OBC"]

    def test__age_rule_pmsym__correct_display_text(self) -> None:
        """Age BETWEEN 18-40 → display_text contains '18', '40', 'age'; non-empty."""
        rule = build_atomic_rule(
            rule_id="PMSYM-R001",
            scheme_id="PMSYM",
            field="applicant.age",
            operator=Operator.BETWEEN,
            value=None,
            source_anchor=_VALID_ANCHOR,
            parse_run_id="RUN-001",
            value_min=18,
            value_max=40,
        )
        assert len(rule.display_text) > 0
        assert "18" in rule.display_text
        assert "40" in rule.display_text
        assert "age" in rule.display_text.lower()


# ---------------------------------------------------------------------------
# Section 2: build_rule_group
# ---------------------------------------------------------------------------


class TestBuildRuleGroup:
    def test__and_logic__returns_group(self) -> None:
        """AND group with 3 rule IDs → RuleGroup with correct logic."""
        from src.schema import RuleGroup  # type: ignore[import]

        group = build_rule_group(
            "PMKISAN-GROUP-A", "PMKISAN", "AND", ["PMKISAN-R001", "PMKISAN-R002", "PMKISAN-R003"]
        )
        assert isinstance(group, RuleGroup)
        assert group.logic == "AND"
        assert len(group.rule_ids) == 3

    def test__or_logic__returns_group(self) -> None:
        """OR group for Ayushman (at-least-one-of) → logic='OR'."""
        group = build_rule_group(
            "AYUSHMAN-GROUP-B", "AYUSHMAN", "OR", ["AYUSHMAN-R004", "AYUSHMAN-R005", "AYUSHMAN-R006"]
        )
        assert group.logic == "OR"
        assert len(group.rule_ids) == 3

    def test__invalid_logic__raises_validation_error(self) -> None:
        """logic='NAND' → ValidationError."""
        with pytest.raises(ValidationError):
            build_rule_group("GROUP-X", "PMKISAN", "NAND", ["R001"])

    def test__and_or_ambiguous__flags_ambiguous_logic(self) -> None:
        """AND_OR_AMBIGUOUS → valid group; used for ambiguous 'and/or' scheme language."""
        group = build_rule_group("NSAP-AMBIG", "NSAP", "AND_OR_AMBIGUOUS", ["NSAP-R001", "NSAP-R002"])
        assert group.logic == "AND_OR_AMBIGUOUS"

    def test__empty_rule_ids__raises_validation_error(self) -> None:
        """Empty rule_ids list → ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            build_rule_group("GROUP-EMPTY", "PMKISAN", "AND", [])
        msg = str(exc_info.value).lower()
        assert "rule_ids" in msg or "empty" in msg


# ---------------------------------------------------------------------------
# Section 3: render_dmn_row
# ---------------------------------------------------------------------------


class TestRenderDmnRow:
    def _get_rule(self) -> Rule:
        from src.schema import Rule  # type: ignore[import]

        return Rule(
            rule_id="PMKISAN-R001",
            scheme_id="PMKISAN",
            rule_type="eligibility",
            condition_type="land_ownership",
            field="applicant.land_ownership_status",
            operator="EQ",
            value=True,
            source_anchor=_VALID_ANCHOR,
            confidence=0.95,
            parse_run_id="RUN-001",
            display_text="Applicant must own cultivable agricultural land",
        )

    def test__valid_rule__returns_dict_with_required_columns(self) -> None:
        """Valid Rule → dict with Rule_ID, Condition, Source_Quote, Audit_Status keys."""
        rule = self._get_rule()
        row = render_dmn_row(rule)

        assert isinstance(row, dict)
        keys_lower = {k.lower() for k in row}
        assert any("rule" in k and "id" in k for k in keys_lower)
        assert any("condition" in k or "field" in k or "operator" in k for k in keys_lower)
        assert any("source" in k and "quote" in k for k in keys_lower)
        assert any("audit" in k for k in keys_lower)

    def test__is_deterministic__same_rule_produces_same_row(self) -> None:
        """Same rule object rendered twice → identical dict output."""
        rule = self._get_rule()
        row1 = render_dmn_row(rule)
        row2 = render_dmn_row(rule)
        assert row1 == row2

    def test__missing_required_fields__raises_validation_error(self) -> None:
        """Rule with empty display_text → ValidationError when rendering."""
        rule = self._get_rule()
        # Bypass Pydantic to inject empty display_text
        object.__setattr__(rule, "display_text", "")
        with pytest.raises((ValidationError, ValueError)):
            render_dmn_row(rule)

    def test__round_trip__rule_to_row_preserves_field_and_operator(self) -> None:
        """Row contains field path and operator representation matching the Rule."""
        rule = Rule(
            rule_id="PMSYM-R001",
            scheme_id="PMSYM",
            rule_type="eligibility",
            condition_type="age_range",
            field="applicant.age",
            operator="BETWEEN",
            value_min=18.0,
            value_max=40.0,
            source_anchor=_VALID_ANCHOR,
            confidence=0.98,
            parse_run_id="RUN-001",
            display_text="Must be between 18 and 40",
        )
        row = render_dmn_row(rule)
        row_str = str(row)
        assert "applicant.age" in row_str or "age" in row_str
        assert "BETWEEN" in row_str or "between" in row_str.lower()

    def test__all_operator_types__do_not_crash(self) -> None:
        """render_dmn_row handles all 14 operator types without raising."""
        test_cases: list[tuple[str, dict[str, Any]]] = [
            ("EQ", {"value": True}),
            ("NEQ", {"value": False}),
            ("LT", {"value": 18}),
            ("LTE", {"value": 40}),
            ("GT", {"value": 0}),
            ("GTE", {"value": 18}),
            ("BETWEEN", {"value_min": 18.0, "value_max": 40.0}),
            ("IN", {"values": ["SC", "ST"]}),
            ("NOT_IN", {"values": ["GENERAL"]}),
            ("NOT_MEMBER", {"values": ["EPFO", "NPS"]}),
            ("IS_NULL", {}),
            ("IS_NOT_NULL", {}),
            ("CONTAINS", {"value": "rural"}),
            ("MATCHES", {"value": r"^\d{12}$"}),
        ]
        for op, extra in test_cases:
            rule = Rule(
                rule_id=f"TEST-{op}",
                scheme_id="TEST",
                rule_type="eligibility",
                condition_type="test",
                field="applicant.land_ownership_status",
                operator=op,
                source_anchor=_VALID_ANCHOR,
                confidence=0.90,
                parse_run_id="RUN-001",
                display_text=f"Test rule for {op}",
                **extra,
            )
            row = render_dmn_row(rule)
            assert isinstance(row, dict)


# ---------------------------------------------------------------------------
# Section 4: render_dmn_table
# ---------------------------------------------------------------------------


class TestRenderDmnTable:
    def _make_rule(self, rule_id: str) -> Rule:
        return Rule(
            rule_id=rule_id,
            scheme_id="PMKISAN",
            rule_type="eligibility",
            condition_type="land_ownership",
            field="applicant.land_ownership_status",
            operator="EQ",
            value=True,
            source_anchor=_VALID_ANCHOR,
            confidence=0.95,
            parse_run_id="RUN-001",
            display_text=f"Rule {rule_id} display text",
        )

    def test__multiple_rules__returns_markdown_string(self) -> None:
        """3 valid rules → non-empty Markdown string containing all rule IDs."""
        rules = [self._make_rule(r) for r in ["PMKISAN-R001", "PMKISAN-R002", "PMKISAN-R003"]]
        output = render_dmn_table(rules)

        assert isinstance(output, str)
        assert len(output) > 0
        assert "PMKISAN-R001" in output
        assert "PMKISAN-R002" in output
        assert "PMKISAN-R003" in output
        assert "|" in output  # Markdown table

    def test__empty_rules_list__returns_empty_or_header_only(self) -> None:
        """Empty rules list → non-raising string output."""
        output = render_dmn_table([])
        assert isinstance(output, str)

    def test__is_human_readable__contains_display_text(self) -> None:
        """Output contains the display_text from the rule."""
        rule = self._make_rule("PMKISAN-R001")
        output = render_dmn_table([rule])
        assert rule.display_text in output


# ---------------------------------------------------------------------------
# Section 5: FIELD_NAMESPACE
# ---------------------------------------------------------------------------


class TestFieldNamespace:
    def test__is_non_empty_dict__has_minimum_50_entries(self) -> None:
        """FIELD_NAMESPACE is a dict with ≥50 canonical field paths."""
        assert isinstance(FIELD_NAMESPACE, dict)
        assert len(FIELD_NAMESPACE) >= 50

    def test__contains_all_anchor_scheme_fields__required_paths_present(self) -> None:
        """All required field paths for anchor schemes are present in namespace."""
        required = [
            "applicant.age",
            "applicant.caste_category",
            "household.income_annual",
            "household.land_acres",
            "applicant.land_ownership_status",
            "enrollment.epfo",
            "enrollment.nps",
            "enrollment.esic",
            "applicant.gender",
        ]
        for field in required:
            assert field in FIELD_NAMESPACE, f"Missing required field: {field}"

    def test__values_are_human_labels__not_empty(self) -> None:
        """All FIELD_NAMESPACE values are non-empty strings (human-readable labels)."""
        assert all(isinstance(v, str) and len(v) > 0 for v in FIELD_NAMESPACE.values())
