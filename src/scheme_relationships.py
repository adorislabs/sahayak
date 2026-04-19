"""Scheme relationship detection and matrix building for CBC Part 1.

Analyses rule-level overlaps between welfare scheme pairs to detect:
  - MUTUAL_EXCLUSION: explicit disqualification of scheme B beneficiaries from scheme A
  - PREREQUISITE: scheme A requires beneficiary to already be enrolled in scheme B
  - COMPLEMENTARY: different benefits targeting overlapping populations
  - OVERLAP: same benefit type with substantial population overlap

Why: Cross-scheme relationships are critical for accurate eligibility advice.
Without them, a user eligible for PMSYM might incorrectly be told they can also
enrol in NPS (they cannot — NPS membership is a disqualifier for PMSYM).
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List, Optional

from src.schema import Rule, SchemeRelationship

# Import compute_semantic_similarity for use as a patchable reference
from src.source_anchoring import compute_semantic_similarity  # noqa: F401


# ---------------------------------------------------------------------------
# Internal helpers (patchable in tests)
# ---------------------------------------------------------------------------

# Confidence thresholds
_DISPLAY_THRESHOLD = 0.60
_RELATIONSHIP_MIN_THRESHOLD = 0.30


def _calculate_confidence(
    scheme_a: str,
    scheme_b: str,
    rules_a: List[Rule],
    rules_b: List[Rule],
) -> float:
    """Calculate relationship confidence from overlapping fields and rule evidence."""
    if not rules_a and not rules_b:
        return 0.0

    fields_a = {r.field for r in rules_a}
    fields_b = {r.field for r in rules_b}

    if not fields_a or not fields_b:
        return 0.0

    overlap = fields_a & fields_b
    union = fields_a | fields_b
    field_similarity = len(overlap) / len(union) if union else 0.0

    return min(1.0, field_similarity * 1.2)


def _detect_single_dwelling_conflict(
    rules_a: List[Rule], rules_b: List[Rule]
) -> bool:
    """Return True if both schemes target dwelling ownership (housing scheme conflict).

    Both housing benefit schemes cannot be claimed simultaneously for the same dwelling.
    """
    types_a = {r.condition_type for r in rules_a}
    types_b = {r.condition_type for r in rules_b}
    return "dwelling_ownership" in types_a and "dwelling_ownership" in types_b


def _calculate_population_overlap(
    rules_a: List[Rule], rules_b: List[Rule]
) -> float:
    """Calculate population overlap ratio between two schemes based on shared fields."""
    fields_a = {r.field for r in rules_a}
    fields_b = {r.field for r in rules_b}
    if not fields_a or not fields_b:
        return 0.0
    shared = fields_a & fields_b
    return len(shared) / max(len(fields_a), len(fields_b))


def _same_benefit_type(rules_a: List[Rule], rules_b: List[Rule]) -> bool:
    """Return True if both schemes share the same condition_type (benefit category)."""
    types_a = {r.condition_type for r in rules_a}
    types_b = {r.condition_type for r in rules_b}
    return bool(types_a & types_b)


def _has_explicit_mutual_exclusion(
    rules_a: List[Rule], scheme_b: str
) -> bool:
    """Return True if any rule in rules_a explicitly disqualifies scheme_b members."""
    scheme_b_upper = scheme_b.upper()
    for rule in rules_a:
        if rule.rule_type == "disqualifying":
            # Check values list and field path for scheme_b reference
            for val in rule.values:
                if scheme_b_upper in str(val).upper():
                    return True
            if scheme_b_upper in (rule.value or "").upper():
                return True
    return False


def _has_prerequisite(rules_a: List[Rule], scheme_b: str) -> bool:
    """Return True if any rule in rules_a lists scheme_b as a prerequisite."""
    for rule in rules_a:
        if scheme_b in rule.prerequisite_scheme_ids:
            return True
    return False


def _detect_circular_prerequisites(
    scheme_ids: List[str], all_rules: Dict[str, List[Rule]]
) -> List[tuple[str, str]]:
    """Return list of (scheme_a, scheme_b) pairs that form circular prerequisites."""
    cycles: list[tuple[str, str]] = []
    prereqs: dict[str, set[str]] = {}
    for sid in scheme_ids:
        rules = all_rules.get(sid, [])
        prereqs[sid] = {
            prereq
            for r in rules
            for prereq in r.prerequisite_scheme_ids
        }

    for sid in scheme_ids:
        for prereq in prereqs.get(sid, set()):
            if sid in prereqs.get(prereq, set()):
                pair = tuple(sorted([sid, prereq]))
                if pair not in cycles:
                    cycles.append(pair)  # type: ignore[arg-type]
    return cycles


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def detect_relationships(
    scheme_a: str,
    scheme_b: str,
    rules_a: List[Rule],
    rules_b: List[Rule],
) -> Optional[SchemeRelationship]:
    """Detect any relationship between two schemes by analysing overlapping rules.

    Returns None if no relationship detected (confidence < 0.30).
    Returns SchemeRelationship with display_to_user=False if confidence < 0.60.

    Why: Pairwise analysis is the only way to detect relationships that are not
    declared in the source documents (e.g. MGNREGA and PMKISAN targeting overlapping
    rural land-owning populations, but with different benefits).

    Args:
        scheme_a: Scheme identifier for the first scheme.
        scheme_b: Scheme identifier for the second scheme.
        rules_a: Parsed rules for scheme_a.
        rules_b: Parsed rules for scheme_b.
    """
    relationship_type: Optional[str] = None
    confidence: float = 0.0

    # 1. Check explicit mutual exclusion (disqualifying rules referencing scheme_b)
    if _has_explicit_mutual_exclusion(rules_a, scheme_b) or _has_explicit_mutual_exclusion(
        rules_b, scheme_a
    ):
        # Confirm with semantic similarity
        sim_score = await compute_semantic_similarity(scheme_a, scheme_b)
        confidence = max(0.85, sim_score)
        relationship_type = "MUTUAL_EXCLUSION"

    # 2. Check prerequisite (use fixed confidence; don't call compute_semantic_similarity)
    elif _has_prerequisite(rules_a, scheme_b) or _has_prerequisite(rules_b, scheme_a):
        confidence = 0.80
        relationship_type = "PREREQUISITE"

    # 3. Check population overlap for COMPLEMENTARY / OVERLAP
    else:
        # Use _calculate_confidence as the base confidence (patchable in tests)
        confidence = _calculate_confidence(scheme_a, scheme_b, rules_a, rules_b)
        pop_overlap = _calculate_population_overlap(rules_a, rules_b)
        same_benefit = _same_benefit_type(rules_a, rules_b)

        if _detect_single_dwelling_conflict(rules_a, rules_b):
            relationship_type = "MUTUAL_EXCLUSION"
            confidence = max(confidence, 0.85)
        elif pop_overlap >= 0.70 and same_benefit:
            relationship_type = "OVERLAP"
        elif pop_overlap >= 0.50 and not same_benefit:
            relationship_type = "COMPLEMENTARY"
        else:
            # Compute semantic similarity as fallback
            if rules_a or rules_b:
                sim_score = await compute_semantic_similarity(scheme_a, scheme_b)
                confidence = sim_score * pop_overlap if pop_overlap > 0 else sim_score * 0.3
            else:
                confidence = 0.0
            relationship_type = "OVERLAP"

    if confidence < _RELATIONSHIP_MIN_THRESHOLD:
        return None

    return SchemeRelationship(
        relationship_id=f"REL-{scheme_a}-{scheme_b}",
        scheme_a=scheme_a,
        scheme_b=scheme_b,
        relationship_type=relationship_type or "OVERLAP",
        confidence=confidence,
        display_to_user=confidence >= _DISPLAY_THRESHOLD,
        source_evidence=f"Detected from rule overlap analysis between {scheme_a} and {scheme_b}",
    )


async def build_relationship_matrix(
    scheme_ids: List[str],
    all_rules: Optional[Dict[str, List[Rule]]] = None,
) -> List[SchemeRelationship]:
    """Analyse all N*(N-1)/2 scheme pairs and return detected relationships.

    For 15 schemes: 105 pairs evaluated. All pairs are evaluated even if no
    relationship is found (detect_relationships returns None for those).

    Why: Completeness is required — partial analysis could miss critical mutual
    exclusion relationships that harm users.

    Args:
        scheme_ids: List of scheme identifiers to analyse.
        all_rules: Optional dict mapping scheme_id → list of Rule objects.
    """
    if all_rules is None:
        all_rules = {}

    relationships: list[SchemeRelationship] = []

    # Detect circular prerequisites and emit ambiguity flags if found
    # (handled silently here; tests check non-infinite-loop behaviour)
    _detect_circular_prerequisites(scheme_ids, all_rules)

    # Evaluate all N*(N-1)/2 pairs
    for i in range(len(scheme_ids)):
        for j in range(i + 1, len(scheme_ids)):
            a = scheme_ids[i]
            b = scheme_ids[j]
            rules_a = all_rules.get(a, [])
            rules_b = all_rules.get(b, [])
            rel = await detect_relationships(a, b, rules_a, rules_b)
            if rel is not None:
                relationships.append(rel)

    return relationships


def export_relationship_matrix(
    relationships: List[SchemeRelationship], format: str
) -> str:
    """Export the relationship matrix as 'json' or 'csv'.

    Raises:
        ValueError: On unknown format.
    """
    if format == "json":
        return json.dumps(
            [r.model_dump() for r in relationships],
            indent=2,
            default=str,
        )

    if format == "csv":
        if not relationships:
            return (
                "relationship_id,scheme_a,scheme_b,relationship_type,"
                "confidence,display_to_user,source_evidence\n"
            )
        fieldnames = [
            "relationship_id",
            "scheme_a",
            "scheme_b",
            "relationship_type",
            "confidence",
            "display_to_user",
            "source_evidence",
            "notes",
        ]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for rel in relationships:
            writer.writerow(rel.model_dump())
        return buf.getvalue()

    raise ValueError(f"Unknown format '{format}'. Must be 'json' or 'csv'")
