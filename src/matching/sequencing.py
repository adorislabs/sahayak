"""Application sequencing via topological sort for the CBC matching engine.

Produces a sequenced application plan from a list of scheme determinations
and inter-scheme relationships.

Relationships handled:
  PREREQUISITE     → topological ordering, step.depends_on populated
  MUTUAL_EXCLUSION → ChoiceSet
  COMPLEMENTARY    → ComplementarySuggestion
  (none)           → ParallelGroup for independent schemes

Cycles in PREREQUISITE graph are broken at the lowest-confidence edge.
INELIGIBLE / DISQUALIFIED schemes are excluded from steps.
NEAR_MISS schemes are included as aspirational steps.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from graphlib import TopologicalSorter, CycleError
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Statuses excluded from output steps
_EXCLUDED_STATUSES = frozenset({"INELIGIBLE", "DISQUALIFIED"})


@dataclass
class ApplicationStep:
    """A single step in the application sequence."""

    order: int
    scheme_id: str
    scheme_name: str
    status: str
    depends_on: list[str]
    confidence: float


@dataclass
class ChoiceSet:
    """A set of mutually exclusive schemes — only one may be chosen."""

    choice_set_id: str
    schemes: list[str]          # list of scheme IDs (NOT scheme_ids to match tests)
    reason: str
    comparison_notes: str


@dataclass
class ParallelGroup:
    """A set of schemes that can be applied simultaneously."""

    schemes: list[str]


@dataclass
class ComplementarySuggestion:
    """A suggestion to also apply for a complementary scheme."""

    base_scheme_id: str
    suggested_scheme_id: str
    rationale: str


@dataclass
class ApplicationSequence:
    """Complete sequenced application plan."""

    steps: list[ApplicationStep]
    choice_sets: list[ChoiceSet]
    parallel_groups: list[ParallelGroup]
    complementary_suggestions: list[ComplementarySuggestion]
    warnings: list[str]


def _get_rel_source(rel: Any) -> str:
    """Extract source scheme ID from a relationship (handles mock + real objects)."""
    return getattr(rel, "source_scheme_id", None) or getattr(rel, "scheme_a", None) or ""


def _get_rel_target(rel: Any) -> str:
    """Extract target scheme ID from a relationship (handles mock + real objects)."""
    return getattr(rel, "target_scheme_id", None) or getattr(rel, "scheme_b", None) or ""


def _get_rel_type(rel: Any) -> str:
    return str(getattr(rel, "relationship_type", "") or "")


def _get_rel_confidence(rel: Any) -> float:
    try:
        return float(getattr(rel, "confidence", 0.5) or 0.5)
    except (TypeError, ValueError):
        return 0.5


def _break_cycles(
    prerequisite_edges: list[tuple[str, str, float]],
    warnings: list[str],
) -> list[tuple[str, str, float]]:
    """Attempt to break cycles by removing lowest-confidence edges until acyclic.

    Modifies the edge list in-place (by index removal). Also appends warnings.

    Args:
        prerequisite_edges: List of (source, target, confidence) tuples.
        warnings: List to append cycle warning messages to.

    Returns:
        Acyclic edge list.
    """
    edges = list(prerequisite_edges)
    max_iterations = len(edges) + 1  # Safety limit

    for _ in range(max_iterations):
        # Build adjacency to test for cycles
        graph: dict[str, set[str]] = {}
        for src, tgt, _ in edges:
            graph.setdefault(src, set()).add(tgt)

        ts = TopologicalSorter(graph)
        try:
            list(ts.static_order())
            break  # No cycle — done
        except CycleError:
            pass

        # Find and remove the lowest-confidence edge
        if not edges:
            break

        edges.sort(key=lambda e: e[2])  # Sort by confidence ascending
        removed = edges.pop(0)
        warnings.append(
            f"Cycle detected in prerequisite graph. Broke edge "
            f"'{removed[0]}' → '{removed[1]}' (confidence {removed[2]:.2f}) "
            f"to restore order."
        )

    return edges


def compute_application_sequence(
    determinations: list[Any],
    relationships: list[Any],
) -> ApplicationSequence:
    """Compute an application sequence from scheme determinations and relationships.

    Args:
        determinations: List of SchemeDetermination objects.
        relationships: List of SchemeRelationship objects.

    Returns:
        ApplicationSequence with steps, choice_sets, parallel_groups,
        complementary_suggestions, and warnings.

    Never raises — all exceptions are caught internally.
    """
    warnings: list[str] = []
    steps: list[ApplicationStep] = []
    choice_sets: list[ChoiceSet] = []
    parallel_groups: list[ParallelGroup] = []
    complementary_suggestions: list[ComplementarySuggestion] = []

    if not determinations:
        return ApplicationSequence(
            steps=[],
            choice_sets=[],
            parallel_groups=[],
            complementary_suggestions=[],
            warnings=[],
        )

    try:
        # Build lookup maps
        det_by_id: dict[str, Any] = {
            getattr(d, "scheme_id", ""): d for d in determinations
        }

        # Separate eligible/includable schemes from excluded ones
        includable_ids: set[str] = set()
        for d in determinations:
            sid = getattr(d, "scheme_id", "")
            status = getattr(d, "status", "ELIGIBLE")
            if status not in _EXCLUDED_STATUSES and sid:
                includable_ids.add(sid)

        # Categorise relationships
        prerequisite_edges: list[tuple[str, str, float]] = []  # (source, target, conf)
        mutual_exclusion_pairs: list[tuple[str, str]] = []
        complementary_pairs: list[tuple[str, str]] = []

        for rel in relationships:
            src = _get_rel_source(rel)
            tgt = _get_rel_target(rel)
            rel_type = _get_rel_type(rel).upper()
            conf = _get_rel_confidence(rel)

            if not src or not tgt:
                continue

            if rel_type == "PREREQUISITE":
                # Only include if both sides are known
                if src in det_by_id and tgt in det_by_id:
                    prerequisite_edges.append((src, tgt, conf))
            elif rel_type == "MUTUAL_EXCLUSION":
                if src in det_by_id and tgt in det_by_id:
                    mutual_exclusion_pairs.append((src, tgt))
            elif rel_type == "COMPLEMENTARY":
                complementary_pairs.append((src, tgt))

        # Break cycles in prerequisite graph
        if prerequisite_edges:
            prerequisite_edges = _break_cycles(prerequisite_edges, warnings)

        # Build topological sort for PREREQUISITE relationships
        # depends_on[target] = set of source IDs it depends on
        depends_on_map: dict[str, set[str]] = {sid: set() for sid in includable_ids}

        graph_adj: dict[str, set[str]] = {sid: set() for sid in includable_ids}
        for src, tgt, _ in prerequisite_edges:
            if src in includable_ids and tgt in includable_ids:
                graph_adj.setdefault(src, set())
                depends_on_map.setdefault(tgt, set()).add(src)

        # Compute topological order for steps
        # We want: if A → B (PREREQUISITE), then A comes before B
        # TopologicalSorter: pass {node: predecessors}
        pred_map: dict[str, set[str]] = {}
        for sid in includable_ids:
            pred_map[sid] = depends_on_map.get(sid, set())

        ts = TopologicalSorter(pred_map)
        try:
            topo_order = list(ts.static_order())
        except CycleError:
            # Fallback: ignore prerequisite ordering
            warnings.append("Could not resolve topological order; using arbitrary order.")
            topo_order = list(includable_ids)

        # Build steps in topological order
        step_num = 1
        for sid in topo_order:
            if sid not in includable_ids:
                continue
            det = det_by_id.get(sid)
            if det is None:
                continue

            _conf_obj = getattr(det, "confidence", None)
            if _conf_obj is not None and hasattr(_conf_obj, "composite"):
                confidence = float(_conf_obj.composite or 1.0)
            else:
                try:
                    confidence = float(_conf_obj or 1.0)
                except (TypeError, ValueError):
                    confidence = 1.0
            steps.append(
                ApplicationStep(
                    order=step_num,
                    scheme_id=sid,
                    scheme_name=getattr(det, "scheme_name", sid),
                    status=getattr(det, "status", "ELIGIBLE"),
                    depends_on=sorted(depends_on_map.get(sid, set())),
                    confidence=confidence,
                )
            )
            step_num += 1

        # Identify parallel groups: pairs of steps with no PREREQUISITE edge between them.
        # Any two schemes that don't depend on each other can be applied simultaneously.
        has_prereq_relation: set[tuple[str, str]] = set()
        for src, tgt, _ in prerequisite_edges:
            has_prereq_relation.add((src, tgt))
            has_prereq_relation.add((tgt, src))

        step_ids = [s.scheme_id for s in steps]
        for i, a in enumerate(step_ids):
            for j, b in enumerate(step_ids):
                if i >= j:
                    continue
                if (a, b) not in has_prereq_relation:
                    # They can be applied in parallel — find or create group for 'a'
                    found_group: Optional[ParallelGroup] = None
                    for grp in parallel_groups:
                        if a in grp.schemes:
                            found_group = grp
                            break

                    if found_group is None:
                        found_group = ParallelGroup(schemes=[a])
                        parallel_groups.append(found_group)

                    if b not in found_group.schemes:
                        found_group.schemes.append(b)

        # MUTUAL_EXCLUSION → ChoiceSets
        seen_excl_pairs: set[frozenset] = set()
        for i, (a, b) in enumerate(mutual_exclusion_pairs):
            pair_key = frozenset({a, b})
            if pair_key in seen_excl_pairs:
                continue
            seen_excl_pairs.add(pair_key)

            name_a = getattr(det_by_id.get(a), "scheme_name", a)
            name_b = getattr(det_by_id.get(b), "scheme_name", b)

            choice_sets.append(
                ChoiceSet(
                    choice_set_id=f"CS-{i+1:03d}",
                    schemes=[a, b],
                    reason=(
                        f"{name_a} and {name_b} are mutually exclusive — "
                        "you may only enroll in one."
                    ),
                    comparison_notes=(
                        f"Compare {name_a} vs {name_b}: review eligibility, benefit amounts, "
                        "and application process before choosing."
                    ),
                )
            )

        # COMPLEMENTARY → ComplementarySuggestions
        seen_comp_pairs: set[tuple[str, str]] = set()
        for src, tgt in complementary_pairs:
            if (src, tgt) in seen_comp_pairs:
                continue
            seen_comp_pairs.add((src, tgt))

            name_src = getattr(det_by_id.get(src), "scheme_name", src) if src in det_by_id else src
            name_tgt = getattr(det_by_id.get(tgt), "scheme_name", tgt) if tgt in det_by_id else tgt

            complementary_suggestions.append(
                ComplementarySuggestion(
                    base_scheme_id=src,
                    suggested_scheme_id=tgt,
                    rationale=(
                        f"If you are applying for {name_src}, also consider "
                        f"{name_tgt} — these schemes complement each other "
                        "and can be held simultaneously."
                    ),
                )
            )

    except Exception as e:
        logger.exception("Error computing application sequence: %s", e)
        warnings.append(f"Sequencing error: {e}")

    return ApplicationSequence(
        steps=steps,
        choice_sets=choice_sets,
        parallel_groups=parallel_groups,
        complementary_suggestions=complementary_suggestions,
        warnings=warnings,
    )
