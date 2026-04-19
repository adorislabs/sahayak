"""
Tests for spec_02_parsing_agent.py

Module: src/spec_02_parsing_agent.py
Spec:   docs/part1-planning/tests/spec_02_parsing_agent.md
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.exceptions import AuditError, ParseError  # type: ignore[import]
from src.parsing import (  # type: ignore[import]
    dispatch_parsing_subagent,
    extract_ambiguities,
    reverse_audit,
    run_batch_pipeline,
    validate_schema,
)
from src.schema import AuditStatus, Operator, Rule  # type: ignore[import]
from src.exceptions import ValidationError  # type: ignore[import]


# ---------------------------------------------------------------------------
# Helpers — minimal valid ParseInput dict
# ---------------------------------------------------------------------------

_VALID_ANCHOR: dict[str, Any] = {
    "source_url": "https://pmkisan.gov.in/guidelines.pdf",
    "document_title": "PM-KISAN Guidelines",
    "source_quote": "All landholding farmer families shall own cultivable land",
    "section": "3.2",
    "notification_date": "2023-11-15",
    "language": "en",
}

_VALID_RULE_DICT: dict[str, Any] = {
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
    "audit_status": "PENDING",
    "display_text": "Applicant must own cultivable agricultural land",
    "version": "1.0.0",
}


def _make_parse_input(scheme_id: str) -> Any:
    from src.parsing import ParseInput  # type: ignore[import]

    return ParseInput(scheme_id=scheme_id, input_type="prose", raw_text=f"eligibility text for {scheme_id}")


def _make_parse_result(scheme_id: str, triage: str = "VERIFIED") -> Any:
    from src.parsing import ParseResult  # type: ignore[import]

    rule = Rule(**{**_VALID_RULE_DICT, "rule_id": f"{scheme_id}-R001", "scheme_id": scheme_id})
    confidence = 0.95 if triage != "DISPUTED" else 0.0
    return ParseResult(
        scheme_id=scheme_id,
        rules=[rule] if triage != "DISPUTED" else [],
        triage_status=triage,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Section 1: dispatch_parsing_subagent
# ---------------------------------------------------------------------------


class TestDispatchParsingSubagent:
    async def test__valid_batch__returns_one_result_per_input(self) -> None:
        """2-item batch → 2 ParseResult objects, one per scheme."""
        batch = [_make_parse_input("PMKISAN"), _make_parse_input("PMSYM")]
        expected = [_make_parse_result("PMKISAN"), _make_parse_result("PMSYM")]

        with patch(
            "src.parsing._call_subagent",
            new_callable=AsyncMock,
            return_value=expected,
        ):
            results = await dispatch_parsing_subagent(batch)

        assert len(results) == 2
        assert results[0].scheme_id == "PMKISAN"
        assert results[1].scheme_id == "PMSYM"
        from src.parsing import ParseResult  # type: ignore[import]
        assert all(isinstance(r, ParseResult) for r in results)

    async def test__batch_of_50__handles_max_batch_size(self) -> None:
        """50-item batch (maximum size) → 50 ParseResult objects returned."""
        batch = [_make_parse_input(f"SCHEME-{i:02d}") for i in range(50)]
        expected = [_make_parse_result(f"SCHEME-{i:02d}") for i in range(50)]

        with patch(
            "src.parsing._call_subagent",
            new_callable=AsyncMock,
            return_value=expected,
        ):
            results = await dispatch_parsing_subagent(batch)

        assert len(results) == 50

    async def test__single_scheme_fails__other_schemes_succeed(self) -> None:
        """Individual parse failure → failed item has DISPUTED/confidence=0.0; others VERIFIED."""
        batch = [
            _make_parse_input("PMKISAN"),
            _make_parse_input("FAIL-SCHEME"),
            _make_parse_input("PMSYM"),
        ]
        results_from_subagent = [
            _make_parse_result("PMKISAN", "VERIFIED"),
            _make_parse_result("FAIL-SCHEME", "DISPUTED"),
            _make_parse_result("PMSYM", "VERIFIED"),
        ]

        with patch(
            "src.parsing._call_subagent",
            new_callable=AsyncMock,
            return_value=results_from_subagent,
        ):
            results = await dispatch_parsing_subagent(batch)

        assert len(results) == 3
        assert results[1].triage_status == "DISPUTED"
        assert results[1].confidence == 0.0
        assert results[0].triage_status == "VERIFIED"
        assert results[2].triage_status == "VERIFIED"

    async def test__total_batch_failure__raises_parse_error(self) -> None:
        """Subagent completely unreachable → ParseError raised."""
        batch = [_make_parse_input("PMKISAN")]

        with patch(
            "src.parsing._call_subagent",
            new_callable=AsyncMock,
            side_effect=ParseError("subagent unreachable"),
        ):
            with pytest.raises(ParseError):
                await dispatch_parsing_subagent(batch)

    async def test__empty_batch__returns_empty_list(self) -> None:
        """Empty batch → empty list; no exception."""
        results = await dispatch_parsing_subagent([])
        assert results == []


# ---------------------------------------------------------------------------
# Section 2: validate_schema
# ---------------------------------------------------------------------------


class TestValidateSchema:
    def test__valid_rule_dict__returns_rule_object(self) -> None:
        """Valid dict → Rule object with correct operator."""
        rule = validate_schema(_VALID_RULE_DICT)
        assert isinstance(rule, Rule)
        assert rule.rule_id == "PMKISAN-R001"
        assert rule.operator == Operator.EQ

    def test__missing_rule_id__raises_validation_error(self) -> None:
        """Missing rule_id → ValidationError mentioning 'rule_id'."""
        bad = {k: v for k, v in _VALID_RULE_DICT.items() if k != "rule_id"}
        with pytest.raises(ValidationError) as exc_info:
            validate_schema(bad)
        assert "rule_id" in str(exc_info.value)

    def test__invalid_operator__raises_validation_error(self) -> None:
        """operator='FUZZY' → ValidationError mentioning 'operator'."""
        bad = {**_VALID_RULE_DICT, "operator": "FUZZY"}
        with pytest.raises(ValidationError) as exc_info:
            validate_schema(bad)
        assert "operator" in str(exc_info.value)

    def test__confidence_out_of_range__raises_validation_error(self) -> None:
        """confidence=1.5 → ValidationError."""
        with pytest.raises(ValidationError):
            validate_schema({**_VALID_RULE_DICT, "confidence": 1.5})

    def test__invalid_audit_status__raises_validation_error(self) -> None:
        """audit_status='APPROVED' → ValidationError."""
        with pytest.raises(ValidationError):
            validate_schema({**_VALID_RULE_DICT, "audit_status": "APPROVED"})

    def test__missing_source_quote__raises_validation_error(self) -> None:
        """source_quote=None → ValidationError mentioning source_quote."""
        bad_anchor = {**_VALID_ANCHOR, "source_quote": None}
        bad = {**_VALID_RULE_DICT, "source_anchor": bad_anchor}
        with pytest.raises(ValidationError) as exc_info:
            validate_schema(bad)
        assert "source_quote" in str(exc_info.value)

    def test__duplicate_rule_id__not_detected_at_single_rule_level(self) -> None:
        """Two calls with same rule_id both pass (uniqueness is pipeline-level, Gate 4)."""
        rule1 = validate_schema(_VALID_RULE_DICT)
        rule2 = validate_schema({**_VALID_RULE_DICT, "confidence": 0.80})
        assert rule1.rule_id == rule2.rule_id == "PMKISAN-R001"


# ---------------------------------------------------------------------------
# Section 3: extract_ambiguities
# ---------------------------------------------------------------------------


class TestExtractAmbiguities:
    async def test__vague_text__returns_flag_records(self) -> None:
        """'resident of the state' (Semantic Vagueness) → at least one AMB flag."""
        from src.schema import AmbiguityFlag  # type: ignore[import]

        flags = await extract_ambiguities("Applicant should be a resident of the state", [])

        assert len(flags) > 0
        assert flags[0].ambiguity_type_code == 1
        assert flags[0].ambiguity_id.startswith("AMB-")
        assert flags[0].severity is not None

    async def test__discretionary_clause__flags_type_4(self) -> None:
        """'at the discretion of' → Type 4 flag present."""
        text = "Eligible applicants may be selected at the discretion of the district collector"
        flags = await extract_ambiguities(text, [])
        assert any(f.ambiguity_type_code == 4 for f in flags)

    async def test__clear_text__returns_empty_list_or_low_severity(self) -> None:
        """Clear numeric text → empty list or only LOW severity flags; never raises."""
        flags = await extract_ambiguities(
            "Applicant must be 18 years old and own agricultural land.", []
        )
        assert isinstance(flags, list)
        high_or_above = [f for f in flags if f.severity.value in ("HIGH", "CRITICAL")]
        assert len(high_or_above) == 0

    async def test__financial_threshold_reference__flags_type_10(self) -> None:
        """'below poverty line' without numeric value → Type 10 flag."""
        text = "Families below poverty line are eligible"
        flags = await extract_ambiguities(text, [])
        assert any(f.ambiguity_type_code == 10 for f in flags)

    async def test__never_raises_on_any_input__returns_list(self) -> None:
        """Empty text input → empty list; no exception raised."""
        flags = await extract_ambiguities("", [])
        assert isinstance(flags, list)


# ---------------------------------------------------------------------------
# Section 4: reverse_audit
# ---------------------------------------------------------------------------


class TestReverseAudit:
    async def test__exact_match_above_90__returns_verified(self, valid_rule_pmkisan: Rule) -> None:
        """similarity=0.95 → AuditStatus.VERIFIED."""
        with patch(
            "src.parsing.compute_semantic_similarity",
            new_callable=AsyncMock,
            return_value=0.95,
        ):
            result = await reverse_audit(valid_rule_pmkisan)

        assert result.audit_status == AuditStatus.VERIFIED
        assert result.similarity_score == 0.95
        assert result.rule_id == valid_rule_pmkisan.rule_id

    async def test__partial_match_between_70_and_90__returns_needs_review(
        self, valid_rule_pmkisan: Rule
    ) -> None:
        """similarity=0.82 → AuditStatus.NEEDS_REVIEW."""
        with patch(
            "src.parsing.compute_semantic_similarity",
            new_callable=AsyncMock,
            return_value=0.82,
        ):
            result = await reverse_audit(valid_rule_pmkisan)

        assert result.audit_status == AuditStatus.NEEDS_REVIEW
        assert result.similarity_score == 0.82

    async def test__low_similarity_below_70__returns_disputed(
        self, valid_rule_pmkisan: Rule
    ) -> None:
        """similarity=0.45 → AuditStatus.DISPUTED."""
        with patch(
            "src.parsing.compute_semantic_similarity",
            new_callable=AsyncMock,
            return_value=0.45,
        ):
            result = await reverse_audit(valid_rule_pmkisan)

        assert result.audit_status == AuditStatus.DISPUTED
        assert result.similarity_score == 0.45

    async def test__source_url_unreachable__raises_audit_error(
        self, valid_rule_pmkisan: Rule
    ) -> None:
        """Unreachable source URL after retries → AuditError."""
        with patch(
            "src.parsing._fetch_source_text",
            new_callable=AsyncMock,
            side_effect=AuditError("source URL unreachable"),
        ):
            with pytest.raises(AuditError):
                await reverse_audit(valid_rule_pmkisan)

    async def test__threshold_boundary_exactly_at_90__returns_verified(
        self, valid_rule_pmkisan: Rule
    ) -> None:
        """similarity=0.90 exactly → VERIFIED (≥0.90 is inclusive)."""
        with patch(
            "src.parsing.compute_semantic_similarity",
            new_callable=AsyncMock,
            return_value=0.90,
        ):
            result = await reverse_audit(valid_rule_pmkisan)

        assert result.audit_status == AuditStatus.VERIFIED

    async def test__threshold_boundary_exactly_at_70__returns_needs_review(
        self, valid_rule_pmkisan: Rule
    ) -> None:
        """similarity=0.70 exactly → NEEDS_REVIEW (lower bound is inclusive)."""
        with patch(
            "src.parsing.compute_semantic_similarity",
            new_callable=AsyncMock,
            return_value=0.70,
        ):
            result = await reverse_audit(valid_rule_pmkisan)

        assert result.audit_status == AuditStatus.NEEDS_REVIEW


# ---------------------------------------------------------------------------
# Section 5: run_batch_pipeline
# ---------------------------------------------------------------------------


class TestRunBatchPipeline:
    _15_SCHEMES = [
        "PMKISAN", "MGNREGA", "PMSYM", "AYUSHMAN", "NSAP-IGNOAPS",
        "PMAY-G", "PMAY-U", "NFSA", "PMJDY", "MUDRA",
        "DDU-GKY", "PMMVY", "SARKARI-A", "SARKARI-B", "SARKARI-C",
    ]

    async def test__15_schemes__returns_run_manifest(self) -> None:
        """Full 15-scheme batch → RunManifest with correct counts."""
        from src.parsing import RunManifest  # type: ignore[import]

        mock_results = [_make_parse_result(s) for s in self._15_SCHEMES]

        with patch(
            "src.parsing.dispatch_parsing_subagent",
            new_callable=AsyncMock,
            return_value=mock_results,
        ):
            with patch(
                "src.parsing.reverse_audit",
                new_callable=AsyncMock,
                return_value=MagicMock(audit_status=AuditStatus.VERIFIED, similarity_score=0.95),
            ):
                manifest = await run_batch_pipeline(self._15_SCHEMES, batch_size=50)

        assert isinstance(manifest, RunManifest)
        assert manifest.schemes_processed == 15
        assert manifest.rules_generated > 0
        assert manifest.completed_at is not None
        assert len(manifest.run_id) > 0

    async def test__some_rules_disputed__routed_to_review_queue(self) -> None:
        """3 DISPUTED rules → excluded from rule base; listed in review_queue."""
        schemes = ["PMKISAN", "PMSYM", "MGNREGA"]
        mock_results = [
            _make_parse_result("PMKISAN", "VERIFIED"),
            _make_parse_result("PMSYM", "DISPUTED"),
            _make_parse_result("MGNREGA", "DISPUTED"),
        ]

        with patch(
            "src.parsing.dispatch_parsing_subagent",
            new_callable=AsyncMock,
            return_value=mock_results,
        ):
            with patch(
                "src.parsing.reverse_audit",
                new_callable=AsyncMock,
                return_value=MagicMock(audit_status=AuditStatus.VERIFIED, similarity_score=0.95),
            ):
                manifest = await run_batch_pipeline(schemes, batch_size=50)

        assert manifest.rules_disputed > 0
        assert len(manifest.review_queue) > 0

    async def test__needs_review_rules__included_in_rule_base_with_penalty(self) -> None:
        """NEEDS_REVIEW rules → included in rule base (confidence-penalised)."""
        schemes = ["PMKISAN", "PMSYM"]
        mock_results = [
            _make_parse_result("PMKISAN", "VERIFIED"),
            _make_parse_result("PMSYM", "NEEDS_REVIEW"),
        ]

        with patch(
            "src.parsing.dispatch_parsing_subagent",
            new_callable=AsyncMock,
            return_value=mock_results,
        ):
            with patch(
                "src.parsing.reverse_audit",
                new_callable=AsyncMock,
                return_value=MagicMock(audit_status=AuditStatus.NEEDS_REVIEW, similarity_score=0.80),
            ):
                manifest = await run_batch_pipeline(schemes, batch_size=50)

        assert manifest.rules_needs_review > 0
        assert any(r in manifest.review_queue for r in [f"PMSYM-R001"])

    async def test__pipeline_never_stalls_on_error__continues_to_next_scheme(self) -> None:
        """One DISPUTED scheme → all 15 schemes processed; no stall."""
        schemes = self._15_SCHEMES
        mock_results = [
            _make_parse_result(s, "DISPUTED" if s == "MGNREGA" else "VERIFIED")
            for s in schemes
        ]

        with patch(
            "src.parsing.dispatch_parsing_subagent",
            new_callable=AsyncMock,
            return_value=mock_results,
        ):
            with patch(
                "src.parsing.reverse_audit",
                new_callable=AsyncMock,
                return_value=MagicMock(audit_status=AuditStatus.VERIFIED, similarity_score=0.95),
            ):
                manifest = await run_batch_pipeline(schemes, batch_size=50)

        assert manifest.schemes_processed == 15

    async def test__empty_scheme_list__returns_empty_manifest(self) -> None:
        """Empty scheme list → manifest with zero counts; no exception."""
        manifest = await run_batch_pipeline([], batch_size=50)
        assert manifest.schemes_processed == 0
        assert manifest.rules_generated == 0

    async def test__configurable_batch_size__respects_env_var(self) -> None:
        """PARSE_BATCH_SIZE=10, 25 schemes → subagent called 3 times (10+10+5)."""
        schemes = [f"SCHEME-{i:02d}" for i in range(25)]
        mock_results_per_call = [_make_parse_result(f"SCHEME-{i:02d}") for i in range(10)]

        dispatch_mock = AsyncMock(return_value=mock_results_per_call)

        with patch.dict(os.environ, {"PARSE_BATCH_SIZE": "10"}):
            with patch("src.parsing.dispatch_parsing_subagent", dispatch_mock):
                with patch(
                    "src.parsing.reverse_audit",
                    new_callable=AsyncMock,
                    return_value=MagicMock(audit_status=AuditStatus.VERIFIED, similarity_score=0.95),
                ):
                    await run_batch_pipeline(schemes)

        assert dispatch_mock.call_count == 3
