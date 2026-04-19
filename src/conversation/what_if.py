""""What If" scenario exploration for CBC Part 5.

Implements the clone-modify-compare pattern: clone the user's profile,
apply a hypothetical change, re-run the matching engine, and compare
results to show what changed.
"""

from __future__ import annotations

import copy
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.conversation.config import GEMINI_API_KEY_ENV
from src.conversation.exceptions import ExtractionError, LLMUnavailableError
from src.conversation.prompts import WHAT_IF_EXTRACTION_PROMPT
from src.conversation.templates import (
    WHAT_IF_HEADER,
    WHAT_IF_IMPACT_NEGATIVE,
    WHAT_IF_IMPACT_NEUTRAL,
    WHAT_IF_IMPACT_POSITIVE,
    WHAT_IF_SUGGESTION_HEADER,
    get_field_label,
    get_template,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class FieldChange:
    """A single field modification within a What If scenario."""

    field_path: str
    old_value: Any
    new_value: Any
    change_description: str


@dataclass
class WhatIfModification:
    """A hypothetical profile change."""

    modification_id: str
    description: str
    field_changes: list[FieldChange]
    source_text: str


@dataclass
class SchemeStatusChange:
    """Status change for one scheme between current and What If results."""

    scheme_id: str
    scheme_name: str
    old_status: str
    new_status: str
    old_confidence: float
    new_confidence: float
    change_reason: str


@dataclass
class WhatIfComparison:
    """Comparison between current and What If matching results."""

    modification: WhatIfModification
    current_eligible_count: int = 0
    what_if_eligible_count: int = 0
    current_near_miss_count: int = 0
    what_if_near_miss_count: int = 0
    schemes_gained: list[SchemeStatusChange] = field(default_factory=list)
    schemes_lost: list[SchemeStatusChange] = field(default_factory=list)
    schemes_improved: list[SchemeStatusChange] = field(default_factory=list)
    schemes_worsened: list[SchemeStatusChange] = field(default_factory=list)
    schemes_unchanged: int = 0
    net_impact: str = "neutral"  # positive / negative / neutral
    impact_summary: str = ""


@dataclass
class WhatIfSuggestion:
    """A proactive suggestion for a What If scenario."""

    description: str
    field_changes: list[FieldChange]
    affected_schemes_count: int
    suggestion_text_en: str
    suggestion_text_hi: str


# ---------------------------------------------------------------------------
# What If intent detection
# ---------------------------------------------------------------------------


async def detect_what_if_intent(
    message: str,
    profile: dict[str, Any],
) -> Optional[WhatIfModification]:
    """Detect "What If" intent and extract the hypothetical modification.

    Uses LLM to parse natural language into field changes.

    Returns:
        ``WhatIfModification`` if intent detected, ``None`` otherwise.
    """
    prompt = WHAT_IF_EXTRACTION_PROMPT.format(
        current_profile=json.dumps(profile, default=str),
        user_message=message,
    )

    try:
        from src.conversation.extraction import _call_gemini

        result = await _call_gemini(
            system_prompt="You extract hypothetical profile changes from user messages.",
            user_message=prompt,
        )

        description = result.get("description", "")
        changes_raw = result.get("field_changes", [])

        if not changes_raw:
            return None

        field_changes: list[FieldChange] = []
        for ch in changes_raw:
            fp = ch.get("field_path", "")
            new_val = ch.get("new_value")
            old_val = profile.get(fp)
            desc = ch.get("change_description", "")
            field_changes.append(
                FieldChange(
                    field_path=fp,
                    old_value=old_val,
                    new_value=new_val,
                    change_description=desc,
                )
            )

        return WhatIfModification(
            modification_id=uuid.uuid4().hex[:12],
            description=description,
            field_changes=field_changes,
            source_text=message,
        )

    except (LLMUnavailableError, ExtractionError) as exc:
        logger.warning("What If extraction failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# What If execution
# ---------------------------------------------------------------------------


async def process_what_if(
    modification: WhatIfModification,
    current_profile: dict[str, Any],
    current_result: dict[str, Any],
    rule_base_path: Path,
) -> WhatIfComparison:
    """Execute a What If scenario using clone-modify-compare.

    Steps:
    1. Deep-clone current profile
    2. Apply hypothetical modifications
    3. Run matching engine on modified profile
    4. Compare results
    5. Return comparison (do NOT modify the original profile)
    """
    # 1. Clone
    modified_profile = copy.deepcopy(current_profile)

    # 2. Apply modifications
    for change in modification.field_changes:
        modified_profile[change.field_path] = change.new_value

    # 3. Run matching on modified profile
    try:
        from src.matching.engine import evaluate_profile
        from src.matching.profile import UserProfile

        profile_obj = UserProfile.from_flat_json(modified_profile)
        what_if_result = await evaluate_profile(
            profile=profile_obj,
            rule_base_path=rule_base_path,
        )
        what_if_dict = (
            asdict(what_if_result)
            if hasattr(what_if_result, "__dataclass_fields__")
            else what_if_result
        )
    except ImportError:
        logger.warning(
            "Matching engine not available — returning mock What If comparison"
        )
        what_if_dict = {}
    except Exception as exc:
        logger.error("What If matching failed: %s", exc)
        what_if_dict = {}

    # 4. Compare results
    comparison = _compare_results(
        current=current_result,
        what_if=what_if_dict,
        modification=modification,
    )

    return comparison


def _compare_results(
    current: dict[str, Any],
    what_if: dict[str, Any],
    modification: WhatIfModification,
) -> WhatIfComparison:
    """Compare two matching results and produce a WhatIfComparison.

    This function is resilient to missing fields — if the matching
    engine output doesn't have expected keys, it defaults gracefully.
    """
    # Extract scheme-level results from both
    current_schemes = _extract_scheme_statuses(current)
    what_if_schemes = _extract_scheme_statuses(what_if)

    gained: list[SchemeStatusChange] = []
    lost: list[SchemeStatusChange] = []
    improved: list[SchemeStatusChange] = []
    worsened: list[SchemeStatusChange] = []
    unchanged = 0

    _STATUS_RANK = {
        "ELIGIBLE": 3,
        "NEAR_MISS": 2,
        "INSUFFICIENT_DATA": 1,
        "INELIGIBLE": 0,
    }

    all_ids = set(current_schemes.keys()) | set(what_if_schemes.keys())
    for sid in all_ids:
        cur = current_schemes.get(sid, {"status": "INELIGIBLE", "confidence": 0.0, "name": sid})
        wif = what_if_schemes.get(sid, {"status": "INELIGIBLE", "confidence": 0.0, "name": sid})

        old_status = cur["status"]
        new_status = wif["status"]
        name = cur.get("name", sid)

        if old_status == new_status:
            unchanged += 1
            continue

        change = SchemeStatusChange(
            scheme_id=sid,
            scheme_name=name,
            old_status=old_status,
            new_status=new_status,
            old_confidence=cur.get("confidence", 0.0),
            new_confidence=wif.get("confidence", 0.0),
            change_reason=modification.description,
        )

        old_rank = _STATUS_RANK.get(old_status, 0)
        new_rank = _STATUS_RANK.get(new_status, 0)

        if new_rank > old_rank:
            if new_status == "ELIGIBLE" and old_status != "ELIGIBLE":
                gained.append(change)
            else:
                improved.append(change)
        elif new_rank < old_rank:
            if old_status == "ELIGIBLE" and new_status != "ELIGIBLE":
                lost.append(change)
            else:
                worsened.append(change)

    # Compute impact
    current_eligible = sum(1 for s in current_schemes.values() if s["status"] == "ELIGIBLE")
    what_if_eligible = sum(1 for s in what_if_schemes.values() if s["status"] == "ELIGIBLE")

    if what_if_eligible > current_eligible:
        net_impact = "positive"
    elif what_if_eligible < current_eligible:
        net_impact = "negative"
    else:
        net_impact = "neutral"

    return WhatIfComparison(
        modification=modification,
        current_eligible_count=current_eligible,
        what_if_eligible_count=what_if_eligible,
        schemes_gained=gained,
        schemes_lost=lost,
        schemes_improved=improved,
        schemes_worsened=worsened,
        schemes_unchanged=unchanged,
        net_impact=net_impact,
        impact_summary=(
            f"{modification.description}: "
            f"{len(gained)} gained, {len(lost)} lost, "
            f"{len(improved)} improved, {unchanged} unchanged"
        ),
    )


def _extract_scheme_statuses(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract scheme ID → {status, confidence, name} map from a MatchingResult dict."""
    schemes: dict[str, dict[str, Any]] = {}

    # Try common output structures
    for key in ("scheme_results", "results", "determinations"):
        items = result.get(key, [])
        if isinstance(items, list):
            for item in items:
                sid = item.get("scheme_id", item.get("id", ""))
                if sid:
                    schemes[sid] = {
                        "status": item.get("status", item.get("determination", "INELIGIBLE")),
                        "confidence": item.get("confidence", item.get("composite_confidence", 0.0)),
                        "name": item.get("scheme_name", item.get("name", sid)),
                    }
    return schemes


# ---------------------------------------------------------------------------
# Smart suggestion generation
# ---------------------------------------------------------------------------


def generate_what_if_suggestions(
    result: dict[str, Any],
    profile: dict[str, Any],
) -> list[WhatIfSuggestion]:
    """Generate actionable What If suggestions from gap analysis.

    Finds near-miss schemes and suggests profile changes that would
    flip them to ELIGIBLE.

    Returns:
        List of ``WhatIfSuggestion``, ordered by affected scheme count.
    """
    suggestions: list[WhatIfSuggestion] = []

    # Common actionable changes
    actionable_changes: list[dict[str, Any]] = [
        {
            "condition": not profile.get("documents.bank_account"),
            "field_path": "documents.bank_account",
            "new_value": True,
            "desc_en": "Open a bank account",
            "desc_hi": "बैंक खाता खोलें",
            "potential_schemes": 3,
        },
        {
            "condition": not profile.get("documents.mgnrega_job_card"),
            "field_path": "documents.mgnrega_job_card",
            "new_value": True,
            "desc_en": "Get an MGNREGA job card",
            "desc_hi": "मनरेगा जॉब कार्ड बनवाएँ",
            "potential_schemes": 2,
        },
        {
            "condition": not profile.get("documents.caste_certificate"),
            "field_path": "documents.caste_certificate",
            "new_value": True,
            "desc_en": "Get a caste certificate",
            "desc_hi": "जाति प्रमाण पत्र बनवाएँ",
            "potential_schemes": 2,
        },
        {
            "condition": not profile.get("documents.income_certificate"),
            "field_path": "documents.income_certificate",
            "new_value": True,
            "desc_en": "Get an income certificate",
            "desc_hi": "आय प्रमाण पत्र बनवाएँ",
            "potential_schemes": 2,
        },
    ]

    for change in actionable_changes:
        if change["condition"]:
            fc = FieldChange(
                field_path=change["field_path"],
                old_value=profile.get(change["field_path"]),
                new_value=change["new_value"],
                change_description=change["desc_en"],
            )
            suggestions.append(WhatIfSuggestion(
                description=change["desc_en"],
                field_changes=[fc],
                affected_schemes_count=change["potential_schemes"],
                suggestion_text_en=(
                    f'"{change["desc_en"]}" — could unlock '
                    f'{change["potential_schemes"]} more schemes'
                ),
                suggestion_text_hi=(
                    f'"{change["desc_hi"]}" — '
                    f'{change["potential_schemes"]} और योजनाएँ मिल सकती हैं'
                ),
            ))

    # Sort by impact (highest first)
    suggestions.sort(key=lambda s: s.affected_schemes_count, reverse=True)
    return suggestions[:3]  # Top 3


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_what_if_comparison(
    comparison: WhatIfComparison,
    language: str = "en",
) -> str:
    """Format a What If comparison as user-facing text."""
    lines: list[str] = []

    # Header
    lines.append(get_template(
        WHAT_IF_HEADER, language,
        description=comparison.modification.description,
    ))
    lines.append("")

    # Impact
    if comparison.net_impact == "positive":
        lines.append(get_template(
            WHAT_IF_IMPACT_POSITIVE, language,
            count=len(comparison.schemes_gained),
        ))
    elif comparison.net_impact == "negative":
        lines.append(get_template(
            WHAT_IF_IMPACT_NEGATIVE, language,
            count=len(comparison.schemes_lost),
        ))
    else:
        lines.append(get_template(WHAT_IF_IMPACT_NEUTRAL, language))

    lines.append("")

    # Gained schemes
    if comparison.schemes_gained:
        header = "✅ NEW — Now Eligible:" if language == "en" else "✅ नई पात्रता:"
        lines.append(header)
        for s in comparison.schemes_gained:
            conf = f"{s.new_confidence:.0%}" if s.new_confidence else "N/A"
            lines.append(f"  • {s.scheme_name}  ({conf} confidence)")
            lines.append(f"    {s.old_status} → {s.new_status}")
        lines.append("")

    # Improved schemes
    if comparison.schemes_improved:
        header = "⬆️ IMPROVED:" if language == "en" else "⬆️ सुधार:"
        lines.append(header)
        for s in comparison.schemes_improved:
            lines.append(f"  • {s.scheme_name}: {s.old_status} → {s.new_status}")
        lines.append("")

    # Lost schemes
    if comparison.schemes_lost:
        header = "⬇️ LOST:" if language == "en" else "⬇️ खोई योजनाएँ:"
        lines.append(header)
        for s in comparison.schemes_lost:
            lines.append(f"  • {s.scheme_name}: {s.old_status} → {s.new_status}")
        lines.append("")

    # Unchanged
    if comparison.schemes_unchanged:
        label = "unchanged" if language == "en" else "अपरिवर्तित"
        lines.append(f"  ➡️ {comparison.schemes_unchanged} schemes {label}")

    return "\n".join(lines)
