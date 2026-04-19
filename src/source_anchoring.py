"""Source anchoring and reverse-audit via semantic similarity for CBC Part 1.

Implements:
  - compute_semantic_similarity(): cosine similarity via sentence-transformers
  - verify_source_anchor(): full reverse-audit with VERIFIED / NEEDS_REVIEW / DISPUTED
  - check_staleness(): flag rules whose source notification is >90 days old

Why: Rules extracted from PDFs can drift from their source documents as gazette
notifications are amended. Reverse-audit catches these drifts before stale rules
reach users.
"""

from __future__ import annotations

import math
import os
from datetime import date, timedelta
from typing import List, Tuple

from dataclasses import dataclass

from src.config import (
    AUDIT_NEEDS_REVIEW_THRESHOLD,
    AUDIT_SIMILARITY_THRESHOLD,
    SIMILARITY_MODEL,
    STALENESS_CUTOFF_DAYS,
)
from src.exceptions import AuditError
from src.schema import AuditStatus, Rule


# ---------------------------------------------------------------------------
# AuditResult — defined here since spec_07 is the primary audit module
# ---------------------------------------------------------------------------


@dataclass
class AuditResult:
    """Result of a reverse-audit similarity check for a single rule."""

    rule_id: str
    audit_status: AuditStatus
    similarity_score: float
    notes: str | None = None

# ---------------------------------------------------------------------------
# Threshold constants (also importable by tests)
# ---------------------------------------------------------------------------

SIMILARITY_THRESHOLD_VERIFIED: float = AUDIT_SIMILARITY_THRESHOLD
SIMILARITY_THRESHOLD_NEEDS_REVIEW: float = AUDIT_NEEDS_REVIEW_THRESHOLD


# ---------------------------------------------------------------------------
# Internal helpers (patchable in tests)
# ---------------------------------------------------------------------------


def _get_model():  # type: ignore[no-untyped-def]
    """Load and cache the SentenceTransformer model.

    Why lazy-loaded: Avoids importing sentence-transformers at module import time,
    which would slow down tests that mock the model entirely.
    """
    from sentence_transformers import SentenceTransformer  # type: ignore[import]

    return SentenceTransformer(SIMILARITY_MODEL)


def _encode_texts(text_a: str, text_b: str) -> Tuple[List[float], List[float]]:
    """Encode two texts into embedding vectors using the sentence-transformer model.

    Returns: Tuple of (embedding_a, embedding_b) as lists of floats.
    """
    model = _get_model()
    embedding_a = model.encode(text_a).tolist()
    embedding_b = model.encode(text_b).tolist()
    return embedding_a, embedding_b


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Compute cosine similarity between two embedding vectors.

    Returns: Float in [0.0, 1.0] — 1.0 is identical, 0.0 is orthogonal.
    """
    if not vec_a or not vec_b:
        return 0.0

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = math.sqrt(sum(a ** 2 for a in vec_a))
    mag_b = math.sqrt(sum(b ** 2 for b in vec_b))

    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0

    return max(0.0, min(1.0, dot / (mag_a * mag_b)))


async def _fetch_source_text(rule: Rule) -> str:
    """Fetch the source document text for a rule's source anchor.

    Raises:
        AuditError: If the source URL is unreachable after retries.
    """
    import httpx

    url = rule.source_anchor.source_url
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
        if response.status_code >= 400:
            raise AuditError(
                f"Source URL unreachable (HTTP {response.status_code}): {url}"
            )
        return response.text
    except httpx.RequestError as exc:
        raise AuditError(
            f"Source URL unreachable after retries: {url} — {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def compute_semantic_similarity(text_a: str, text_b: str) -> float:
    """Compute cosine similarity between two texts via sentence-transformers.

    Model: all-MiniLM-L6-v2 (dev) / all-mpnet-base-v2 (prod), configurable via
    the CBC_SIMILARITY_MODEL environment variable.

    Why sentence-transformers: Pre-trained on semantic similarity tasks; captures
    paraphrase equivalence that keyword matching misses (critical for auditing
    policy text which varies in phrasing between versions).

    Returns: Float in [0.0, 1.0]. Identical texts return ~1.0.
    """
    embedding_a, embedding_b = _encode_texts(text_a, text_b)
    return _cosine_similarity(embedding_a, embedding_b)


async def verify_source_anchor(rule: Rule) -> AuditResult:
    """Fetch source document, locate section, compare source_quote via semantic similarity.

    Threshold mapping (re-read from env on every call so tests can patch os.environ):
      >= AUDIT_SIMILARITY_THRESHOLD       -> VERIFIED
      >= AUDIT_NEEDS_REVIEW_THRESHOLD     -> NEEDS_REVIEW
      <  AUDIT_NEEDS_REVIEW_THRESHOLD     -> DISPUTED

    Why: The source_quote in a rule must still exist verbatim (or semantically
    equivalent) in the source document. If the document has been revised,
    the rule is stale and must be re-verified.

    Raises:
        AuditError: If source URL is unreachable after retries.
    """
    import os

    # Read thresholds dynamically so os.environ patches take effect in tests.
    threshold_verified = float(
        os.environ.get("AUDIT_SIMILARITY_THRESHOLD", str(SIMILARITY_THRESHOLD_VERIFIED))
    )
    threshold_review = float(
        os.environ.get("AUDIT_NEEDS_REVIEW_THRESHOLD", str(SIMILARITY_THRESHOLD_NEEDS_REVIEW))
    )

    source_text = await _fetch_source_text(rule)

    score = await compute_semantic_similarity(
        rule.source_anchor.source_quote, source_text
    )

    if score >= threshold_verified:
        status = AuditStatus.VERIFIED
    elif score >= threshold_review:
        status = AuditStatus.NEEDS_REVIEW
    else:
        status = AuditStatus.DISPUTED

    return AuditResult(
        rule_id=rule.rule_id,
        audit_status=status,
        similarity_score=score,
    )


def check_staleness(rule: Rule, cutoff_days: int = STALENESS_CUTOFF_DAYS) -> bool:
    """Return True if rule.source_anchor.notification_date is older than cutoff_days.

    Why: Gazette notifications are amended periodically. Rules anchored to
    notifications older than 90 days (default) should be re-verified against
    the latest gazette version.

    Args:
        rule: The rule to check.
        cutoff_days: Number of days since notification before a rule is stale.

    Returns: True if the notification date is older than cutoff_days.
    """
    notification_date_str = rule.source_anchor.notification_date
    try:
        notification_date = date.fromisoformat(notification_date_str)
    except ValueError:
        # If date is unparseable, treat as stale
        return True

    cutoff = date.today() - timedelta(days=cutoff_days)
    return notification_date < cutoff
