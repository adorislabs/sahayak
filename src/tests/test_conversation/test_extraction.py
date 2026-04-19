"""Tests for src.conversation.extraction — normalisation and field priority."""

from __future__ import annotations

import pytest

from src.conversation.extraction import (
    CASTE_ALIASES,
    STATE_ALIASES,
    ExtractionReasoning,
    ExtractionResult,
    ExtractedField,
    compute_field_priority,
    format_extraction_summary,
    normalize_value,
)


class TestNormalizeState:
    """Test state name/abbreviation normalisation."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("uttar pradesh", "UP"),
            ("Uttar Pradesh", "UP"),
            ("UP", "UP"),
            ("up", "UP"),
            ("उत्तर प्रदेश", "UP"),
            ("यूपी", "UP"),
            ("maharashtra", "MH"),
            ("MH", "MH"),
            ("महाराष्ट्र", "MH"),
            ("bihar", "BR"),
            ("बिहार", "BR"),
            ("rajasthan", "RJ"),
            ("kerala", "KL"),
            ("tamil nadu", "TN"),
            ("delhi", "DL"),
            ("दिल्ली", "DL"),
            ("west bengal", "WB"),
            ("jammu and kashmir", "JK"),
            ("ladakh", "LA"),
        ],
    )
    def test_state_normalisation(self, raw: str, expected: str) -> None:
        assert normalize_value("location.state", raw) == expected

    def test_unknown_state_passes_through(self) -> None:
        result = normalize_value("location.state", "Atlantis")
        assert result == "Atlantis"

    def test_state_aliases_coverage(self) -> None:
        # Must have at least 28 states + 8 UTs
        unique_codes = set(STATE_ALIASES.values())
        assert len(unique_codes) >= 28


class TestNormalizeCaste:
    """Test caste category normalisation."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("SC", "SC"),
            ("sc", "SC"),
            ("dalit", "SC"),
            ("Dalit", "SC"),
            ("scheduled caste", "SC"),
            ("ST", "ST"),
            ("adivasi", "ST"),
            ("tribal", "ST"),
            ("OBC", "OBC"),
            ("backward class", "OBC"),
            ("general", "GENERAL"),
            ("unreserved", "GENERAL"),
            ("EWS", "EWS"),
            ("दलित", "SC"),
            ("आदिवासी", "ST"),
            ("अनुसूचित जाति", "SC"),
            ("सामान्य", "GENERAL"),
        ],
    )
    def test_caste_normalisation(self, raw: str, expected: str) -> None:
        assert normalize_value("applicant.caste_category", raw) == expected


class TestNormalizeCurrency:
    """Test Indian currency normalisation."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            (200000, 200000),
            (150000.0, 150000),
            ("1.5 lakh", 150000),
            ("2 lakh", 200000),
            ("1.5 lac", 150000),
            ("3 लाख", 300000),
            ("1 crore", 10000000),
            ("5 thousand", 5000),
            ("10 hazar", 10000),
            ("₹50,000", 50000),
            ("250000", 250000),
        ],
    )
    def test_currency_normalisation(self, raw: object, expected: int) -> None:
        assert normalize_value("household.income_annual", raw) == expected

    def test_monthly_income_normalisation(self) -> None:
        assert normalize_value("household.income_monthly", "25 thousand") == 25000


class TestNormalizeLand:
    """Test land area normalisation."""

    def test_bigha_to_acres(self) -> None:
        assert normalize_value("household.land_acres", "2 bigha") == 1.24

    def test_bigha_hindi(self) -> None:
        assert normalize_value("household.land_acres", "3 बीघा") == 1.86

    def test_hectare_to_acres(self) -> None:
        assert normalize_value("household.land_acres", "1 hectare") == 2.47

    def test_acres_passthrough(self) -> None:
        assert normalize_value("household.land_acres", 3.5) == 3.5

    def test_plain_number(self) -> None:
        assert normalize_value("household.land_acres", "5") == 5.0


class TestNormalizeAge:
    """Test age normalisation."""

    def test_numeric_age(self) -> None:
        assert normalize_value("applicant.age", 35) == 35

    def test_string_age(self) -> None:
        assert normalize_value("applicant.age", "35 years") == 35

    def test_birth_year(self) -> None:
        # Born in 1990 → age should be ~36 in 2026
        result = normalize_value("applicant.age", "born in 1990")
        assert result == 36


class TestComputeFieldPriority:
    """Test follow-up question priority ordering."""

    def test_excludes_populated_fields(self) -> None:
        populated = {"applicant.age", "location.state"}
        result = compute_field_priority(populated, set(), set())
        fields = [fp for fp, _, _ in result]
        assert "applicant.age" not in fields
        assert "location.state" not in fields

    def test_excludes_asked_fields(self) -> None:
        result = compute_field_priority(
            set(), {"applicant.age"}, set()
        )
        fields = [fp for fp, _, _ in result]
        assert "applicant.age" not in fields

    def test_excludes_skipped_fields(self) -> None:
        result = compute_field_priority(
            set(), set(), {"applicant.age"}
        )
        fields = [fp for fp, _, _ in result]
        assert "applicant.age" not in fields

    def test_returns_tuples_with_both_languages(self) -> None:
        result = compute_field_priority(set(), set(), set())
        assert len(result) > 0
        fp, en, hi = result[0]
        assert isinstance(fp, str)
        assert isinstance(en, str)
        assert isinstance(hi, str)

    def test_empty_when_all_populated(self) -> None:
        from src.conversation.templates import FIELD_QUESTIONS
        all_fields = {q["field"] for q in FIELD_QUESTIONS}
        result = compute_field_priority(all_fields, set(), set())
        assert result == []


class TestFormatExtractionSummary:
    """Test the query → process → field explainability formatting."""

    def test_english_summary(self) -> None:
        chain = [
            ExtractionReasoning(
                source_span="35 year old",
                field_path="applicant.age",
                field_label="Age",
                value=35,
                raw_value="35 year old",
                confidence="HIGH",
                reasoning_note="Explicit age statement",
            ),
        ]
        result = format_extraction_summary(chain, "en")
        assert "35 year old" in result
        assert "Age" in result
        assert "35" in result
        assert "HIGH" in result

    def test_hindi_summary(self) -> None:
        chain = [
            ExtractionReasoning(
                source_span="35 साल",
                field_path="applicant.age",
                field_label="उम्र",
                value=35,
                raw_value="35 साल",
                confidence="HIGH",
                reasoning_note="",
            ),
        ]
        result = format_extraction_summary(chain, "hi")
        assert "उम्र" in result
        assert "उच्च" in result

    def test_empty_chain(self) -> None:
        result = format_extraction_summary([], "en")
        assert "No information" in result

    def test_empty_chain_hindi(self) -> None:
        result = format_extraction_summary([], "hi")
        assert "कोई जानकारी" in result


class TestExtractLastQuestions:
    """Test the conversation context helper for extraction."""

    def test_structured_questions(self) -> None:
        from src.conversation.extraction import _extract_last_questions
        history = [{
            "last_bot_questions": [
                {"field_path": "applicant.age", "question": "How old are you?", "index": 1},
                {"field_path": "documents.aadhaar", "question": "Do you have an Aadhaar card?", "index": 2},
            ],
            "system_response_en": "some response",
        }]
        result = _extract_last_questions(history)
        assert "How old are you?" in result
        assert "Aadhaar" in result
        assert "applicant.age" in result

    def test_fallback_to_numbered_lines(self) -> None:
        from src.conversation.extraction import _extract_last_questions
        history = [{
            "system_response_en": "Please answer:\n  1. How old are you?\n  2. What state?",
        }]
        result = _extract_last_questions(history)
        assert "How old are you?" in result
        assert "What state?" in result

    def test_empty_history(self) -> None:
        from src.conversation.extraction import _extract_last_questions
        assert _extract_last_questions([]) == ""

    def test_no_questions_in_turn(self) -> None:
        from src.conversation.extraction import _extract_last_questions
        history = [{"system_response_en": "Welcome! Tell me about yourself."}]
        result = _extract_last_questions(history)
        assert result == ""
