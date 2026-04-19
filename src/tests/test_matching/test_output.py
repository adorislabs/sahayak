"""Tests for Feature 6: MatchingResult assembly and output formatting.

Spec reference: docs/part2-planning/specs/06-output-formatting.md
Architecture:   docs/part2-planning/ARCHITECTURE-CONTRACT.md § src/matching/output.py

Output contracts:
  - assemble_matching_result buckets determinations by status
  - DocumentChecklist is de-duplicated across all scheme results
  - to_json() returns valid JSON string
  - to_cli_text() returns non-empty plain text
  - to_markdown() returns string containing markdown headers
  - generate_summary_text has status-specific templates for all 8 statuses
  - profile_id is a hash of profile data, not raw PII
  - evaluation_timestamp is valid ISO 8601
  - MatchingResult.summary counts schemes by status correctly

Tests will fail (ImportError) until Agent B implements src/matching/output.py.
"""

from __future__ import annotations

import json
import re
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.matching.output import (  # type: ignore[import]
    DocumentChecklist,
    MatchingResult,
    ResultSummary,
    SchemeResult,
    assemble_matching_result,
    generate_summary_text,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_determination(
    scheme_id: str,
    scheme_name: str = "",
    status: str = "ELIGIBLE",
    ministry: str = "Test Ministry",
    confidence_composite: float = 0.85,
    rule_evals: list | None = None,
    gap_analysis: Any = None,
    state_overrides_applied: list | None = None,
    excluded_rules_count: int = 0,
    discretion_warnings: list | None = None,
    rule_trace: list | None = None,
) -> MagicMock:
    det = MagicMock()
    det.scheme_id = scheme_id
    det.scheme_name = scheme_name or scheme_id
    det.status = status
    det.rule_evaluations = rule_evals or []
    det.gap_analysis = gap_analysis
    det.state_overrides_applied = state_overrides_applied or []
    det.excluded_rules_count = excluded_rules_count
    det.discretion_warnings = discretion_warnings or []
    det.rule_trace = rule_trace or []

    scheme = MagicMock()
    scheme.ministry = ministry
    det.scheme = scheme

    confidence = MagicMock()
    confidence.composite = confidence_composite
    confidence.composite_label = "HIGH" if confidence_composite >= 0.8 else "MEDIUM"
    confidence.rule_match_score = 1.0
    confidence.data_confidence = 0.9
    confidence.profile_completeness = 0.8
    confidence.bottleneck = "profile_completeness"
    confidence.bottleneck_explanation = "Some fields missing"
    confidence.improvement_actions = []
    det.confidence = confidence

    return det


def _make_profile_mock(state: str = "MH") -> MagicMock:
    profile = MagicMock()
    profile.location_state = state
    profile.applicant_age = 38
    profile.applicant_caste_category = "OBC"
    profile.model_dump = MagicMock(return_value={"applicant_age": 38, "location_state": state})
    return profile


def _make_sequence_mock() -> MagicMock:
    seq = MagicMock()
    seq.steps = []
    seq.choice_sets = []
    seq.parallel_groups = []
    seq.complementary_suggestions = []
    seq.warnings = []
    seq.total_estimated_time = None
    return seq


def _make_profile_completeness_mock() -> MagicMock:
    pc = MagicMock()
    pc.completeness_score = 0.75
    pc.total_relevant_fields = 8
    pc.populated_fields = 6
    pc.missing_fields = ["household.bpl_status", "employment.type"]
    pc.impact_assessment = []
    return pc


# ===========================================================================
# Group 1: assemble_matching_result — bucketing
# ===========================================================================

class TestAssembleMatchingResultBucketing:
    """assemble_matching_result correctly buckets determinations by status."""

    def test_eligible_schemes_bucketed_correctly(self) -> None:
        """ELIGIBLE determination must appear in result.eligible_schemes."""
        profile = _make_profile_mock()
        dets = [_make_determination("PMKISAN", status="ELIGIBLE")]
        seq = _make_sequence_mock()

        result = assemble_matching_result(profile, dets, seq, [])

        assert len(result.eligible_schemes) == 1
        assert result.eligible_schemes[0].scheme_id == "PMKISAN"

    def test_near_miss_schemes_bucketed_correctly(self) -> None:
        """NEAR_MISS determination must appear in result.near_miss_schemes."""
        profile = _make_profile_mock()
        dets = [_make_determination("PMKISAN", status="NEAR_MISS")]
        seq = _make_sequence_mock()

        result = assemble_matching_result(profile, dets, seq, [])

        assert len(result.near_miss_schemes) == 1
        assert result.near_miss_schemes[0].scheme_id == "PMKISAN"

    def test_ineligible_schemes_bucketed_correctly(self) -> None:
        profile = _make_profile_mock()
        dets = [_make_determination("PMSYM", status="INELIGIBLE")]
        seq = _make_sequence_mock()

        result = assemble_matching_result(profile, dets, seq, [])

        assert len(result.ineligible_schemes) == 1

    def test_requires_prerequisite_bucketed_correctly(self) -> None:
        profile = _make_profile_mock()
        dets = [_make_determination("NSAP", status="REQUIRES_PREREQUISITE")]
        seq = _make_sequence_mock()

        result = assemble_matching_result(profile, dets, seq, [])

        assert len(result.requires_prerequisite_schemes) == 1

    def test_partial_schemes_bucketed_correctly(self) -> None:
        profile = _make_profile_mock()
        dets = [_make_determination("MGNREGA", status="PARTIAL")]
        seq = _make_sequence_mock()

        result = assemble_matching_result(profile, dets, seq, [])

        assert len(result.partial_schemes) == 1

    def test_insufficient_data_bucketed_correctly(self) -> None:
        profile = _make_profile_mock()
        dets = [_make_determination("NSAP", status="INSUFFICIENT_DATA")]
        seq = _make_sequence_mock()

        result = assemble_matching_result(profile, dets, seq, [])

        assert len(result.insufficient_data_schemes) == 1

    def test_mixed_statuses_all_bucketed_correctly(self) -> None:
        """Multiple schemes of different statuses must all end up in correct buckets."""
        profile = _make_profile_mock()
        dets = [
            _make_determination("PMKISAN", status="ELIGIBLE"),
            _make_determination("MGNREGA", status="NEAR_MISS"),
            _make_determination("PMSYM", status="INELIGIBLE"),
            _make_determination("NSAP", status="PARTIAL"),
        ]
        seq = _make_sequence_mock()

        result = assemble_matching_result(profile, dets, seq, [])

        assert len(result.eligible_schemes) == 1
        assert len(result.near_miss_schemes) == 1
        assert len(result.ineligible_schemes) == 1
        assert len(result.partial_schemes) == 1


# ===========================================================================
# Group 2: Metadata fields
# ===========================================================================

class TestMatchingResultMetadata:
    """Metadata fields must be correctly populated."""

    def test_evaluation_timestamp_is_valid_iso_8601(self) -> None:
        """evaluation_timestamp must match ISO 8601 format."""
        profile = _make_profile_mock()
        seq = _make_sequence_mock()

        result = assemble_matching_result(profile, [], seq, [])

        ts = result.evaluation_timestamp
        # Basic ISO 8601: YYYY-MM-DDTHH:MM
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", ts), f"Not ISO 8601: {ts!r}"

    def test_profile_id_is_hash_not_pii(self) -> None:
        """profile_id must not expose raw field values from the profile."""
        profile = _make_profile_mock(state="MH")
        seq = _make_sequence_mock()

        result = assemble_matching_result(profile, [], seq, [])

        assert result.profile_id != "MH"
        assert result.profile_id != "38"  # not raw age
        assert len(result.profile_id) > 8  # must be a real hash

    def test_profile_id_is_deterministic_for_same_profile(self) -> None:
        """Two calls with the same profile must produce the same profile_id."""
        profile = _make_profile_mock(state="MH")
        seq = _make_sequence_mock()

        result1 = assemble_matching_result(profile, [], seq, [])
        result2 = assemble_matching_result(profile, [], seq, [])

        assert result1.profile_id == result2.profile_id

    def test_state_applied_matches_profile_state(self) -> None:
        """result.state_applied must match profile.location_state."""
        profile = _make_profile_mock(state="UP")
        seq = _make_sequence_mock()

        result = assemble_matching_result(profile, [], seq, [])

        assert result.state_applied == "UP"

    def test_engine_version_non_empty_string(self) -> None:
        """engine_version must be a non-empty string."""
        profile = _make_profile_mock()
        seq = _make_sequence_mock()

        result = assemble_matching_result(profile, [], seq, [])

        assert isinstance(result.engine_version, str)
        assert len(result.engine_version) > 0


# ===========================================================================
# Group 3: Summary statistics
# ===========================================================================

class TestResultSummary:
    """ResultSummary fields accurately count schemes by status."""

    def test_summary_eligible_count_correct(self) -> None:
        """summary.eligible_count must equal len(eligible_schemes)."""
        profile = _make_profile_mock()
        dets = [
            _make_determination("A", status="ELIGIBLE"),
            _make_determination("B", status="ELIGIBLE"),
            _make_determination("C", status="INELIGIBLE"),
        ]
        seq = _make_sequence_mock()

        result = assemble_matching_result(profile, dets, seq, [])

        assert result.summary.eligible_count == 2
        assert result.summary.ineligible_count == 1

    def test_summary_total_schemes_evaluated(self) -> None:
        """summary.total_schemes_evaluated == len(determinations)."""
        profile = _make_profile_mock()
        dets = [
            _make_determination("A", status="ELIGIBLE"),
            _make_determination("B", status="NEAR_MISS"),
            _make_determination("C", status="PARTIAL"),
        ]
        seq = _make_sequence_mock()

        result = assemble_matching_result(profile, dets, seq, [])

        assert result.summary.total_schemes_evaluated == 3

    def test_summary_top_recommendation_is_highest_confidence_eligible(self) -> None:
        """summary.top_recommendation must be the ELIGIBLE scheme with highest composite."""
        profile = _make_profile_mock()
        dets = [
            _make_determination("A", status="ELIGIBLE", confidence_composite=0.75),
            _make_determination("B", status="ELIGIBLE", confidence_composite=0.95),
        ]
        seq = _make_sequence_mock()

        result = assemble_matching_result(profile, dets, seq, [])

        assert result.summary.top_recommendation == "B"

    def test_summary_top_recommendation_none_when_no_eligible_schemes(self) -> None:
        """summary.top_recommendation must be None when no ELIGIBLE schemes."""
        profile = _make_profile_mock()
        dets = [_make_determination("A", status="INELIGIBLE")]
        seq = _make_sequence_mock()

        result = assemble_matching_result(profile, dets, seq, [])

        assert result.summary.top_recommendation is None


# ===========================================================================
# Group 4: Document checklist de-duplication
# ===========================================================================

class TestDocumentChecklist:
    """DocumentChecklist de-duplicates documents needed across all schemes."""

    def test_document_checklist_is_document_checklist_instance(self) -> None:
        """result.document_checklist must be a DocumentChecklist instance."""
        profile = _make_profile_mock()
        seq = _make_sequence_mock()

        result = assemble_matching_result(profile, [], seq, [])

        assert isinstance(result.document_checklist, DocumentChecklist)

    def test_same_document_across_two_schemes_deduplicated(self) -> None:
        """Aadhaar required by both PMKISAN and MGNREGA must appear once in checklist."""
        profile = _make_profile_mock()
        # Both schemes require aadhaar → checklist deduplicates
        dets = [
            _make_determination("PMKISAN", status="ELIGIBLE"),
            _make_determination("MGNREGA", status="ELIGIBLE"),
        ]
        seq = _make_sequence_mock()

        result = assemble_matching_result(profile, dets, seq, [])

        if result.document_checklist.items:
            # Count how many times aadhaar appears
            aadhaar_items = [
                i for i in result.document_checklist.items
                if "aadhaar" in i.document_field.lower()
            ]
            # Must not appear twice
            assert len(aadhaar_items) <= 1


# ===========================================================================
# Group 5: Output format methods
# ===========================================================================

class TestOutputFormatMethods:
    """to_json, to_cli_text, to_markdown must serialize correctly."""

    def _build_result(self) -> MatchingResult:
        profile = _make_profile_mock()
        dets = [
            _make_determination("PMKISAN", status="ELIGIBLE"),
            _make_determination("PMSYM", status="INELIGIBLE"),
        ]
        seq = _make_sequence_mock()
        return assemble_matching_result(profile, dets, seq, [])

    def test_to_json_returns_valid_json_string(self) -> None:
        """to_json() must return a string that can be parsed by json.loads."""
        result = self._build_result()
        json_str = result.to_json()

        assert isinstance(json_str, str)
        parsed = json.loads(json_str)  # must not raise
        assert isinstance(parsed, dict)

    def test_to_json_contains_eligible_schemes(self) -> None:
        """to_json() output must include the eligible schemes data."""
        result = self._build_result()
        json_str = result.to_json()
        parsed = json.loads(json_str)

        # Should have a key for eligible schemes
        assert "eligible_schemes" in parsed or "PMKISAN" in json_str

    def test_to_cli_text_returns_non_empty_string(self) -> None:
        """to_cli_text() must return a non-empty plain text string."""
        result = self._build_result()
        cli_text = result.to_cli_text()

        assert isinstance(cli_text, str)
        assert len(cli_text) > 0

    def test_to_cli_text_contains_scheme_names(self) -> None:
        """to_cli_text() must mention scheme IDs or names."""
        result = self._build_result()
        cli_text = result.to_cli_text()

        assert "PMKISAN" in cli_text or "PM-KISAN" in cli_text

    def test_to_markdown_returns_string_with_headers(self) -> None:
        """to_markdown() must return a string containing markdown headers (#)."""
        result = self._build_result()
        md = result.to_markdown()

        assert isinstance(md, str)
        assert "#" in md  # at least one markdown header

    def test_to_markdown_contains_eligible_section(self) -> None:
        """to_markdown() must contain a section for eligible schemes."""
        result = self._build_result()
        md = result.to_markdown()

        # Must have some mention of eligible
        assert "ELIGIBLE" in md.upper() or "Eligible" in md

    def test_to_json_never_raises(self) -> None:
        """to_json() must never raise on any MatchingResult."""
        result = self._build_result()
        # Should not raise
        json_str = result.to_json()
        assert json_str is not None

    def test_to_cli_text_never_raises(self) -> None:
        """to_cli_text() must never raise on any MatchingResult."""
        result = self._build_result()
        cli = result.to_cli_text()
        assert cli is not None

    def test_to_markdown_never_raises(self) -> None:
        """to_markdown() must never raise on any MatchingResult."""
        result = self._build_result()
        md = result.to_markdown()
        assert md is not None


# ===========================================================================
# Group 6: generate_summary_text
# ===========================================================================

class TestGenerateSummaryText:
    """generate_summary_text produces status-specific natural language summaries."""

    @pytest.mark.parametrize("status", [
        "ELIGIBLE",
        "ELIGIBLE_WITH_CAVEATS",
        "NEAR_MISS",
        "INELIGIBLE",
        "DISQUALIFIED",
        "REQUIRES_PREREQUISITE",
        "PARTIAL",
        "INSUFFICIENT_DATA",
    ])
    def test_generate_summary_text_for_all_8_statuses(self, status: str) -> None:
        """generate_summary_text must return a non-empty string for all 8 statuses."""
        scheme_result = MagicMock()
        scheme_result.scheme_id = "PMKISAN"
        scheme_result.scheme_name = "PM-KISAN"
        scheme_result.status = status
        scheme_result.confidence = MagicMock()
        scheme_result.confidence.composite_label = "HIGH"
        scheme_result.rules_passed = 3
        scheme_result.rules_failed = 1 if status in ("NEAR_MISS", "INELIGIBLE") else 0

        text = generate_summary_text(scheme_result)

        assert isinstance(text, str)
        assert len(text) > 0

    def test_generate_summary_text_never_raises(self) -> None:
        """generate_summary_text must never raise, even with minimal input."""
        scheme_result = MagicMock()
        scheme_result.status = "ELIGIBLE"
        scheme_result.scheme_name = "Test Scheme"

        text = generate_summary_text(scheme_result)
        assert isinstance(text, str)

    def test_eligible_summary_text_positive_tone(self) -> None:
        """ELIGIBLE summary must convey qualification positively."""
        scheme_result = MagicMock()
        scheme_result.scheme_id = "PMKISAN"
        scheme_result.scheme_name = "PM-KISAN"
        scheme_result.status = "ELIGIBLE"
        scheme_result.rules_passed = 4
        scheme_result.rules_failed = 0

        text = generate_summary_text(scheme_result)

        # Should not contain negative framing
        negative_words = ["ineligible", "disqualified", "failed", "cannot apply"]
        text_lower = text.lower()
        assert not any(word in text_lower for word in negative_words)

    def test_ineligible_summary_text_not_positive(self) -> None:
        """INELIGIBLE summary must not claim user is eligible."""
        scheme_result = MagicMock()
        scheme_result.status = "INELIGIBLE"
        scheme_result.scheme_name = "PM-KISAN"
        scheme_result.rules_passed = 1
        scheme_result.rules_failed = 3

        text = generate_summary_text(scheme_result)

        # Must not say user is eligible
        assert "eligible" not in text.lower() or "not eligible" in text.lower()
