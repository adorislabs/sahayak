"""Shared fixtures and configuration for the CBC Part 1 test suite."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Anchor fixture data — mirrored from docs/part1-planning/tests/fixtures/
# ---------------------------------------------------------------------------

ANCHOR_PMKISAN_2023: dict[str, Any] = {
    "source_url": "https://pmkisan.gov.in/documents/operational_guidelines_2023.pdf",
    "document_title": "PM-KISAN Operational Guidelines (Revised November 2023)",
    "source_quote": (
        "All landholding farmer families, which have the cultivable land as per land "
        "records of the concerned State/UT, will get income support of ₹6000/- per year"
    ),
    "page_number": 4,
    "section": "3. Eligibility Criteria",
    "clause": "3.1",
    "gazette_ref": "G.S.R. 119(E) dated 01-02-2019",
    "notification_date": "2023-11-15",
    "language": "en",
    "alternate_language_ref": "https://pmkisan.gov.in/documents/hindi_guidelines_2023.pdf",
}

ANCHOR_PMSYM_2019: dict[str, Any] = {
    "source_url": "https://labour.gov.in/sites/default/files/pmsym_guidelines_2019.pdf",
    "document_title": "PM Shram Yogi Maandhan — Scheme Guidelines 2019",
    "source_quote": (
        "The subscriber should not be a member of EPFO/ESIC or NPS (statutory social security "
        "schemes) governed by Central Government"
    ),
    "page_number": 2,
    "section": "4. Exclusion Criteria",
    "notification_date": "2019-02-15",
    "language": "en",
}

RULE_PMKISAN_R001_DICT: dict[str, Any] = {
    "rule_id": "PMKISAN-R001",
    "scheme_id": "PMKISAN",
    "rule_type": "eligibility",
    "condition_type": "land_ownership",
    "field": "applicant.land_ownership_status",
    "operator": "EQ",
    "value": True,
    "unit": None,
    "logic_group": "PMKISAN-GROUP-A",
    "logic_operator": "AND",
    "prerequisite_scheme_ids": [],
    "state_scope": "central",
    "source_anchor": ANCHOR_PMKISAN_2023,
    "ambiguity_flags": [],
    "confidence": 0.95,
    "audit_status": "PENDING",
    "verified_by": None,
    "parse_run_id": "RUN-2026-001",
    "version": "2.1.0",
    "effective_from": "2019-02-01",
    "supersedes_rule_id": None,
    "display_text": "Applicant must own cultivable agricultural land as per state land records",
    "notes": None,
}

RULE_PMSYM_R001_DICT: dict[str, Any] = {
    "rule_id": "PMSYM-R001",
    "scheme_id": "PMSYM",
    "rule_type": "eligibility",
    "condition_type": "age_range",
    "field": "applicant.age",
    "operator": "BETWEEN",
    "value": None,
    "value_min": 18.0,
    "value_max": 40.0,
    "unit": "years",
    "state_scope": "central",
    "source_anchor": {
        "source_url": "https://labour.gov.in/sites/default/files/pmsym_guidelines_2019.pdf",
        "document_title": "PM Shram Yogi Maandhan — Scheme Guidelines 2019",
        "source_quote": "Unorganised Workers in the age group of 18-40 years",
        "page_number": 1,
        "section": "2. Eligibility Criteria",
        "notification_date": "2019-02-15",
        "language": "en",
    },
    "confidence": 0.98,
    "audit_status": "PENDING",
    "parse_run_id": "RUN-2026-001",
    "version": "1.0.0",
    "display_text": "Applicant must be between 18 and 40 years of age at date of enrolment",
}

RULE_PMSYM_DIS001_DICT: dict[str, Any] = {
    "rule_id": "PMSYM-DIS001",
    "scheme_id": "PMSYM",
    "rule_type": "disqualifying",
    "condition_type": "scheme_enrollment",
    "field": "enrollment.epfo",
    "operator": "NOT_MEMBER",
    "value": None,
    "values": ["EPFO", "NPS", "ESIC"],
    "unit": None,
    "state_scope": "central",
    "source_anchor": ANCHOR_PMSYM_2019,
    "confidence": 0.99,
    "audit_status": "PENDING",
    "parse_run_id": "RUN-2026-001",
    "version": "1.0.0",
    "display_text": "Applicant must NOT be a member of EPFO, NPS, or ESIC",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def mock_http_client() -> AsyncMock:
    """Mock httpx.AsyncClient scoped per-test."""
    client = AsyncMock()
    return client


@pytest.fixture
def mock_sentence_transformer() -> MagicMock:
    """Mock SentenceTransformer with deterministic embeddings."""
    mock = MagicMock()
    mock.encode.return_value = [0.1, 0.2, 0.3]
    return mock


@pytest_asyncio.fixture
async def mock_playwright_browser() -> AsyncMock:
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.content = AsyncMock(return_value="<html><section id='eligibility'>Eligible residents apply here.</section></html>")
    return mock_page


@pytest.fixture
def valid_rule_pmkisan():  # type: ignore[no-untyped-def]
    """Return a valid Rule object for PMKISAN-R001."""
    from src.schema import Rule  # type: ignore[import]

    return Rule(**RULE_PMKISAN_R001_DICT)


@pytest.fixture
def valid_rule_pmsym():  # type: ignore[no-untyped-def]
    """Return a valid Rule object for PMSYM-R001 (BETWEEN)."""
    from src.schema import Rule  # type: ignore[import]

    return Rule(**RULE_PMSYM_R001_DICT)


@pytest.fixture
def valid_anchor_pmkisan():  # type: ignore[no-untyped-def]
    from src.schema import SourceAnchor  # type: ignore[import]

    return SourceAnchor(**ANCHOR_PMKISAN_2023)


@pytest.fixture
def valid_source_anchor_dict() -> dict[str, Any]:
    return {
        "source_url": "https://pmkisan.gov.in/guidelines.pdf",
        "document_title": "PM-KISAN Operational Guidelines 2023",
        "source_quote": "All landholding farmer families...",
        "section": "3.2 Eligibility Criteria",
        "notification_date": "2023-11-15",
        "language": "en",
    }


@pytest.fixture
def fresh_rule_dict(valid_source_anchor_dict: dict[str, Any]) -> dict[str, Any]:
    """Return a minimal valid Rule dict ready for Rule(**...)."""
    return {
        "rule_id": "TEST-R001",
        "scheme_id": "TEST",
        "rule_type": "eligibility",
        "condition_type": "age_range",
        "field": "applicant.age",
        "operator": "EQ",
        "value": 18,
        "source_anchor": valid_source_anchor_dict,
        "confidence": 0.90,
        "parse_run_id": "RUN-TEST-001",
        "display_text": "Applicant must be 18 years of age",
    }


@pytest.fixture
def old_rule_dict(valid_source_anchor_dict: dict[str, Any]) -> dict[str, Any]:
    """Rule with a notification_date > 90 days ago."""
    old_date = (date.today() - timedelta(days=120)).isoformat()
    return {
        **RULE_PMKISAN_R001_DICT,
        "source_anchor": {**ANCHOR_PMKISAN_2023, "notification_date": old_date},
    }


@pytest.fixture
def recent_rule_dict(valid_source_anchor_dict: dict[str, Any]) -> dict[str, Any]:
    """Rule with a notification_date within the last 30 days."""
    recent_date = (date.today() - timedelta(days=30)).isoformat()
    return {
        **RULE_PMKISAN_R001_DICT,
        "source_anchor": {**ANCHOR_PMKISAN_2023, "notification_date": recent_date},
    }
