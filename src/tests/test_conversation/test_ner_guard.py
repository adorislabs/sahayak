"""Tests for the NER hallucination guard (src/conversation/ner_guard.py)."""

from __future__ import annotations

import pytest
from src.conversation.extraction import ExtractedField, ExtractionResult, ExtractionReasoning
from src.conversation.ner_guard import NERGuard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_ef(
    field_path: str,
    value,
    source_span: str = "35",
    confidence: str = "HIGH",
) -> ExtractedField:
    return ExtractedField(
        field_path=field_path,
        value=value,
        raw_value=str(value),
        confidence=confidence,
        source_span=source_span,
        reasoning="test",
    )


def make_result(fields: list[ExtractedField]) -> ExtractionResult:
    return ExtractionResult(
        extractions=fields,
        detected_language="en",
        reasoning_chain=[
            ExtractionReasoning(
                source_span=ef.source_span,
                field_path=ef.field_path,
                field_label=ef.field_path,
                value=ef.value,
                raw_value=ef.raw_value,
                confidence=ef.confidence,
                reasoning_note=ef.reasoning,
            )
            for ef in fields
        ],
    )


guard = NERGuard()


# ---------------------------------------------------------------------------
# Range checks
# ---------------------------------------------------------------------------

class TestRangeChecks:
    def test_valid_age_passes(self):
        result = make_result([make_ef("applicant.age", 35, "35 year old")])
        report = guard.validate(result)
        assert len(report.passed_fields) == 1
        assert len(report.rejected_fields) == 0

    def test_age_too_high_rejected(self):
        result = make_result([make_ef("applicant.age", 999, "999 years old")])
        report = guard.validate(result)
        assert any(ef.field_path == "applicant.age" for ef in report.rejected_fields)

    def test_age_negative_rejected(self):
        result = make_result([make_ef("applicant.age", -5, "-5")])
        report = guard.validate(result)
        assert len(report.rejected_fields) == 1

    def test_disability_100_passes(self):
        result = make_result([make_ef("applicant.disability_percentage", 100, "100%")])
        report = guard.validate(result)
        assert len(report.rejected_fields) == 0

    def test_disability_over_100_rejected(self):
        result = make_result([make_ef("applicant.disability_percentage", 150, "150%")])
        report = guard.validate(result)
        assert len(report.rejected_fields) == 1

    def test_income_zero_rejected(self):
        result = make_result([make_ef("household.income_annual", -1000, "negative")])
        report = guard.validate(result)
        assert len(report.rejected_fields) == 1

    def test_valid_income_passes(self):
        result = make_result([make_ef("household.income_annual", 150_000, "1.5 lakh")])
        report = guard.validate(result)
        assert len(report.rejected_fields) == 0


# ---------------------------------------------------------------------------
# Vocabulary checks
# ---------------------------------------------------------------------------

class TestVocabChecks:
    def test_valid_caste_passes(self):
        result = make_result([make_ef("applicant.caste_category", "SC", "SC")])
        report = guard.validate(result)
        assert len(report.rejected_fields) == 0

    def test_invalid_caste_is_warned_not_rejected(self):
        """Vocab mismatches are now WARN (not REJECT) — value is still kept."""
        result = make_result([make_ef("applicant.caste_category", "ALIEN", "alien")])
        report = guard.validate(result)
        assert len(report.rejected_fields) == 0
        assert len(report.warned_fields) == 1

    def test_valid_gender_passes(self):
        result = make_result([make_ef("applicant.gender", "female", "female")])
        report = guard.validate(result)
        assert len(report.rejected_fields) == 0

    def test_invalid_gender_is_warned_not_rejected(self):
        """Vocab mismatches are now WARN — value is still kept for profile."""
        result = make_result([make_ef("applicant.gender", "martian", "martian")])
        report = guard.validate(result)
        assert len(report.rejected_fields) == 0
        assert len(report.warned_fields) == 1

    def test_valid_state_passes(self):
        result = make_result([make_ef("location.state", "UP", "UP")])
        report = guard.validate(result)
        assert len(report.rejected_fields) == 0

    def test_invalid_state_is_warned_not_rejected(self):
        """Unrecognised state name: warns but does not block extraction."""
        result = make_result([make_ef("location.state", "Mars", "Mars")])
        report = guard.validate(result)
        assert len(report.rejected_fields) == 0
        assert len(report.warned_fields) == 1


# ---------------------------------------------------------------------------
# Source anchor checks
# ---------------------------------------------------------------------------

class TestAnchorChecks:
    def test_age_no_source_span_warns(self):
        ef = make_ef("applicant.age", 35, "")
        result = make_result([ef])
        report = guard.validate(result)
        # Should warn (not reject) for empty source span
        assert len(report.rejected_fields) == 0
        # Either passed or warned
        assert (len(report.passed_fields) + len(report.warned_fields)) == 1

    def test_age_non_numeric_source_warns(self):
        ef = make_ef("applicant.age", 35, "middle aged person")
        result = make_result([ef])
        # No digits in source span → warn
        report = guard.validate(result)
        assert len(report.rejected_fields) == 0


# ---------------------------------------------------------------------------
# Cross-field checks
# ---------------------------------------------------------------------------

class TestCrossFieldChecks:
    def test_consistent_age_and_birth_year_passes(self):
        from datetime import datetime
        current_year = datetime.now().year
        birth_year = current_year - 35
        result = make_result([
            make_ef("applicant.age", 35, "35 year old"),
            make_ef("applicant.birth_year", birth_year, str(birth_year)),
        ])
        report = guard.validate(result)
        assert len(report.rejected_fields) == 0

    def test_inconsistent_age_birth_year_warns(self):
        result = make_result([
            make_ef("applicant.age", 35, "35 year old"),
            make_ef("applicant.birth_year", 1980, "1980"),   # would make ~45
        ])
        report = guard.validate(result)
        # Should have a cross-field warning
        cross_issues = [i for i in report.issues if i.check_type == "cross"]
        assert len(cross_issues) >= 1

    def test_consistent_income_monthly_annual_passes(self):
        result = make_result([
            make_ef("household.income_monthly", 12_000, "12000"),
            make_ef("household.income_annual", 144_000, "144000"),
        ])
        report = guard.validate(result)
        cross_issues = [i for i in report.issues if i.check_type == "cross"]
        assert len(cross_issues) == 0

    def test_inconsistent_income_warns(self):
        result = make_result([
            make_ef("household.income_monthly", 5_000, "5000"),
            make_ef("household.income_annual", 200_000, "200000"),  # 5000×12=60k ≠ 200k
        ])
        report = guard.validate(result)
        cross_issues = [i for i in report.issues if i.check_type == "cross"]
        assert len(cross_issues) >= 1


# ---------------------------------------------------------------------------
# ValidationReport properties
# ---------------------------------------------------------------------------

class TestValidationReport:
    def test_has_rejections(self):
        result = make_result([make_ef("applicant.age", 9999, "9999")])
        report = guard.validate(result)
        assert report.has_rejections is True

    def test_no_rejections(self):
        result = make_result([make_ef("applicant.age", 35, "35")])
        report = guard.validate(result)
        assert report.has_rejections is False

    def test_clarification_questions_on_rejection(self):
        result = make_result([make_ef("applicant.age", 999, "999 years")])
        report = guard.validate(result)
        assert len(report.get_clarification_questions()) >= 1

    def test_empty_extraction_passes(self):
        result = make_result([])
        report = guard.validate(result)
        assert report.has_rejections is False
        assert report.has_warnings is False
