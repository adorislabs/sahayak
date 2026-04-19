"""Tests for src.conversation.presentation."""

from __future__ import annotations

import pytest

from src.conversation.presentation import (
    _extract_schemes,
    _generate_document_checklist,
    _generate_next_steps,
    render_scheme_detail,
    render_summary,
)


class TestRenderSummary:
    """Test the summary view rendering."""

    def test_empty_result(self) -> None:
        result = render_summary({}, "en")
        # Should not crash on empty data
        assert "═" in result  # separator present

    def test_eligible_schemes_shown(self) -> None:
        result_data = {
            "scheme_results": [
                {
                    "scheme_id": "s1",
                    "scheme_name": "PM Kisan",
                    "status": "ELIGIBLE",
                    "confidence": 0.92,
                },
                {
                    "scheme_id": "s2",
                    "scheme_name": "MGNREGA",
                    "status": "NEAR_MISS",
                    "confidence": 0.65,
                    "gap_summary": "Missing MGNREGA job card",
                },
            ]
        }
        text = render_summary(result_data, "en")
        assert "PM Kisan" in text
        assert "ELIGIBLE" in text
        assert "MGNREGA" in text
        assert "ALMOST ELIGIBLE" in text or "NEAR" in text

    def test_hindi_rendering(self) -> None:
        result_data = {
            "scheme_results": [
                {
                    "scheme_id": "s1",
                    "scheme_name": "पीएम किसान",
                    "status": "ELIGIBLE",
                    "confidence": 0.90,
                },
            ]
        }
        text = render_summary(result_data, "hi")
        assert "पात्र" in text
        assert "पीएम किसान" in text


class TestRenderSchemeDetail:
    """Test the detail view rendering."""

    def test_basic_detail(self) -> None:
        scheme = {
            "name": "PM Kisan",
            "status": "ELIGIBLE",
            "confidence": 0.92,
        }
        text = render_scheme_detail(scheme, "en")
        assert "PM Kisan" in text
        assert "92%" in text
        assert "High" in text

    def test_low_confidence_warning(self) -> None:
        scheme = {
            "name": "Test Scheme",
            "status": "NEAR_MISS",
            "confidence": 0.40,
        }
        text = render_scheme_detail(scheme, "en")
        assert "40%" in text
        assert "not confident" in text.lower() or "low" in text.lower()

    def test_with_rule_evaluations(self) -> None:
        scheme = {
            "name": "Test",
            "status": "ELIGIBLE",
            "confidence": 0.85,
            "rule_evaluations": [
                {"description": "Age >= 18", "passed": True},
                {"description": "Income < 2.5L", "passed": False},
            ],
        }
        text = render_scheme_detail(scheme, "en")
        assert "✅" in text
        assert "❌" in text
        assert "Age >= 18" in text


class TestExtractSchemes:
    """Test scheme extraction from various result formats."""

    def test_scheme_results_format(self) -> None:
        data = {
            "scheme_results": [
                {"scheme_id": "s1", "scheme_name": "A", "status": "ELIGIBLE", "confidence": 0.9},
                {"scheme_id": "s2", "scheme_name": "B", "status": "INELIGIBLE", "confidence": 0.1},
            ]
        }
        schemes = _extract_schemes(data)
        assert len(schemes) == 2
        # Should be sorted: ELIGIBLE before INELIGIBLE
        assert schemes[0]["status"] == "ELIGIBLE"
        assert schemes[1]["status"] == "INELIGIBLE"

    def test_empty_data(self) -> None:
        assert _extract_schemes({}) == []


class TestGenerateNextSteps:
    """Test next steps generation."""

    def test_apply_now_for_eligible(self) -> None:
        eligible = [{"name": "PM Kisan", "action": "Apply at nearest CSC"}]
        steps = _generate_next_steps(eligible, [], "en")
        assert any("PM Kisan" in s for s in steps)

    def test_near_miss_gap_action(self) -> None:
        near_miss = [{"name": "MGNREGA", "gap": "Get a job card"}]
        steps = _generate_next_steps([], near_miss, "en")
        assert any("MGNREGA" in s for s in steps)


class TestGenerateDocumentChecklist:
    """Test document checklist generation."""

    def test_dedup_documents(self) -> None:
        schemes = [
            {"required_documents": ["Aadhaar", "Bank passbook"]},
            {"required_documents": ["Aadhaar", "Income certificate"]},
        ]
        docs = _generate_document_checklist(schemes, "en")
        # Aadhaar should appear once with count 2
        aadhaar_lines = [d for d in docs if "Aadhaar" in d]
        assert len(aadhaar_lines) == 1
        assert "2" in aadhaar_lines[0]

    def test_max_six_documents(self) -> None:
        schemes = [
            {"required_documents": [f"Doc {i}" for i in range(20)]},
        ]
        docs = _generate_document_checklist(schemes, "en")
        assert len(docs) <= 6
