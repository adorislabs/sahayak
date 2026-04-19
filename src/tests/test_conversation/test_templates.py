"""Tests for src.conversation.templates."""

from __future__ import annotations

import pytest

from src.conversation.templates import (
    CLARIFYING,
    CONTRADICTION_DIRECT,
    ENDED,
    FIELD_LABELS,
    FIELD_QUESTION_MAP,
    FIELD_QUESTIONS,
    GATHERING_ACK,
    GREETING,
    MATCHING_STARTED,
    RESULT_ELIGIBLE_HEADER,
    WHAT_IF_HEADER,
    get_confidence_label,
    get_field_label,
    get_template,
)


class TestGetTemplate:
    """Test template retrieval and formatting."""

    def test_english_greeting(self) -> None:
        result = get_template(GREETING, "en")
        assert "👋" in result
        assert "Hello" in result

    def test_hindi_greeting(self) -> None:
        result = get_template(GREETING, "hi")
        assert "👋" in result
        assert "नमस्ते" in result

    def test_hinglish_falls_back_to_hindi(self) -> None:
        result = get_template(GREETING, "hinglish")
        assert "नमस्ते" in result  # Should use Hindi template

    def test_unknown_language_falls_back_to_english(self) -> None:
        result = get_template(GREETING, "fr")
        assert "Hello" in result

    def test_template_with_format_params(self) -> None:
        result = get_template(
            RESULT_ELIGIBLE_HEADER, "en", count=3
        )
        assert "3" in result
        assert "ELIGIBLE" in result

    def test_template_hindi_with_format_params(self) -> None:
        result = get_template(
            RESULT_ELIGIBLE_HEADER, "hi", count=5
        )
        assert "5" in result
        assert "पात्र" in result

    def test_template_with_missing_params_returns_raw(self) -> None:
        # Should not crash, returns raw template
        result = get_template(GATHERING_ACK, "en")
        assert "{extracted_summary}" in result or "Thanks" in result

    def test_what_if_header_format(self) -> None:
        result = get_template(
            WHAT_IF_HEADER, "en", description="Open bank account"
        )
        assert "Open bank account" in result

    def test_contradiction_dialog_format(self) -> None:
        result = get_template(
            CONTRADICTION_DIRECT, "en",
            field_label="Income",
            existing_value="₹2,00,000",
            new_value="₹3,00,000",
        )
        assert "₹2,00,000" in result
        assert "₹3,00,000" in result


class TestGetFieldLabel:
    """Test human-readable field label lookup."""

    def test_known_field_english(self) -> None:
        assert get_field_label("applicant.age", "en") == "Age"

    def test_known_field_hindi(self) -> None:
        assert get_field_label("applicant.age", "hi") == "उम्र"

    def test_known_field_hinglish_uses_hindi(self) -> None:
        assert get_field_label("location.state", "hinglish") == "राज्य"

    def test_unknown_field_returns_path(self) -> None:
        assert get_field_label("unknown.field", "en") == "unknown.field"

    def test_all_field_labels_have_both_languages(self) -> None:
        for field_path, labels in FIELD_LABELS.items():
            assert "en" in labels, f"{field_path} missing English label"
            assert "hi" in labels, f"{field_path} missing Hindi label"


class TestGetConfidenceLabel:
    """Test confidence score to human label mapping."""

    def test_high_confidence(self) -> None:
        label = get_confidence_label(0.92, "en")
        assert "High" in label

    def test_medium_confidence(self) -> None:
        label = get_confidence_label(0.75, "en")
        assert "Medium" in label

    def test_low_confidence(self) -> None:
        label = get_confidence_label(0.55, "en")
        assert "Low" in label

    def test_very_low_confidence(self) -> None:
        label = get_confidence_label(0.30, "en")
        assert "Very low" in label or "low" in label.lower()

    def test_boundary_085(self) -> None:
        label = get_confidence_label(0.85, "en")
        assert "High" in label

    def test_boundary_070(self) -> None:
        label = get_confidence_label(0.70, "en")
        assert "Medium" in label

    def test_boundary_050(self) -> None:
        label = get_confidence_label(0.50, "en")
        assert "Low" in label

    def test_hindi_confidence(self) -> None:
        label = get_confidence_label(0.45, "hi")
        assert "कम" in label


class TestFieldQuestions:
    """Test field question templates."""

    def test_questions_ordered_by_impact(self) -> None:
        impacts = [q["schemes_affected"] for q in FIELD_QUESTIONS]
        assert impacts == sorted(impacts, reverse=True)

    def test_all_questions_have_both_languages(self) -> None:
        for q in FIELD_QUESTIONS:
            assert "en" in q, f"{q['field']} missing English"
            assert "hi" in q, f"{q['field']} missing Hindi"
            assert "field" in q

    def test_question_map_has_all_fields(self) -> None:
        for q in FIELD_QUESTIONS:
            assert q["field"] in FIELD_QUESTION_MAP

    def test_minimum_question_count(self) -> None:
        assert len(FIELD_QUESTIONS) >= 10
