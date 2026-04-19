"""Tests for src.conversation.what_if."""

from __future__ import annotations

import pytest

from src.conversation.what_if import (
    FieldChange,
    SchemeStatusChange,
    WhatIfComparison,
    WhatIfModification,
    WhatIfSuggestion,
    _compare_results,
    _extract_scheme_statuses,
    format_what_if_comparison,
    generate_what_if_suggestions,
)


class TestCompareResults:
    """Test the result comparison logic."""

    def test_gained_scheme(self) -> None:
        current = {
            "scheme_results": [
                {"scheme_id": "s1", "scheme_name": "Scheme 1", "status": "INELIGIBLE", "confidence": 0.0},
            ]
        }
        what_if = {
            "scheme_results": [
                {"scheme_id": "s1", "scheme_name": "Scheme 1", "status": "ELIGIBLE", "confidence": 0.9},
            ]
        }
        mod = WhatIfModification(
            modification_id="test",
            description="Open bank account",
            field_changes=[],
            source_text="what if I open a bank account",
        )
        comp = _compare_results(current, what_if, mod)
        assert comp.net_impact == "positive"
        assert len(comp.schemes_gained) == 1
        assert comp.schemes_gained[0].scheme_name == "Scheme 1"

    def test_lost_scheme(self) -> None:
        current = {
            "scheme_results": [
                {"scheme_id": "s1", "scheme_name": "Scheme 1", "status": "ELIGIBLE", "confidence": 0.9},
            ]
        }
        what_if = {
            "scheme_results": [
                {"scheme_id": "s1", "scheme_name": "Scheme 1", "status": "INELIGIBLE", "confidence": 0.0},
            ]
        }
        mod = WhatIfModification(
            modification_id="test",
            description="Test",
            field_changes=[],
            source_text="",
        )
        comp = _compare_results(current, what_if, mod)
        assert comp.net_impact == "negative"
        assert len(comp.schemes_lost) == 1

    def test_no_change(self) -> None:
        current = {
            "scheme_results": [
                {"scheme_id": "s1", "scheme_name": "Scheme 1", "status": "ELIGIBLE", "confidence": 0.9},
            ]
        }
        mod = WhatIfModification(
            modification_id="test",
            description="Test",
            field_changes=[],
            source_text="",
        )
        comp = _compare_results(current, current, mod)
        assert comp.net_impact == "neutral"
        assert comp.schemes_unchanged == 1

    def test_empty_results(self) -> None:
        mod = WhatIfModification(
            modification_id="test",
            description="Test",
            field_changes=[],
            source_text="",
        )
        comp = _compare_results({}, {}, mod)
        assert comp.net_impact == "neutral"
        assert comp.schemes_unchanged == 0


class TestExtractSchemeStatuses:
    """Test scheme status extraction from various result formats."""

    def test_scheme_results_key(self) -> None:
        result = {
            "scheme_results": [
                {"scheme_id": "s1", "status": "ELIGIBLE", "confidence": 0.9, "scheme_name": "Test"},
            ]
        }
        statuses = _extract_scheme_statuses(result)
        assert "s1" in statuses
        assert statuses["s1"]["status"] == "ELIGIBLE"

    def test_determinations_key(self) -> None:
        result = {
            "determinations": [
                {"id": "s1", "determination": "NEAR_MISS", "composite_confidence": 0.7, "name": "Test"},
            ]
        }
        statuses = _extract_scheme_statuses(result)
        assert "s1" in statuses
        assert statuses["s1"]["status"] == "NEAR_MISS"

    def test_empty_result(self) -> None:
        statuses = _extract_scheme_statuses({})
        assert statuses == {}


class TestFormatWhatIfComparison:
    """Test user-facing What If formatting."""

    def test_positive_impact_english(self) -> None:
        comp = WhatIfComparison(
            modification=WhatIfModification(
                modification_id="test",
                description="Open bank account",
                field_changes=[],
                source_text="",
            ),
            current_eligible_count=2,
            what_if_eligible_count=4,
            schemes_gained=[
                SchemeStatusChange(
                    scheme_id="s1",
                    scheme_name="PM Kisan",
                    old_status="INELIGIBLE",
                    new_status="ELIGIBLE",
                    old_confidence=0.0,
                    new_confidence=0.85,
                    change_reason="Bank account required",
                ),
            ],
            net_impact="positive",
        )
        text = format_what_if_comparison(comp, "en")
        assert "Open bank account" in text
        assert "POSITIVE" in text
        assert "PM Kisan" in text

    def test_neutral_impact_hindi(self) -> None:
        comp = WhatIfComparison(
            modification=WhatIfModification(
                modification_id="test",
                description="Test",
                field_changes=[],
                source_text="",
            ),
            net_impact="neutral",
        )
        text = format_what_if_comparison(comp, "hi")
        assert "कोई बदलाव नहीं" in text


class TestGenerateSuggestions:
    """Test smart suggestion generation."""

    def test_suggests_bank_account(self) -> None:
        profile = {"applicant.age": 35, "location.state": "UP"}
        # No bank account → should suggest opening one
        suggestions = generate_what_if_suggestions({}, profile)
        descriptions = [s.description for s in suggestions]
        assert any("bank" in d.lower() for d in descriptions)

    def test_no_duplicate_suggestions(self) -> None:
        profile = {"documents.bank_account": True}
        suggestions = generate_what_if_suggestions({}, profile)
        # Should NOT suggest bank account since already has one
        descriptions = [s.description for s in suggestions]
        assert not any("bank account" in d.lower() for d in descriptions)

    def test_max_three_suggestions(self) -> None:
        suggestions = generate_what_if_suggestions({}, {})
        assert len(suggestions) <= 3

    def test_suggestions_sorted_by_impact(self) -> None:
        suggestions = generate_what_if_suggestions({}, {})
        if len(suggestions) >= 2:
            assert (
                suggestions[0].affected_schemes_count
                >= suggestions[1].affected_schemes_count
            )
