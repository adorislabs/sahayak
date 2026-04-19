"""Output presentation layer for CBC Part 5.

Transforms ``MatchingResult`` objects into user-readable text for
CLI (Rich), Web (HTML), and plain Markdown.  Handles bilingual
output (EN + HI) and provides both summary and detail views.
"""

from __future__ import annotations

import logging
from typing import Any

from src.conversation.templates import (
    CONFIDENCE_EXPLANATIONS,
    DOCUMENTS_HEADER,
    NEXT_STEPS_HEADER,
    PRESENTING_HEADER,
    RESULT_ELIGIBLE_HEADER,
    RESULT_GAP_ROW,
    RESULT_INELIGIBLE_HEADER,
    RESULT_NEAR_MISS_HEADER,
    RESULT_SCHEME_ROW,
    get_confidence_label,
    get_field_label,
    get_template,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STATUS_ORDER = ["ELIGIBLE", "NEAR_MISS", "INSUFFICIENT_DATA", "INELIGIBLE"]


# ---------------------------------------------------------------------------
# Summary view
# ---------------------------------------------------------------------------


def render_summary(
    result: dict[str, Any],
    language: str = "en",
) -> str:
    """Render a MatchingResult as a summary view.

    Groups schemes by status (ELIGIBLE → NEAR_MISS → INELIGIBLE),
    shows confidence, gaps, and actionable next steps.

    Args:
        result: MatchingResult as dict.
        language: ``"en"`` or ``"hi"``.

    Returns:
        Formatted multi-line string.
    """
    schemes = _extract_schemes(result)
    total = len(schemes)

    eligible = [s for s in schemes if s["status"] == "ELIGIBLE"]
    near_miss = [s for s in schemes if s["status"] == "NEAR_MISS"]
    ineligible = [s for s in schemes if s["status"] == "INELIGIBLE"]
    partial = [s for s in schemes if s["status"] == "INSUFFICIENT_DATA"]

    lines: list[str] = []

    # Header
    sep = "═" * 50
    lines.append(sep)
    lines.append(get_template(PRESENTING_HEADER, language, scheme_count=total))
    lines.append(sep)
    lines.append("")

    # Eligible schemes
    if eligible:
        lines.append(get_template(RESULT_ELIGIBLE_HEADER, language, count=len(eligible)))
        lines.append("─" * 40)
        for i, s in enumerate(eligible, 1):
            conf = int(s.get("confidence", 0) * 100)
            lines.append(get_template(
                RESULT_SCHEME_ROW, language,
                index=i, scheme_name=s.get("scheme_name", s.get("name", "")), confidence=conf,
            ))
            if s.get("action"):
                lines.append(f"     → {s['action']}")
        lines.append("")

    # Near-miss schemes
    if near_miss:
        lines.append(get_template(RESULT_NEAR_MISS_HEADER, language, count=len(near_miss)))
        lines.append("─" * 40)
        for i, s in enumerate(near_miss, len(eligible) + 1):
            conf = int(s.get("confidence", 0) * 100)
            lines.append(get_template(
                RESULT_SCHEME_ROW, language,
                index=i, scheme_name=s.get("scheme_name", s.get("name", "")), confidence=conf,
            ))
            if s.get("gap"):
                lines.append(get_template(
                    RESULT_GAP_ROW, language,
                    gap_description=s["gap"],
                ))
        lines.append("")

    # Partial / insufficient data
    if partial:
        header = (
            f"⬜ NEEDS MORE INFO ({len(partial)} scheme(s))"
            if language == "en"
            else f"⬜ और जानकारी चाहिए ({len(partial)} योजनाएँ)"
        )
        lines.append(header)
        lines.append("─" * 40)
        for s in partial:
            lines.append(f"  • {s.get('scheme_name', s.get('name', ''))}")
        lines.append("")

    # Ineligible (collapsed)
    if ineligible:
        lines.append(get_template(
            RESULT_INELIGIBLE_HEADER, language, count=len(ineligible),
        ))
        lines.append("")

    # Next steps
    steps = _generate_next_steps(eligible, near_miss, language)
    if steps:
        lines.append("─" * 40)
        lines.append(get_template(NEXT_STEPS_HEADER, language))
        lines.append("─" * 40)
        for step in steps:
            lines.append(f"  {step}")
        lines.append("")

    # Document checklist
    docs = _generate_document_checklist(schemes, language)
    if docs:
        lines.append(get_template(DOCUMENTS_HEADER, language))
        lines.append("─" * 40)
        for doc in docs:
            lines.append(f"  {doc}")
        lines.append("")

    lines.append(sep)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Detail view (per scheme)
# ---------------------------------------------------------------------------


def render_scheme_detail(
    scheme: dict[str, Any],
    language: str = "en",
) -> str:
    """Render detailed breakdown for a single scheme.

    Shows per-rule evaluation results, confidence breakdown,
    gap analysis, and source citations.

    Args:
        scheme: Single scheme result dict.
        language: ``"en"`` or ``"hi"``.

    Returns:
        Formatted multi-line string.
    """
    lines: list[str] = []

    name = scheme.get("name", scheme.get("scheme_name", "Unknown"))
    status = scheme.get("status", "UNKNOWN")
    conf = scheme.get("confidence", 0)

    lines.append("─" * 50)
    lines.append(f"  {name} — {status}")
    lines.append("─" * 50)
    lines.append("")

    # Confidence
    conf_label = get_confidence_label(conf, language)
    conf_pct = int(conf * 100) if isinstance(conf, float) and conf <= 1 else conf
    lines.append(f"  Confidence: {conf_pct}% ({conf_label})")

    # Explanation
    if conf >= 0.85:
        tier = "HIGH"
    elif conf >= 0.70:
        tier = "MEDIUM"
    elif conf >= 0.50:
        tier = "LOW"
    else:
        tier = "VERY_LOW"
    explanation = get_template(CONFIDENCE_EXPLANATIONS[tier], language)
    lines.append(f"  → {explanation}")
    lines.append("")

    # Rule evaluations
    rules = scheme.get("rule_evaluations", scheme.get("rules", []))
    if rules:
        lines.append("  Rule evaluations:")
        for rule in rules:
            passed = rule.get("passed", rule.get("result"))
            icon = "✅" if passed else "❌"
            rule_text = rule.get("description", rule.get("rule_text", ""))
            lines.append(f"  {icon} {rule_text}")
            source = rule.get("source", rule.get("source_anchor", ""))
            if source:
                lines.append(f"     Source: {source}")
        lines.append("")

    # Gap analysis
    gap = scheme.get("gap_analysis", scheme.get("gap", {}))
    if gap:
        if language == "en":
            lines.append("  Gap Analysis:")
        else:
            lines.append("  कमी विश्लेषण:")
        if isinstance(gap, dict):
            for field_path, gap_detail in gap.items():
                label = get_field_label(field_path, language)
                lines.append(f"  • {label}: {gap_detail}")
        elif isinstance(gap, str):
            lines.append(f"  • {gap}")
        lines.append("")

    # Ambiguity warnings
    ambiguities = scheme.get("ambiguity_flags", [])
    if ambiguities:
        warn = "⚠️ Important Notes:" if language == "en" else "⚠️ ज़रूरी नोट:"
        lines.append(f"  {warn}")
        for amb in ambiguities:
            if isinstance(amb, dict):
                lines.append(f"  • {amb.get('description', amb.get('message', ''))}")
            else:
                lines.append(f"  • {amb}")
        lines.append("")

    lines.append("─" * 50)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Next steps generation
# ---------------------------------------------------------------------------


def _generate_next_steps(
    eligible: list[dict[str, Any]],
    near_miss: list[dict[str, Any]],
    language: str,
) -> list[str]:
    """Generate prioritised next steps."""
    steps: list[str] = []
    step_num = 1

    # 1. Actions for eligible schemes (apply now)
    apply_now: list[str] = []
    for s in eligible:
        apply_now.append(s.get("scheme_name", s.get("name", "")))
    if apply_now:
        names = ", ".join(apply_now[:3])
        if language == "en":
            steps.append(f"{step_num}. Apply now for: {names}")
        else:
            steps.append(f"{step_num}. अभी आवेदन करें: {names}")
        step_num += 1

    # 2. Actions to unlock near-miss schemes
    for s in near_miss[:3]:
        gap = s.get("gap", s.get("gap_short", ""))
        if gap:
            if language == "en":
                steps.append(f"{step_num}. {gap} → unlocks {s.get('scheme_name', s.get('name', ''))}")
            else:
                steps.append(f"{step_num}. {gap} → {s.get('scheme_name', s.get('name', ''))} मिल सकती है")
            step_num += 1

    return steps


# ---------------------------------------------------------------------------
# Document checklist
# ---------------------------------------------------------------------------


def _generate_document_checklist(
    schemes: list[dict[str, Any]],
    language: str,
) -> list[str]:
    """Generate a de-duplicated document checklist ordered by impact."""
    doc_counts: dict[str, int] = {}

    for s in schemes:
        docs = s.get("required_documents", s.get("documents", []))
        for doc in docs:
            name = doc if isinstance(doc, str) else doc.get("name", "")
            if name:
                doc_counts[name] = doc_counts.get(name, 0) + 1

    # Sort by count (most impactful first)
    sorted_docs = sorted(doc_counts.items(), key=lambda x: x[1], reverse=True)

    lines: list[str] = []
    for i, (doc, count) in enumerate(sorted_docs[:6], 1):
        if language == "en":
            lines.append(f"{i}. {doc} — needed by {count} scheme(s)")
        else:
            lines.append(f"{i}. {doc} — {count} योजनाओं के लिए ज़रूरी")

    return lines


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_schemes(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract normalised scheme list from a MatchingResult dict."""
    schemes: list[dict[str, Any]] = []

    # Primary format produced by ConversationEngine._result_to_dict
    if "scheme_results" in result:
        return result["scheme_results"]

    # Legacy / alternative formats
    for key in ("results", "determinations"):
        items = result.get(key, [])
        if isinstance(items, list):
            for item in items:
                schemes.append({
                    "id": item.get("scheme_id", item.get("id", "")),
                    "name": item.get("scheme_name", item.get("name", "Unknown")),
                    "status": item.get("status", item.get("determination", "INELIGIBLE")),
                    "confidence": item.get("confidence", item.get("composite_confidence", 0.0)),
                    "gap": item.get("gap_summary", item.get("gap", "")),
                    "gap_short": item.get("gap_short", ""),
                    "action": item.get("action", item.get("next_step", "")),
                    "rule_evaluations": item.get("rule_evaluations", []),
                    "gap_analysis": item.get("gap_analysis", {}),
                    "ambiguity_flags": item.get("ambiguity_flags", []),
                    "required_documents": item.get("required_documents", []),
                })

    # Sort by status order
    status_rank = {s: i for i, s in enumerate(_STATUS_ORDER)}
    schemes.sort(key=lambda s: status_rank.get(s["status"], 99))

    return schemes
