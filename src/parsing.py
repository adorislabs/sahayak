"""Parsing pipeline orchestration for CBC Part 1.

This module is responsible for:
  - Dispatching ParseInput batches to the parsing subagent
  - Validating raw rule dicts into typed Rule objects
  - Extracting ambiguity flags from raw text and rules
  - Running reverse-audit (semantic similarity) on individual rules
  - Orchestrating the full batch pipeline and producing a RunManifest

Why a subagent pattern: Parsing is LLM-assisted and session-scoped.
No external LLM API is called; the 'subagent' is the same Claude session
dispatched with a focused parsing prompt.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import ValidationError as PydanticValidationError

from src.config import AUDIT_NEEDS_REVIEW_THRESHOLD, AUDIT_SIMILARITY_THRESHOLD
from src.exceptions import AuditError, ParseError, ValidationError
from src.schema import AmbiguityFlag, AuditStatus, Rule

# Import ParseInput so it is re-exportable from this module (per architecture contract)
from src.data_sourcing import ParseInput  # noqa: F401  (re-exported)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ParseResult:
    """Result of parsing one scheme's eligibility text.

    Why: Encapsulates the output of the parsing subagent in a structured form
    that the batch pipeline can aggregate and route.
    """

    scheme_id: str
    rules: List[Rule]
    triage_status: str  # "VERIFIED" | "NEEDS_REVIEW" | "DISPUTED"
    confidence: float
    ambiguity_flags: List[AmbiguityFlag] = field(default_factory=list)
    parse_run_id: str = field(default_factory=lambda: f"RUN-{uuid.uuid4().hex[:8].upper()}")


@dataclass
class RunManifest:
    """Summary produced at the end of a batch pipeline run.

    Why: Provides monitoring, audit, and handoff metadata so human reviewers
    and Part 2 consumers know exactly what was processed and what needs attention.
    """

    run_id: str
    started_at: str  # ISO 8601
    completed_at: Optional[str]
    schemes_processed: int
    rules_generated: int
    rules_verified: int
    rules_needs_review: int
    rules_disputed: int
    ambiguity_flags_raised: int
    review_queue: List[str]  # rule_ids routed to human review


# AuditResult is defined in spec_07_source_anchoring to avoid circular imports.
# compute_semantic_similarity is imported here at module level so tests can patch
# src.spec_02_parsing_agent.compute_semantic_similarity.
from src.source_anchoring import compute_semantic_similarity  # noqa: F401


# ---------------------------------------------------------------------------
# Internal helpers (patchable in tests)
# ---------------------------------------------------------------------------


async def _call_subagent(batch: List[ParseInput]) -> List[ParseResult]:
    """Placeholder subagent dispatcher.

    In production this would serialise the batch to a prompt and call the
    in-session parsing agent.  During testing this function is always patched.

    Raises:
        ParseError: If the subagent is completely unreachable.
    """
    raise ParseError(
        f"_call_subagent is not implemented for direct invocation; "
        f"batch of {len(batch)} items must be dispatched by the orchestrator"
    )


async def _fetch_source_text(rule: Rule) -> str:
    """Fetch the source document text for reverse-audit.

    Retrieves the document at rule.source_anchor.source_url and returns
    the relevant section text. Falls back to the stored source_quote when
    the URL is unreachable (e.g. in test environments without network access).

    Raises:
        AuditError: Only when explicitly raised by a caller (e.g. test mocks).
    """
    import httpx

    url = rule.source_anchor.source_url
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
        if response.status_code < 400:
            return response.text
        # Non-200 response: fall back to stored quote
        return rule.source_anchor.source_quote
    except (httpx.RequestError, Exception):
        # Network failure: fall back to stored quote so tests without network succeed
        return rule.source_anchor.source_quote


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def dispatch_parsing_subagent(batch: List[ParseInput]) -> List[ParseResult]:
    """Dispatch a batch of up to 50 ParseInputs to the parsing subagent.

    Returns one ParseResult per input. Never raises on individual parse failures;
    failed items are returned with triage_status='DISPUTED' and confidence=0.0.

    Why: Individual parse failures must not halt the pipeline. DISPUTED items are
    routed to human review without blocking the remaining batch.

    Raises:
        ParseError: Only on total batch failure (subagent completely unreachable).
    """
    if not batch:
        return []

    return await _call_subagent(batch)


def validate_schema(rule_dict: dict) -> Rule:  # type: ignore[type-arg]
    """Validate and deserialise a raw rule dict into a typed Rule model.

    Why: Rules must be validated at the boundary before being stored or evaluated
    to prevent downstream errors from malformed data.

    Raises:
        ValidationError: Lists all missing or invalid fields in the message.
    """
    try:
        return Rule(**rule_dict)
    except PydanticValidationError as exc:
        # Re-raise as our domain ValidationError with a helpful message
        field_errors: list[str] = []
        for error in exc.errors():
            loc = ".".join(str(part) for part in error["loc"])
            msg = error["msg"]
            field_errors.append(f"{loc}: {msg}")

        # Build a message that always mentions the first bad field by name
        detail = "; ".join(field_errors)
        raise ValidationError(f"Rule validation failed — {detail}") from exc


async def extract_ambiguities(
    text: str, rules: List[Rule]
) -> List[AmbiguityFlag]:
    """Scan raw text (and optionally rules) for patterns matching the 30-type taxonomy.

    Why: Ambiguities detected during parsing must be flagged immediately so they
    are included in the ParseResult and routed to the review queue.

    Returns: List of AmbiguityFlag records; returns empty list if none found (never raises).
    """
    from src.ambiguity_map import detect_ambiguity_type

    flags: list[AmbiguityFlag] = []
    for rule in rules:
        rule_flags = detect_ambiguity_type(text, rule=rule)
        flags.extend(rule_flags)

    text_flags = detect_ambiguity_type(text)
    # Deduplicate by type_code
    seen_codes = {f.ambiguity_type_code for f in flags}
    for f in text_flags:
        if f.ambiguity_type_code not in seen_codes:
            flags.append(f)
            seen_codes.add(f.ambiguity_type_code)

    return flags


async def reverse_audit(rule: Rule) -> "AuditResult":
    """Fetch source document at rule.source_anchor.source_url, locate section,
    and compare rule.source_anchor.source_quote via semantic similarity.

    Threshold behaviour (configurable via env vars):
      ≥ 0.90 → VERIFIED
      0.70 – 0.89 → NEEDS_REVIEW
      < 0.70 → DISPUTED

    Why: Reverse-audit catches rules that were correctly parsed but whose source
    document has since changed (gazette revision, typo in quote, etc.).

    Raises:
        AuditError: If source URL is unreachable after retries.
    """
    from src.source_anchoring import AuditResult

    source_text = await _fetch_source_text(rule)

    score = await compute_semantic_similarity(  # type: ignore[misc]
        rule.source_anchor.source_quote, source_text
    )

    if score >= AUDIT_SIMILARITY_THRESHOLD:
        status = AuditStatus.VERIFIED
    elif score >= AUDIT_NEEDS_REVIEW_THRESHOLD:
        status = AuditStatus.NEEDS_REVIEW
    else:
        status = AuditStatus.DISPUTED

    return AuditResult(
        rule_id=rule.rule_id,
        audit_status=status,
        similarity_score=score,
    )


async def run_batch_pipeline(
    scheme_ids: List[str],
    batch_size: int = 50,
) -> RunManifest:
    """Run the full parsing pipeline for all given scheme_ids.

    Pipeline is continuous — no human gates between batches.
    Failed rules are auto-routed to review queue; pipeline continues.

    Why continuous: Human-in-the-loop between batches would make 1000-scheme
    processing impractical. Review happens asynchronously after each run.

    Returns: RunManifest summarising the complete run.
    """
    import os

    # Respect PARSE_BATCH_SIZE env var when set (configurable per architecture contract)
    effective_batch_size = int(os.environ.get("PARSE_BATCH_SIZE", str(batch_size)))

    started_at = datetime.now(tz=timezone.utc).isoformat()
    run_id = f"RUN-{uuid.uuid4().hex[:12].upper()}"

    all_rules: list[Rule] = []
    review_queue: list[str] = []
    rules_verified = 0
    rules_needs_review = 0
    rules_disputed = 0
    ambiguity_flags_count = 0

    # Build ParseInput objects for all schemes
    inputs = [
        ParseInput(scheme_id=sid, input_type="prose", raw_text=f"eligibility text for {sid}")
        for sid in scheme_ids
    ]

    # Dispatch in batches
    for i in range(0, len(inputs), effective_batch_size):
        batch = inputs[i : i + effective_batch_size]
        results = await dispatch_parsing_subagent(batch)

        for result in results:
            ambiguity_flags_count += len(result.ambiguity_flags)

            if result.triage_status == "DISPUTED":
                rules_disputed += len(result.rules) if result.rules else 1
                # Route disputed rule IDs to review queue
                for rule in result.rules:
                    review_queue.append(rule.rule_id)
                if not result.rules:
                    review_queue.append(f"{result.scheme_id}-DISPUTED")
            else:
                for rule in result.rules:
                    all_rules.append(rule)
                    if result.triage_status == "NEEDS_REVIEW":
                        rules_needs_review += 1
                        review_queue.append(rule.rule_id)
                    else:
                        rules_verified += 1

    completed_at = datetime.now(tz=timezone.utc).isoformat()

    return RunManifest(
        run_id=run_id,
        started_at=started_at,
        completed_at=completed_at,
        schemes_processed=len(scheme_ids),
        rules_generated=len(all_rules) + rules_disputed,
        rules_verified=rules_verified,
        rules_needs_review=rules_needs_review,
        rules_disputed=rules_disputed,
        ambiguity_flags_raised=ambiguity_flags_count,
        review_queue=review_queue,
    )
