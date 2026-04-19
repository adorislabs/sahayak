"""Tests for src.conversation.contradiction."""

from __future__ import annotations

import pytest

from src.conversation.contradiction import (
    ContradictionFlag,
    build_resolution_dialog,
    detect_contradictions,
    detect_intra_message_contradictions,
    is_intentional_correction,
)


class TestCorrectionIntentDetection:
    """Test correction intent marker detection."""

    @pytest.mark.parametrize("msg", [
        "actually my income is 3 lakh",
        "wait, I meant 40 years old",
        "sorry, I'm from Bihar not UP",
        "correction: my age is 36",
        "no I meant to say OBC",
        "my mistake, it's 2 acres not 3",
    ])
    def test_english_corrections(self, msg: str) -> None:
        assert is_intentional_correction(msg)

    @pytest.mark.parametrize("msg", [
        "दरअसल मेरी उम्र 35 है",
        "रुकिए, मैं बिहार से हूँ",
        "माफ़ कीजिए, मेरा मतलब 3 लाख था",
        "गलती हो गई, SC नहीं OBC है",
    ])
    def test_hindi_corrections(self, msg: str) -> None:
        assert is_intentional_correction(msg)

    @pytest.mark.parametrize("msg", [
        "I am 35 years old",
        "My income is 2 lakh per year",
        "I live in UP",
    ])
    def test_non_corrections(self, msg: str) -> None:
        assert not is_intentional_correction(msg)


class TestDetectContradictions:
    """Test Type 1 (direct value) contradiction detection."""

    def test_no_contradictions_empty_profile(self) -> None:
        new = [{"field_path": "applicant.age", "value": 35}]
        flags = detect_contradictions(new, {}, {}, 1)
        assert flags == []

    def test_no_contradiction_same_value(self) -> None:
        new = [{"field_path": "applicant.age", "value": 35}]
        existing = {"applicant.age": 35}
        flags = detect_contradictions(new, existing, {}, 2)
        assert flags == []

    def test_direct_value_conflict(self) -> None:
        new = [{"field_path": "applicant.age", "value": 40, "source_span": "40 years"}]
        existing = {"applicant.age": 35}
        provenance = {
            "applicant.age": {"source_turn": 1, "source_text": "35 years"}
        }
        flags = detect_contradictions(new, existing, provenance, 2)
        assert len(flags) == 1
        assert flags[0].contradiction_type == 1
        assert flags[0].existing_value == 35
        assert flags[0].new_value == 40
        assert flags[0].severity == "blocking"

    def test_non_critical_field_is_warning(self) -> None:
        new = [{"field_path": "household.size", "value": 6}]
        existing = {"household.size": 4}
        flags = detect_contradictions(new, existing, {}, 2)
        assert len(flags) == 1
        assert flags[0].severity == "warning"

    def test_cross_field_income_inconsistency(self) -> None:
        new = [{"field_path": "household.income_annual", "value": 500000}]
        existing = {"household.income_monthly": 10000}
        flags = detect_contradictions(new, existing, {}, 2)
        # Monthly 10k × 12 = 120k, but annual is 500k → warning
        cross_field = [
            f for f in flags if f.contradiction_type == 4
        ]
        assert len(cross_field) >= 1


class TestIntraMessageContradictions:
    """Test Type 2 contradictions within a single message."""

    def test_age_birth_year_conflict(self) -> None:
        extractions = [
            {"field_path": "applicant.age", "value": 25},
            {"field_path": "applicant.birth_year", "value": 1990},
        ]
        flags = detect_intra_message_contradictions(extractions)
        assert len(flags) == 1
        assert flags[0].contradiction_type == 2
        assert flags[0].severity == "blocking"

    def test_age_birth_year_consistent(self) -> None:
        extractions = [
            {"field_path": "applicant.age", "value": 36},
            {"field_path": "applicant.birth_year", "value": 1990},
        ]
        flags = detect_intra_message_contradictions(extractions)
        assert flags == []

    def test_income_monthly_annual_conflict(self) -> None:
        extractions = [
            {"field_path": "household.income_monthly", "value": 10000},
            {"field_path": "household.income_annual", "value": 500000},
        ]
        flags = detect_intra_message_contradictions(extractions)
        assert len(flags) >= 1

    def test_no_contradiction_when_fields_absent(self) -> None:
        extractions = [
            {"field_path": "applicant.age", "value": 35},
        ]
        flags = detect_intra_message_contradictions(extractions)
        assert flags == []


class TestResolutionDialog:
    """Test resolution dialog generation."""

    def test_english_dialog(self) -> None:
        flag = ContradictionFlag(
            contradiction_id="test",
            contradiction_type=1,
            contradiction_type_name="direct_value_conflict",
            field_path="applicant.age",
            existing_value=35,
            new_value=40,
            existing_source_turn=1,
            new_source_turn=2,
            existing_source_text="35 years",
            new_source_text="40 years",
            severity="blocking",
        )
        dialog = build_resolution_dialog(flag, "en")
        assert "35" in dialog
        assert "40" in dialog

    def test_hindi_dialog(self) -> None:
        flag = ContradictionFlag(
            contradiction_id="test",
            contradiction_type=1,
            contradiction_type_name="direct_value_conflict",
            field_path="applicant.age",
            existing_value=35,
            new_value=40,
            existing_source_turn=1,
            new_source_turn=2,
            existing_source_text="35",
            new_source_text="40",
            severity="blocking",
        )
        dialog = build_resolution_dialog(flag, "hi")
        assert "35" in dialog
        assert "40" in dialog
