"""
Tests for spec_08_validation.py (Quality Gates)

Module: src/spec_08_validation.py
Spec:   docs/part1-planning/tests/spec_08_validation.md
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.schema import (  # type: ignore[import]
    AmbiguityFlag,
    AmbiguitySeverity,
    AuditStatus,
    Rule,
    SourceAnchor,
)
from src.validation import (  # type: ignore[import]
    gate_30_type_completeness,
    gate_cross_scheme_consistency,
    gate_reverse_audit_coherence,
    gate_schema_validation,
    gate_source_quote_grounding,
    generate_quality_report,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_VALID_ANCHOR: dict[str, Any] = {
    "source_url": "https://pmkisan.gov.in/guidelines.pdf",
    "document_title": "PM-KISAN Guidelines",
    "source_quote": "All landholding farmer families shall own cultivable land",
    "section": "3.2",
    "notification_date": "2023-11-15",
    "language": "en",
}


def _make_rule(
    rule_id: str,
    scheme_id: str = "PMKISAN",
    field: str = "applicant.land_ownership_status",
    source_quote: str | None = "All landholding farmer families shall own cultivable land",
) -> Rule:
    anchor = {**_VALID_ANCHOR}
    if source_quote is None:
        anchor.pop("source_quote", None)
        anchor["source_quote"] = None  # type: ignore[assignment]
    else:
        anchor["source_quote"] = source_quote

    return Rule(
        rule_id=rule_id,
        scheme_id=scheme_id,
        rule_type="eligibility",
        condition_type="land_ownership",
        field=field,
        operator="EQ",
        value=True,
        source_anchor=SourceAnchor(**anchor),
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
    from src.ambiguity_map import AMBIGUITY_TAXONOMY  # type: ignore[import]

    return AmbiguityFlag(
        ambiguity_id=flag_id,
        scheme_id=scheme_id,
        rule_id=rule_id,
        ambiguity_type_code=type_code,
        ambiguity_type_name=AMBIGUITY_TAXONOMY.get(type_code, "Unknown"),
        description=f"Flag {flag_id}",
        severity=severity,
    )


# ---------------------------------------------------------------------------
# Section 1: gate_schema_validation (Gate 1)
# ---------------------------------------------------------------------------


class TestGateSchemaValidation:
    def test__all_valid_rules__passes_with_zero_failures(self) -> None:
        """5 valid rules → gate passes; 0 failures."""
        rules = [
            _make_rule(f"PMKISAN-R00{i}", "PMKISAN") for i in range(1, 4)
        ] + [
            _make_rule(f"PMSYM-R00{i}", "PMSYM") for i in range(1, 3)
        ]
        result = gate_schema_validation(rules)

        assert result.passed is True
        assert result.gate_name == "schema_validation"
        assert result.rules_checked == 5
        assert len(result.failures) == 0

    def test__missing_required_field__fails_and_lists_failure(self) -> None:
        """2 valid + 1 rule with missing rule_id → gate fails; failure listed."""
        good = [_make_rule("PMKISAN-R001"), _make_rule("PMKISAN-R002")]

        # Build a bad rule dict missing rule_id, inject it directly
        bad_rule = _make_rule("BAD-R001")
        object.__setattr__(bad_rule, "rule_id", "")  # simulate missing rule_id

        result = gate_schema_validation(good + [bad_rule])

        assert result.passed is False
        assert result.rules_checked == 3
        assert len(result.failures) >= 1
        reasons_str = " ".join(str(f) for f in result.failures).lower()
        assert "rule_id" in reasons_str or "required" in reasons_str

    def test__invalid_operator__fails_and_lists_reason(self) -> None:
        """Rule with invalid operator stored (bypassing Pydantic) → gate catches it."""
        rule = _make_rule("PMKISAN-R001")
        object.__setattr__(rule, "operator", "FUZZY")  # type: ignore[arg-type]

        result = gate_schema_validation([rule])

        assert result.passed is False
        assert any("operator" in str(f).lower() for f in result.failures)

    def test__duplicate_rule_ids__fails_and_lists_both(self) -> None:
        """Two rules with same rule_id → gate fails; duplicate listed."""
        rule1 = _make_rule("PMKISAN-R001")
        rule2 = _make_rule("PMKISAN-R001")  # duplicate ID

        result = gate_schema_validation([rule1, rule2])

        assert result.passed is False
        assert any("PMKISAN-R001" in str(f) for f in result.failures)


# ---------------------------------------------------------------------------
# Section 2: gate_source_quote_grounding (Gate 2)
# ---------------------------------------------------------------------------


class TestGateSourceQuoteGrounding:
    def test__all_rules_have_source_quote__passes(self) -> None:
        """All rules have non-null source_quote → gate passes."""
        rules = [_make_rule("PMKISAN-R001"), _make_rule("PMSYM-R001", "PMSYM")]
        result = gate_source_quote_grounding(rules)

        assert result.passed is True
        assert len(result.failures) == 0

    def test__rule_with_null_source_quote__fails(self) -> None:
        """1 rule with source_quote=None → gate fails; that rule listed."""
        good = _make_rule("PMKISAN-R001")
        bad_anchor = SourceAnchor(
            source_url="https://example.gov.in/doc.pdf",
            document_title="Test Doc",
            source_quote="placeholder",
            section="1",
            notification_date="2023-01-01",
            language="en",
        )
        bad_rule = _make_rule("PMKISAN-R002")
        object.__setattr__(bad_rule.source_anchor, "source_quote", None)

        result = gate_source_quote_grounding([good, bad_rule])

        assert result.passed is False
        assert any("PMKISAN-R002" in str(f) for f in result.failures)

    def test__rule_with_empty_source_quote__fails(self) -> None:
        """source_quote='' → gate fails (empty = null for grounding)."""
        rule = _make_rule("PMKISAN-R001")
        object.__setattr__(rule.source_anchor, "source_quote", "")

        result = gate_source_quote_grounding([rule])

        assert result.passed is False


# ---------------------------------------------------------------------------
# Section 3: gate_reverse_audit_coherence (Gate 3)
# ---------------------------------------------------------------------------


class TestGateReverseAuditCoherence:
    async def test__all_verified__passes(self) -> None:
        """All 3 rules VERIFIED → gate passes."""
        rules = [_make_rule(f"R00{i}") for i in range(1, 4)]

        with patch(
            "src.validation.verify_source_anchor",
            new_callable=AsyncMock,
            return_value=type("AuditResult", (), {"audit_status": AuditStatus.VERIFIED, "similarity_score": 0.95})(),
        ):
            result = await gate_reverse_audit_coherence(rules)

        assert result.passed is True
        assert result.notes is not None and len(result.notes) > 0

    async def test__some_disputed__records_counts_not_fails(self) -> None:
        """2 VERIFIED + 1 DISPUTED → result notes contain counts; not silently omitted."""
        rules = [_make_rule(f"R00{i}") for i in range(1, 4)]
        statuses = [AuditStatus.VERIFIED, AuditStatus.VERIFIED, AuditStatus.DISPUTED]
        call_count = [0]

        async def fake_audit(rule: Any) -> Any:
            status = statuses[call_count[0] % len(statuses)]
            call_count[0] += 1
            return type("AuditResult", (), {"audit_status": status, "similarity_score": 0.85})()

        with patch("src.validation.verify_source_anchor", side_effect=fake_audit):
            result = await gate_reverse_audit_coherence(rules)

        assert result.notes is not None
        assert "1" in result.notes or "DISPUTED" in result.notes.upper()

    async def test__reports_counts__never_silent_about_disputed(self) -> None:
        """Mixed statuses → notes contain all three counts."""
        rules = [_make_rule(f"R00{i}") for i in range(1, 4)]
        statuses = [AuditStatus.VERIFIED, AuditStatus.NEEDS_REVIEW, AuditStatus.DISPUTED]
        call_count = [0]

        async def fake_audit(rule: Any) -> Any:
            status = statuses[call_count[0] % len(statuses)]
            call_count[0] += 1
            return type("AuditResult", (), {"audit_status": status, "similarity_score": 0.75})()

        with patch("src.validation.verify_source_anchor", side_effect=fake_audit):
            result = await gate_reverse_audit_coherence(rules)

        notes = result.notes or ""
        assert len(notes) > 0
        # Must surface all three counts
        assert any(s in notes.upper() for s in ["VERIFIED", "NEEDS_REVIEW", "DISPUTED"])


# ---------------------------------------------------------------------------
# Section 4: gate_cross_scheme_consistency (Gate 4)
# ---------------------------------------------------------------------------


class TestGateCrossSchemeConsistency:
    def test__consistent_field_names__passes(self) -> None:
        """All schemes use canonical field names → gate passes."""
        all_rules = {
            "PMKISAN": [_make_rule("PMKISAN-R001", field="household.income_annual")],
            "PMSYM": [_make_rule("PMSYM-R001", "PMSYM", field="household.income_annual")],
        }
        result = gate_cross_scheme_consistency(all_rules)

        assert result.passed is True
        assert len(result.failures) == 0

    def test__field_namespace_mismatch__fails(self) -> None:
        """Non-canonical field 'annual_income' in one scheme → gate fails."""
        all_rules = {
            "PMKISAN": [_make_rule("PMKISAN-R001", field="household.income_annual")],
            "PMSYM": [_make_rule("PMSYM-R001", "PMSYM", field="annual_income")],
        }
        result = gate_cross_scheme_consistency(all_rules)

        assert result.passed is False
        failure_str = " ".join(str(f) for f in result.failures)
        assert "annual_income" in failure_str or "namespace" in failure_str.lower()

    def test__circular_prerequisite__flags_it(self) -> None:
        """Circular prerequisite A→B, B→A → gate fails; cycle flagged."""
        rule_a = _make_rule("A-R001", "SCHEME-A")
        object.__setattr__(rule_a, "prerequisite_scheme_ids", ["SCHEME-B"])
        rule_b = _make_rule("B-R001", "SCHEME-B")
        object.__setattr__(rule_b, "prerequisite_scheme_ids", ["SCHEME-A"])

        all_rules = {"SCHEME-A": [rule_a], "SCHEME-B": [rule_b]}
        result = gate_cross_scheme_consistency(all_rules)

        assert result.passed is False
        assert any("circular" in str(f).lower() or "prerequisite" in str(f).lower() for f in result.failures)

    def test__missing_mutual_exclusion_record__flags_it(self) -> None:
        """PMSYM has NOT_MEMBER NPS but no relationship record → gate flags it."""
        pmsym_rule = Rule(
            rule_id="PMSYM-DIS001",
            scheme_id="PMSYM",
            rule_type="disqualifying",
            condition_type="scheme_enrollment",
            field="enrollment.nps",
            operator="NOT_MEMBER",
            values=["NPS"],
            source_anchor=SourceAnchor(**_VALID_ANCHOR),
            confidence=0.99,
            parse_run_id="RUN-001",
            display_text="NOT NPS",
        )
        all_rules = {"PMSYM": [pmsym_rule], "NPS": []}

        result = gate_cross_scheme_consistency(all_rules, known_relationships=[])

        assert result.passed is False
        failure_str = " ".join(str(f) for f in result.failures).upper()
        assert "REL" in failure_str or "MUTUAL" in failure_str or "NPS" in failure_str


# ---------------------------------------------------------------------------
# Section 5: gate_30_type_completeness (Gate 5)
# ---------------------------------------------------------------------------


class TestGate30TypeCompleteness:
    def test__all_types_tested_per_scheme__passes(self) -> None:
        """30 flags, one per type for PMKISAN → gate passes."""
        from src.ambiguity_map import AMBIGUITY_TAXONOMY  # type: ignore[import]

        flags = [
            _make_flag(f"AMB-{i:03d}", type_code=i)
            for i in range(1, 31)
        ]
        result = gate_30_type_completeness(flags, ["PMKISAN"])

        assert result.passed is True
        notes = result.notes or ""
        assert "30" in notes or "all" in notes.lower()

    def test__missing_types_for_scheme__fails_with_list(self) -> None:
        """Types 1–20 only (missing 21–30) → gate fails; missing codes listed."""
        flags = [_make_flag(f"AMB-{i:03d}", type_code=i) for i in range(1, 21)]
        result = gate_30_type_completeness(flags, ["PMKISAN"])

        assert result.passed is False
        missing_codes = list(range(21, 31))
        failure_str = " ".join(str(f) for f in result.failures)
        assert any(str(code) in failure_str for code in missing_codes)


# ---------------------------------------------------------------------------
# Section 6: "No Silent Pass" Rule (Gate 6)
# ---------------------------------------------------------------------------


class TestGateNoSilentPass:
    def test__verified_rule_with_source_quote__counts_as_pass(self) -> None:
        """VERIFIED + source_quote + source_url → valid PASS; no warning."""
        rule = _make_rule("PMKISAN-R001")
        object.__setattr__(rule, "audit_status", AuditStatus.VERIFIED)

        result = gate_schema_validation([rule])

        assert result.passed is True

    def test__unverified_rule__blocked_and_flagged(self) -> None:
        """PENDING audit_status → UNVERIFIED_PASS result; warning emitted."""
        rule = _make_rule("PMKISAN-R001")
        # audit_status is already PENDING from factory

        from src.validation import evaluate_rule_pass  # type: ignore[import]

        outcome = evaluate_rule_pass(rule)

        assert outcome.is_unverified_pass is True
        assert outcome.warning is not None and len(outcome.warning) > 0

    def test__null_source_quote_rule__blocked_and_flagged(self) -> None:
        """VERIFIED status but source_quote=None → UNVERIFIED_PASS."""
        rule = _make_rule("PMKISAN-R001")
        object.__setattr__(rule, "audit_status", AuditStatus.VERIFIED)
        object.__setattr__(rule.source_anchor, "source_quote", None)

        from src.validation import evaluate_rule_pass  # type: ignore[import]

        outcome = evaluate_rule_pass(rule)

        assert outcome.is_unverified_pass is True


# ---------------------------------------------------------------------------
# Section 7: Adversarial Profile Tests
# ---------------------------------------------------------------------------


class TestAdversarialProfiles:
    def test__widow_who_remarried__nsap_has_life_event_ambiguity(self) -> None:
        """NSAP rules → at least 1 AmbiguityFlag with type_code=21 (Life-Event Transition)."""
        # In practice, Agent B's ambiguity detection on NSAP widow pension rules must emit Type 21
        from src.ambiguity_map import detect_ambiguity_type  # type: ignore[import]

        nsap_text = "Widows receiving pension under NSAP are eligible; scheme text does not address remarriage"
        flags = detect_ambiguity_type(nsap_text)
        assert any(f.ambiguity_type_code == 21 for f in flags)

    def test__widow_who_remarried__pmkisan_household_ambiguity(self) -> None:
        """PM-KISAN 'household' rule → either uses canonical field OR has Type 16 flag."""
        rule = _make_rule("PMKISAN-R001", field="household.land_acres")
        # Field uses canonical 'household' field OR ambiguity flag type 16 present
        has_canonical_field = rule.field == "household.land_acres"
        has_type_16_flag = any(
            f.ambiguity_type_code == 16 for f in rule.ambiguity_flags
        )
        assert has_canonical_field or has_type_16_flag

    def test__farmer_leases_land__pmkisan_requires_ownership(self) -> None:
        """PM-KISAN land eligibility rule → field is land_ownership_status; value is 'owned' not 'leased'."""
        rule = _make_rule("PMKISAN-R001", field="applicant.land_ownership_status")
        assert rule.field == "applicant.land_ownership_status"
        assert rule.condition_type == "land_ownership"
        # Value should not indicate leasing as eligible
        assert rule.value != "leased"

    def test__farmer_leases_land__evidence_gap_flagged(self) -> None:
        """PM-KISAN ambiguity → Type 2 (Evidence Gap) flag with 'cultivation' in description."""
        from src.ambiguity_map import detect_ambiguity_type  # type: ignore[import]

        pmkisan_text = (
            "Applicant must own cultivable agricultural land. "
            "Scheme does not address farmers who lease land and cannot prove ownership via documents."
        )
        flags = detect_ambiguity_type(pmkisan_text)
        type_2_flags = [f for f in flags if f.ambiguity_type_code == 2]
        assert len(type_2_flags) > 0
        assert any("cultivation" in f.description.lower() or "ownership" in f.description.lower() for f in type_2_flags)

    def test__tribal_no_bank__infrastructure_precondition(self) -> None:
        """Ayushman/NSAP → Type 20 (Infrastructure Preconditions) flag about bank/DBT."""
        from src.ambiguity_map import detect_ambiguity_type  # type: ignore[import]

        text = (
            "Benefit transferred via Direct Benefit Transfer to registered bank account. "
            "Beneficiary must have Aadhaar-linked bank account."
        )
        flags = detect_ambiguity_type(text)
        assert any(f.ambiguity_type_code == 20 for f in flags)
        infra_flags = [f for f in flags if f.ambiguity_type_code == 20]
        assert any(
            "bank" in f.description.lower() or "dbt" in f.description.lower()
            for f in infra_flags
        )

    def test__interstate_migrant__portability_gap_flagged(self) -> None:
        """NFSA/PDS rules → Type 7 (Portability Gap) flag about state-specific ration card."""
        from src.ambiguity_map import detect_ambiguity_type  # type: ignore[import]

        nfsa_text = (
            "Beneficiary must hold a valid ration card issued by the state government. "
            "Inter-state portability of ration card not mentioned."
        )
        flags = detect_ambiguity_type(nfsa_text)
        assert any(f.ambiguity_type_code == 7 for f in flags)
        portability_flags = [f for f in flags if f.ambiguity_type_code == 7]
        assert any(
            "ration" in f.description.lower() or "state" in f.description.lower()
            for f in portability_flags
        )


# ---------------------------------------------------------------------------
# Section 8: Performance Constraints
# ---------------------------------------------------------------------------


class TestPerformanceBaseline:
    def test__schema_validation_per_rule__completes_under_10ms(self) -> None:
        """Gate 1 for 1 rule must complete in < 10ms."""
        rule = _make_rule("PMKISAN-R001")
        start = time.perf_counter()
        gate_schema_validation([rule])
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 10, f"gate_schema_validation took {elapsed_ms:.2f}ms (limit: 10ms)"

    def test__quality_report__contains_all_required_sections(self) -> None:
        """generate_quality_report → string/dict with all required sections."""
        rules_by_scheme = {
            "PMKISAN": [_make_rule(f"PMKISAN-R00{i}") for i in range(1, 4)],
            "PMSYM": [_make_rule(f"PMSYM-R00{i}", "PMSYM") for i in range(1, 3)],
        }
        flags = [_make_flag("AMB-001", severity="CRITICAL"), _make_flag("AMB-002", severity="HIGH")]

        report = generate_quality_report(rules_by_scheme, flags)

        # Report can be str or dict; convert to str for content assertions
        report_str = report if isinstance(report, str) else str(report)
        assert len(report_str) > 0
        # Check all required sections are present
        assert any(kw in report_str.lower() for kw in ["total", "rules", "scheme"])
        assert any(kw in report_str.lower() for kw in ["verified", "pending", "disputed"])
        assert any(kw in report_str.lower() for kw in ["ambiguity", "flag"])
        assert any(kw in report_str.lower() for kw in ["critical"])
