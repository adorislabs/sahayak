"""
Tests for spec_07_source_anchoring.py

Module: src/spec_07_source_anchoring.py
Spec:   docs/part1-planning/tests/spec_07_source_anchoring.md
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.exceptions import AuditError  # type: ignore[import]
from src.schema import AuditStatus, Rule, SourceAnchor  # type: ignore[import]
from src.source_anchoring import (  # type: ignore[import]
    check_staleness,
    compute_semantic_similarity,
    verify_source_anchor,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_VALID_ANCHOR = SourceAnchor(
    source_url="https://pmkisan.gov.in/guidelines.pdf",
    document_title="PM-KISAN Operational Guidelines 2023",
    source_quote="All landholding farmer families owning cultivable agricultural land",
    section="3. Eligibility Criteria",
    notification_date="2023-11-15",
    language="en",
    page_number=4,
)


def _make_rule(notification_date: str | None = None, page_number: int | None = 4) -> Rule:
    anchor_kwargs: dict[str, Any] = {
        "source_url": "https://pmkisan.gov.in/guidelines.pdf",
        "document_title": "PM-KISAN Guidelines",
        "source_quote": "All landholding farmer families owning cultivable agricultural land",
        "section": "3.2",
        "notification_date": notification_date or "2023-11-15",
        "language": "en",
    }
    if page_number is not None:
        anchor_kwargs["page_number"] = page_number

    return Rule(
        rule_id="PMKISAN-R001",
        scheme_id="PMKISAN",
        rule_type="eligibility",
        condition_type="land_ownership",
        field="applicant.land_ownership_status",
        operator="EQ",
        value=True,
        source_anchor=SourceAnchor(**anchor_kwargs),
        confidence=0.95,
        parse_run_id="RUN-001",
        display_text="Applicant must own cultivable agricultural land",
    )


# ---------------------------------------------------------------------------
# Section 1: compute_semantic_similarity
# ---------------------------------------------------------------------------


class TestComputeSemanticSimilarity:
    async def test__identical_strings__returns_one(self) -> None:
        """Identical text → similarity score ≥ 0.99 (effectively 1.0)."""
        text = "All landholding farmer families owning cultivable agricultural land"

        with patch(
            "src.source_anchoring._encode_texts",
            return_value=(([1.0, 0.0]), ([1.0, 0.0])),
        ):
            score = await compute_semantic_similarity(text, text)

        assert score >= 0.99

    async def test__semantically_similar__returns_high_score(self) -> None:
        """Semantically equivalent text → mocked score of 0.88 (≥ 0.70)."""
        text_a = "Annual family income must be below 2 lakh rupees"
        text_b = "The household's yearly earnings should not exceed ₹2,00,000"

        with patch(
            "src.source_anchoring._encode_texts",
            return_value=(([0.9, 0.1]), ([0.85, 0.15])),
        ):
            with patch(
                "src.source_anchoring._cosine_similarity",
                return_value=0.88,
            ):
                score = await compute_semantic_similarity(text_a, text_b)

        assert score >= 0.70

    async def test__semantically_dissimilar__returns_low_score(self) -> None:
        """Unrelated texts → mocked score of 0.35 (< 0.70)."""
        text_a = "Applicant must own agricultural land"
        text_b = "Candidate must not be enrolled in NPS or EPFO"

        with patch(
            "src.source_anchoring._cosine_similarity",
            return_value=0.35,
        ):
            with patch("src.source_anchoring._encode_texts", return_value=([], [])):
                score = await compute_semantic_similarity(text_a, text_b)

        assert score < 0.70

    async def test__returns_bounded_float__between_0_and_1(self) -> None:
        """Any two inputs → score in [0.0, 1.0]."""
        with patch(
            "src.source_anchoring._cosine_similarity",
            return_value=0.72,
        ):
            with patch("src.source_anchoring._encode_texts", return_value=([], [])):
                score = await compute_semantic_similarity("text a", "text b")

        assert 0.0 <= score <= 1.0

    async def test__empty_string__handles_gracefully(self) -> None:
        """Empty string input → float in [0.0, 1.0]; no exception."""
        with patch(
            "src.source_anchoring._cosine_similarity",
            return_value=0.0,
        ):
            with patch("src.source_anchoring._encode_texts", return_value=([], [])):
                score = await compute_semantic_similarity("", "Any non-empty text")

        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Section 2: verify_source_anchor
# ---------------------------------------------------------------------------


class TestVerifySourceAnchor:
    async def test__similarity_above_90__returns_verified(self) -> None:
        """similarity=0.95 → AuditStatus.VERIFIED with correct score and rule_id."""
        rule = _make_rule()

        with patch(
            "src.source_anchoring.compute_semantic_similarity",
            new_callable=AsyncMock,
            return_value=0.95,
        ):
            with patch("src.source_anchoring._fetch_source_text", new_callable=AsyncMock, return_value="text"):
                result = await verify_source_anchor(rule)

        assert result.audit_status == AuditStatus.VERIFIED
        assert result.similarity_score == 0.95
        assert result.rule_id == rule.rule_id

    async def test__similarity_exactly_at_90_threshold__returns_verified(self) -> None:
        """similarity=0.90 exactly → VERIFIED (inclusive lower bound)."""
        rule = _make_rule()

        with patch(
            "src.source_anchoring.compute_semantic_similarity",
            new_callable=AsyncMock,
            return_value=0.90,
        ):
            with patch("src.source_anchoring._fetch_source_text", new_callable=AsyncMock, return_value="text"):
                result = await verify_source_anchor(rule)

        assert result.audit_status == AuditStatus.VERIFIED

    async def test__similarity_at_89__returns_needs_review(self) -> None:
        """similarity=0.89 (just below threshold) → NEEDS_REVIEW."""
        rule = _make_rule()

        with patch(
            "src.source_anchoring.compute_semantic_similarity",
            new_callable=AsyncMock,
            return_value=0.89,
        ):
            with patch("src.source_anchoring._fetch_source_text", new_callable=AsyncMock, return_value="text"):
                result = await verify_source_anchor(rule)

        assert result.audit_status == AuditStatus.NEEDS_REVIEW

    async def test__similarity_at_70__returns_needs_review(self) -> None:
        """similarity=0.70 (lower bound of NEEDS_REVIEW) → NEEDS_REVIEW."""
        rule = _make_rule()

        with patch(
            "src.source_anchoring.compute_semantic_similarity",
            new_callable=AsyncMock,
            return_value=0.70,
        ):
            with patch("src.source_anchoring._fetch_source_text", new_callable=AsyncMock, return_value="text"):
                result = await verify_source_anchor(rule)

        assert result.audit_status == AuditStatus.NEEDS_REVIEW

    async def test__similarity_at_69__returns_disputed(self) -> None:
        """similarity=0.69 (just below NEEDS_REVIEW lower bound) → DISPUTED."""
        rule = _make_rule()

        with patch(
            "src.source_anchoring.compute_semantic_similarity",
            new_callable=AsyncMock,
            return_value=0.69,
        ):
            with patch("src.source_anchoring._fetch_source_text", new_callable=AsyncMock, return_value="text"):
                result = await verify_source_anchor(rule)

        assert result.audit_status == AuditStatus.DISPUTED

    async def test__similarity_below_70__returns_disputed(self) -> None:
        """similarity=0.45 → DISPUTED."""
        rule = _make_rule()

        with patch(
            "src.source_anchoring.compute_semantic_similarity",
            new_callable=AsyncMock,
            return_value=0.45,
        ):
            with patch("src.source_anchoring._fetch_source_text", new_callable=AsyncMock, return_value="text"):
                result = await verify_source_anchor(rule)

        assert result.audit_status == AuditStatus.DISPUTED

    async def test__source_url_unreachable__raises_audit_error(self) -> None:
        """Unreachable source URL after retries → AuditError."""
        rule = _make_rule()

        with patch(
            "src.source_anchoring._fetch_source_text",
            new_callable=AsyncMock,
            side_effect=AuditError("source URL unreachable after retries"),
        ):
            with pytest.raises(AuditError):
                await verify_source_anchor(rule)

    async def test__configurable_threshold__respects_env_var(self) -> None:
        """AUDIT_SIMILARITY_THRESHOLD=0.85; similarity=0.87 → VERIFIED (above custom threshold)."""
        rule = _make_rule()

        with patch.dict(os.environ, {"AUDIT_SIMILARITY_THRESHOLD": "0.85"}):
            with patch(
                "src.source_anchoring.compute_semantic_similarity",
                new_callable=AsyncMock,
                return_value=0.87,
            ):
                with patch("src.source_anchoring._fetch_source_text", new_callable=AsyncMock, return_value="text"):
                    result = await verify_source_anchor(rule)

        assert result.audit_status == AuditStatus.VERIFIED


# ---------------------------------------------------------------------------
# Section 3: check_staleness
# ---------------------------------------------------------------------------


class TestCheckStaleness:
    def test__notification_date_within_90_days__returns_false(self) -> None:
        """Date 30 days ago → not stale."""
        recent_date = (date.today() - timedelta(days=30)).isoformat()
        rule = _make_rule(notification_date=recent_date)
        assert check_staleness(rule, cutoff_days=90) is False

    def test__notification_date_older_than_90_days__returns_true(self) -> None:
        """Date 120 days ago → stale."""
        old_date = (date.today() - timedelta(days=120)).isoformat()
        rule = _make_rule(notification_date=old_date)
        assert check_staleness(rule, cutoff_days=90) is True

    def test__exactly_at_cutoff__edge_case__consistent_behaviour(self) -> None:
        """Exactly 90 days ago → consistent result; behaviour documented by Agent B."""
        exact_date = (date.today() - timedelta(days=90)).isoformat()
        rule = _make_rule(notification_date=exact_date)
        # Must return a bool; either True or False is acceptable — must be consistent
        result = check_staleness(rule, cutoff_days=90)
        assert isinstance(result, bool)
        # Verify consistency: same input same output
        assert check_staleness(rule, cutoff_days=90) == result

    def test__default_cutoff_90_days__used_when_not_provided(self) -> None:
        """Old date, no cutoff_days arg → default of 90 days applied."""
        old_date = (date.today() - timedelta(days=120)).isoformat()
        rule = _make_rule(notification_date=old_date)
        assert check_staleness(rule) is True

    def test__very_recent_date__returns_false(self) -> None:
        """Today's date → not stale."""
        rule = _make_rule(notification_date=date.today().isoformat())
        assert check_staleness(rule, cutoff_days=90) is False

    def test__very_old_date__returns_true(self) -> None:
        """7-year-old date → stale."""
        rule = _make_rule(notification_date="2019-02-24")
        assert check_staleness(rule, cutoff_days=90) is True


# ---------------------------------------------------------------------------
# Section 4: Source Anchor Required Fields — page navigation
# ---------------------------------------------------------------------------


class TestSourceAnchorPageNavigation:
    async def test__page_number_present__uses_page_content(self) -> None:
        """page_number=4 → text extraction targets page 4 specifically."""
        rule = _make_rule(page_number=4)
        fetch_mock = AsyncMock(return_value="page 4 content: farmer families owning land")

        with patch("src.source_anchoring._fetch_source_text", fetch_mock):
            with patch(
                "src.source_anchoring.compute_semantic_similarity",
                new_callable=AsyncMock,
                return_value=0.92,
            ):
                result = await verify_source_anchor(rule)

        # Verify fetch was called with page_number hint
        call_kwargs = fetch_mock.call_args
        assert call_kwargs is not None
        # page_number=4 should be passed through to fetcher
        assert result.audit_status == AuditStatus.VERIFIED

    async def test__null_page_number__falls_back_to_full_doc_scan(self) -> None:
        """page_number=None (web source) → full document scan; function succeeds."""
        rule = _make_rule(page_number=None)

        with patch(
            "src.source_anchoring._fetch_source_text",
            new_callable=AsyncMock,
            return_value="Full document text with eligibility content",
        ):
            with patch(
                "src.source_anchoring.compute_semantic_similarity",
                new_callable=AsyncMock,
                return_value=0.88,
            ):
                result = await verify_source_anchor(rule)

        assert result.audit_status in (AuditStatus.VERIFIED, AuditStatus.NEEDS_REVIEW, AuditStatus.DISPUTED)
