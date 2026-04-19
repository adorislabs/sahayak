"""
Tests for spec_03_schema.py (Pydantic Models)

Module: src/spec_03_schema.py
Spec:   docs/part1-planning/tests/spec_03_schema.md

All tests are synchronous — Pydantic validation runs in-process.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from src.schema import (  # type: ignore[import]
    AmbiguityFlag,
    AmbiguitySeverity,
    AuditStatus,
    Operator,
    Rule,
    RuleGroup,
    Scheme,
    SchemeRelationship,
    SchemeStatus,
    SourceAnchor,
)


# ---------------------------------------------------------------------------
# Section 1: SourceAnchor Model
# ---------------------------------------------------------------------------


class TestSourceAnchor:
    def test__all_required_fields__instantiates_successfully(self) -> None:
        """All required fields present → model instantiates; optional fields default None."""
        data = {
            "source_url": "https://pmkisan.gov.in/guidelines.pdf",
            "document_title": "PM-KISAN Operational Guidelines 2023",
            "source_quote": "All landholding farmer families...",
            "section": "3.2 Eligibility Criteria",
            "notification_date": "2023-11-15",
            "language": "en",
        }
        anchor = SourceAnchor(**data)

        assert anchor.source_url == "https://pmkisan.gov.in/guidelines.pdf"
        assert anchor.language == "en"
        assert anchor.page_number is None  # optional defaults to None

    def test__missing_source_url__raises_validation_error(self) -> None:
        """Missing source_url → pydantic.ValidationError."""
        data = {
            "document_title": "some doc",
            "source_quote": "some quote",
            "section": "3.2",
            "notification_date": "2023-01-01",
            "language": "en",
        }
        with pytest.raises(PydanticValidationError):
            SourceAnchor(**data)

    def test__missing_source_quote__raises_validation_error(self) -> None:
        """Missing source_quote → pydantic.ValidationError."""
        data = {
            "source_url": "https://pmkisan.gov.in/guidelines.pdf",
            "document_title": "PM-KISAN Guidelines",
            "section": "3.2",
            "notification_date": "2023-01-01",
            "language": "en",
        }
        with pytest.raises(PydanticValidationError):
            SourceAnchor(**data)

    def test__optional_fields_default_to_none__instantiates_successfully(self) -> None:
        """Minimal required-only data → all optional fields default to None."""
        data = {
            "source_url": "https://pmkisan.gov.in/guidelines.pdf",
            "document_title": "PM-KISAN Guidelines",
            "source_quote": "Farmer families owning land are eligible",
            "section": "3.2",
            "notification_date": "2023-01-01",
            "language": "en",
        }
        anchor = SourceAnchor(**data)

        assert anchor.page_number is None
        assert anchor.clause is None
        assert anchor.gazette_ref is None
        assert anchor.alternate_language_ref is None


# ---------------------------------------------------------------------------
# Section 2: AmbiguityFlag Model
# ---------------------------------------------------------------------------


class TestAmbiguityFlag:
    def test__valid_data__instantiates_successfully(self) -> None:
        """All fields valid → model instantiates with correct defaults."""
        data = {
            "ambiguity_id": "AMB-001",
            "scheme_id": "PMKISAN",
            "ambiguity_type_code": 1,
            "ambiguity_type_name": "Semantic Vagueness",
            "description": "'resident' not defined in scheme text",
            "severity": "HIGH",
        }
        flag = AmbiguityFlag(**data)

        assert flag.ambiguity_id == "AMB-001"
        assert flag.severity == AmbiguitySeverity.HIGH
        assert flag.resolution_status == "OPEN"
        assert flag.rule_id is None

    def test__invalid_severity__raises_validation_error(self) -> None:
        """severity='EXTREME' (not in enum) → pydantic.ValidationError."""
        data = {
            "ambiguity_id": "AMB-002",
            "scheme_id": "PMKISAN",
            "ambiguity_type_code": 1,
            "ambiguity_type_name": "Semantic Vagueness",
            "description": "some description",
            "severity": "EXTREME",
        }
        with pytest.raises(PydanticValidationError):
            AmbiguityFlag(**data)

    def test__ambiguity_type_code_out_of_range__rejected(self) -> None:
        """ambiguity_type_code=31 → ValidationError (31 is outside 1–30 range)."""
        data = {
            "ambiguity_id": "AMB-003",
            "scheme_id": "PMKISAN",
            "ambiguity_type_code": 31,
            "ambiguity_type_name": "Out of Range",
            "description": "code is 31",
            "severity": "LOW",
        }
        with pytest.raises((PydanticValidationError, ValueError)):
            AmbiguityFlag(**data)

    def test__all_severity_values__round_trip_correctly(self) -> None:
        """All 4 severity values survive model_dump() → reconstruct round-trip."""
        for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            data = {
                "ambiguity_id": f"AMB-{severity}",
                "scheme_id": "TEST",
                "ambiguity_type_code": 1,
                "ambiguity_type_name": "Test",
                "description": "desc",
                "severity": severity,
            }
            flag = AmbiguityFlag(**data)
            dumped = flag.model_dump()
            rebuilt = AmbiguityFlag(**dumped)
            assert rebuilt.severity == flag.severity


# ---------------------------------------------------------------------------
# Section 3: Rule Model
# ---------------------------------------------------------------------------

_VALID_ANCHOR: dict[str, Any] = {
    "source_url": "https://pmkisan.gov.in/guidelines.pdf",
    "document_title": "PM-KISAN Operational Guidelines 2023",
    "source_quote": "All landholding farmer families shall own cultivable land",
    "section": "3.2 Eligibility Criteria",
    "notification_date": "2023-11-15",
    "language": "en",
}

_BASE_RULE: dict[str, Any] = {
    "rule_id": "PMKISAN-R001",
    "scheme_id": "PMKISAN",
    "rule_type": "eligibility",
    "condition_type": "land_ownership",
    "field": "applicant.land_ownership_status",
    "operator": "EQ",
    "value": True,
    "source_anchor": _VALID_ANCHOR,
    "confidence": 0.95,
    "parse_run_id": "RUN-001",
    "display_text": "Applicant must own cultivable agricultural land",
}


class TestRuleModel:
    def test__minimal_valid_rule__instantiates_successfully(self) -> None:
        """All required fields → correct defaults (PENDING, 1.0.0, empty lists)."""
        rule = Rule(**_BASE_RULE)

        assert rule.rule_id == "PMKISAN-R001"
        assert rule.operator == Operator.EQ
        assert rule.audit_status == AuditStatus.PENDING
        assert rule.version == "1.0.0"
        assert rule.ambiguity_flags == []
        assert rule.prerequisite_scheme_ids == []

    def test__all_fourteen_operators__each_instantiates_successfully(self) -> None:
        """All 14 Operator enum values → valid Rule objects."""
        operators_and_values: list[tuple[str, dict[str, Any]]] = [
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
        for op, extra in operators_and_values:
            rule_dict = {**_BASE_RULE, "operator": op, **extra}
            rule = Rule(**rule_dict)
            assert rule.operator == Operator(op)

    def test__invalid_operator__raises_validation_error(self) -> None:
        """operator='REGEX' (not in vocabulary) → pydantic.ValidationError."""
        rule_dict = {**_BASE_RULE, "operator": "REGEX"}
        with pytest.raises(PydanticValidationError):
            Rule(**rule_dict)

    def test__between_operator_without_min_max__raises_validation_error(self) -> None:
        """BETWEEN with value_min=None and value_max=None → ValidationError."""
        rule_dict = {
            **_BASE_RULE,
            "operator": "BETWEEN",
            "value_min": None,
            "value_max": None,
        }
        with pytest.raises((PydanticValidationError, ValueError)):
            Rule(**rule_dict)

    def test__confidence_exactly_zero__instantiates_successfully(self) -> None:
        """confidence=0.0 (failed parse) → storable, no error."""
        rule = Rule(**{**_BASE_RULE, "confidence": 0.0})
        assert rule.confidence == 0.0

    def test__confidence_exactly_one__instantiates_successfully(self) -> None:
        """confidence=1.0 → valid maximum boundary."""
        rule = Rule(**{**_BASE_RULE, "confidence": 1.0})
        assert rule.confidence == 1.0

    def test__confidence_above_one__raises_validation_error(self) -> None:
        """confidence=1.01 → pydantic.ValidationError."""
        with pytest.raises(PydanticValidationError):
            Rule(**{**_BASE_RULE, "confidence": 1.01})

    def test__missing_source_anchor__raises_validation_error(self) -> None:
        """No source_anchor field → pydantic.ValidationError."""
        rule_dict = {k: v for k, v in _BASE_RULE.items() if k != "source_anchor"}
        with pytest.raises(PydanticValidationError):
            Rule(**rule_dict)

    def test__invalid_audit_status__raises_validation_error(self) -> None:
        """audit_status='PENDING_HUMAN' → pydantic.ValidationError."""
        with pytest.raises(PydanticValidationError):
            Rule(**{**_BASE_RULE, "audit_status": "PENDING_HUMAN"})

    def test__model_dump_round_trip__preserves_all_fields(self) -> None:
        """Rule → model_dump() → Rule(**dumped) must be lossless."""
        rule = Rule(**_BASE_RULE)
        dumped = rule.model_dump()
        rebuilt = Rule(**dumped)

        assert rebuilt.rule_id == rule.rule_id
        assert rebuilt.operator == rule.operator
        assert rebuilt.source_anchor.source_url == rule.source_anchor.source_url


# ---------------------------------------------------------------------------
# Section 4: RuleGroup Model
# ---------------------------------------------------------------------------


class TestRuleGroupModel:
    def test__and_logic__instantiates_successfully(self) -> None:
        """AND group with 2 rule IDs → valid RuleGroup."""
        data = {
            "rule_group_id": "PMKISAN-GROUP-A",
            "scheme_id": "PMKISAN",
            "logic": "AND",
            "rule_ids": ["PMKISAN-R001", "PMKISAN-R002"],
            "display_text": "Must satisfy ALL conditions",
        }
        group = RuleGroup(**data)
        assert group.logic == "AND"
        assert group.rule_ids == ["PMKISAN-R001", "PMKISAN-R002"]

    def test__invalid_logic__raises_validation_error(self) -> None:
        """logic='XOR' → ValidationError."""
        with pytest.raises((PydanticValidationError, ValueError)):
            RuleGroup(
                rule_group_id="G-X",
                scheme_id="PMKISAN",
                logic="XOR",
                rule_ids=["R001"],
                display_text="test",
            )

    def test__and_or_ambiguous__is_valid_logic_value(self) -> None:
        """AND_OR_AMBIGUOUS is an accepted logic value."""
        group = RuleGroup(
            rule_group_id="NSAP-AMBIG",
            scheme_id="NSAP",
            logic="AND_OR_AMBIGUOUS",
            rule_ids=["NSAP-R001", "NSAP-R002"],
            display_text="AND or OR unclear",
        )
        assert group.logic == "AND_OR_AMBIGUOUS"


# ---------------------------------------------------------------------------
# Section 5: Scheme Model
# ---------------------------------------------------------------------------


class TestSchemeModel:
    def test__valid_central_scheme__instantiates_successfully(self) -> None:
        """Valid central scheme → correct defaults for state_scope."""
        data = {
            "scheme_id": "PMKISAN",
            "scheme_name": "Pradhan Mantri Kisan Samman Nidhi",
            "short_name": "PM-Kisan",
            "ministry": "Ministry of Agriculture and Farmers Welfare",
            "status": "active",
            "version": "2.1.0",
            "last_verified": "2026-01-15",
            "source_urls": ["https://pmkisan.gov.in/guidelines.pdf"],
            "created_at": "2019-02-24",
            "updated_at": "2026-01-15",
        }
        scheme = Scheme(**data)

        assert scheme.scheme_id == "PMKISAN"
        assert scheme.status == SchemeStatus.ACTIVE
        assert scheme.state_scope == "central"

    def test__invalid_status__raises_validation_error(self) -> None:
        """status='archived' (not in active/dormant/discontinued) → pydantic.ValidationError."""
        data = {
            "scheme_id": "PMKISAN",
            "scheme_name": "Test",
            "short_name": "Test",
            "ministry": "Test Ministry",
            "status": "archived",
            "version": "1.0.0",
            "last_verified": "2026-01-01",
            "source_urls": ["https://example.gov.in"],
            "created_at": "2020-01-01",
            "updated_at": "2026-01-01",
        }
        with pytest.raises(PydanticValidationError):
            Scheme(**data)

    def test__state_specific_scope__stores_state_code(self) -> None:
        """state_scope='MH' → stored as-is (Maharashtra state scheme)."""
        data = {
            "scheme_id": "MH-SCHEME-001",
            "scheme_name": "Maharashtra Scheme",
            "short_name": "MH-S",
            "ministry": "Maharashtra Government",
            "state_scope": "MH",
            "status": "active",
            "version": "1.0.0",
            "last_verified": "2026-01-01",
            "source_urls": ["https://mh.gov.in/scheme"],
            "created_at": "2020-01-01",
            "updated_at": "2026-01-01",
        }
        scheme = Scheme(**data)
        assert scheme.state_scope == "MH"


# ---------------------------------------------------------------------------
# Section 6: SchemeRelationship Model
# ---------------------------------------------------------------------------


class TestSchemeRelationshipModel:
    def test__high_confidence__display_to_user_true(self) -> None:
        """confidence=0.95 and display_to_user=True → stored correctly."""
        data = {
            "relationship_id": "REL-001",
            "scheme_a": "PMSYM",
            "scheme_b": "NPS",
            "relationship_type": "MUTUAL_EXCLUSION",
            "confidence": 0.95,
            "display_to_user": True,
            "source_evidence": "PM-SYM guidelines §4 Exclusion Criteria",
        }
        rel = SchemeRelationship(**data)
        assert rel.display_to_user is True
        assert rel.confidence == 0.95

    def test__low_confidence_below_60__display_to_user_false(self) -> None:
        """confidence < 0.60 → display_to_user MUST be False (enforced at creation or via validator)."""
        data = {
            "relationship_id": "REL-002",
            "scheme_a": "NSAP",
            "scheme_b": "PMSYM",
            "relationship_type": "COMPLEMENTARY",
            "confidence": 0.55,
            "display_to_user": True,  # Attempting to set True with low confidence
            "source_evidence": "Inferred from population overlap",
        }
        # Pydantic validator or factory must enforce display_to_user=False
        rel = SchemeRelationship(**data)
        assert rel.display_to_user is False
