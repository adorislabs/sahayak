"""Tests for Feature 5: Application sequencing via topological sort.

Spec reference: docs/part2-planning/specs/05-application-sequencing.md
Architecture:   docs/part2-planning/ARCHITECTURE-CONTRACT.md § src/matching/sequencing.py

Sequencing contracts:
  - PREREQUISITE relationships → topological ordering (graphlib.TopologicalSorter)
  - Cycles → broken at lowest-confidence edge + warning emitted
  - MUTUAL_EXCLUSION → ChoiceSet
  - COMPLEMENTARY → ComplementarySuggestion
  - Parallel-safe groups identified
  - INELIGIBLE + DISQUALIFIED schemes excluded from sequence steps
  - NEAR_MISS schemes included (aspirational steps)
  - Empty input → empty ApplicationSequence

Tests will fail (ImportError) until Agent B implements src/matching/sequencing.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.matching.sequencing import (  # type: ignore[import]
    ApplicationSequence,
    ApplicationStep,
    ChoiceSet,
    ComplementarySuggestion,
    ParallelGroup,
    compute_application_sequence,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _det(
    scheme_id: str,
    scheme_name: str = "",
    status: str = "ELIGIBLE",
) -> MagicMock:
    d = MagicMock()
    d.scheme_id = scheme_id
    d.scheme_name = scheme_name or scheme_id
    d.status = status
    return d


def _rel(
    source: str,
    target: str,
    rel_type: str,
    confidence: float = 0.9,
) -> MagicMock:
    r = MagicMock()
    r.source_scheme_id = source
    r.target_scheme_id = target
    r.relationship_type = rel_type
    r.confidence = confidence
    return r


# ===========================================================================
# Group 1: Linear prerequisite ordering
# ===========================================================================

class TestLinearPrerequisiteOrdering:
    """PREREQUISITE relationships produce deterministic topological ordering."""

    def test_linear_prerequisite_chain_correct_order(self) -> None:
        """A→B→C chain must produce [A, B, C] in output steps order."""
        dets = [_det("A"), _det("B"), _det("C")]
        rels = [
            _rel("A", "B", "PREREQUISITE"),
            _rel("B", "C", "PREREQUISITE"),
        ]

        seq = compute_application_sequence(dets, rels)

        step_ids = [s.scheme_id for s in seq.steps]
        # A must come before B, B before C
        assert step_ids.index("A") < step_ids.index("B")
        assert step_ids.index("B") < step_ids.index("C")

    def test_prerequisite_step_has_depends_on_populated(self) -> None:
        """Step for scheme B (depends on A) must have depends_on = ['A']."""
        dets = [_det("A"), _det("B")]
        rels = [_rel("A", "B", "PREREQUISITE")]

        seq = compute_application_sequence(dets, rels)

        step_b = next(s for s in seq.steps if s.scheme_id == "B")
        assert "A" in step_b.depends_on

    def test_root_scheme_has_empty_depends_on(self) -> None:
        """A scheme with no prerequisites must have depends_on = []."""
        dets = [_det("A"), _det("B")]
        rels = [_rel("A", "B", "PREREQUISITE")]

        seq = compute_application_sequence(dets, rels)

        step_a = next(s for s in seq.steps if s.scheme_id == "A")
        assert step_a.depends_on == []


# ===========================================================================
# Group 2: Cycle detection
# ===========================================================================

class TestCycleDetection:
    """Cycles in prerequisite graph are broken at lowest-confidence edge."""

    def test_cycle_broken_and_warning_emitted(self) -> None:
        """A→B→A cycle must be broken; a warning must appear in seq.warnings."""
        dets = [_det("A"), _det("B")]
        rels = [
            _rel("A", "B", "PREREQUISITE", confidence=0.9),
            _rel("B", "A", "PREREQUISITE", confidence=0.6),  # lower confidence
        ]

        seq = compute_application_sequence(dets, rels)

        # Must produce steps (not raise) and emit a cycle warning
        assert isinstance(seq, ApplicationSequence)
        assert len(seq.warnings) > 0
        cycle_warning = any("cycle" in w.lower() for w in seq.warnings)
        assert cycle_warning, f"Expected cycle warning, got: {seq.warnings}"

    def test_cycle_broken_at_lowest_confidence_edge(self) -> None:
        """After cycle breaking, the lower-confidence back-edge must be absent."""
        dets = [_det("A"), _det("B")]
        rels = [
            _rel("A", "B", "PREREQUISITE", confidence=0.9),
            _rel("B", "A", "PREREQUISITE", confidence=0.3),  # much lower
        ]

        seq = compute_application_sequence(dets, rels)

        # A must still come before B (high-confidence edge preserved)
        step_ids = [s.scheme_id for s in seq.steps]
        assert step_ids.index("A") < step_ids.index("B")

    def test_cycle_does_not_raise(self) -> None:
        """Cyclic input must never raise an exception."""
        dets = [_det("X"), _det("Y"), _det("Z")]
        rels = [
            _rel("X", "Y", "PREREQUISITE"),
            _rel("Y", "Z", "PREREQUISITE"),
            _rel("Z", "X", "PREREQUISITE"),
        ]

        # Must not raise
        seq = compute_application_sequence(dets, rels)
        assert isinstance(seq, ApplicationSequence)


# ===========================================================================
# Group 3: MUTUAL_EXCLUSION → ChoiceSet
# ===========================================================================

class TestMutualExclusionChoiceSets:
    """MUTUAL_EXCLUSION relationships produce ChoiceSets."""

    def test_mutual_exclusion_produces_choice_set(self) -> None:
        """Two mutually exclusive schemes must produce a ChoiceSet."""
        dets = [_det("PMSYM"), _det("NSAP")]
        rels = [_rel("PMSYM", "NSAP", "MUTUAL_EXCLUSION")]

        seq = compute_application_sequence(dets, rels)

        assert len(seq.choice_sets) >= 1

    def test_choice_set_contains_both_exclusive_schemes(self) -> None:
        """ChoiceSet.schemes must contain both mutually exclusive scheme IDs."""
        dets = [_det("PMSYM"), _det("NSAP")]
        rels = [_rel("PMSYM", "NSAP", "MUTUAL_EXCLUSION")]

        seq = compute_application_sequence(dets, rels)

        choice = seq.choice_sets[0]
        assert isinstance(choice, ChoiceSet)
        assert "PMSYM" in choice.schemes
        assert "NSAP" in choice.schemes

    def test_choice_set_has_comparison_notes(self) -> None:
        """ChoiceSet.comparison_notes must be non-empty to guide user decision."""
        dets = [_det("PMSYM"), _det("NSAP")]
        rels = [_rel("PMSYM", "NSAP", "MUTUAL_EXCLUSION")]

        seq = compute_application_sequence(dets, rels)

        assert len(seq.choice_sets[0].comparison_notes) > 0


# ===========================================================================
# Group 4: COMPLEMENTARY → ComplementarySuggestion
# ===========================================================================

class TestComplementarySuggestions:
    """COMPLEMENTARY relationships produce ComplementarySuggestions."""

    def test_complementary_produces_suggestion(self) -> None:
        """Two COMPLEMENTARY schemes must produce at least one ComplementarySuggestion."""
        dets = [_det("MGNREGA"), _det("PMKISAN")]
        rels = [_rel("MGNREGA", "PMKISAN", "COMPLEMENTARY")]

        seq = compute_application_sequence(dets, rels)

        assert len(seq.complementary_suggestions) >= 1

    def test_complementary_suggestion_has_correct_ids(self) -> None:
        """ComplementarySuggestion.base_scheme_id and suggested_scheme_id correct."""
        dets = [_det("MGNREGA"), _det("PMKISAN")]
        rels = [_rel("MGNREGA", "PMKISAN", "COMPLEMENTARY")]

        seq = compute_application_sequence(dets, rels)

        sugg = seq.complementary_suggestions[0]
        assert isinstance(sugg, ComplementarySuggestion)
        assert sugg.base_scheme_id == "MGNREGA"
        assert sugg.suggested_scheme_id == "PMKISAN"

    def test_complementary_suggestion_has_rationale(self) -> None:
        """ComplementarySuggestion.rationale must be non-empty."""
        dets = [_det("MGNREGA"), _det("PMKISAN")]
        rels = [_rel("MGNREGA", "PMKISAN", "COMPLEMENTARY")]

        seq = compute_application_sequence(dets, rels)

        assert seq.complementary_suggestions[0].rationale


# ===========================================================================
# Group 5: Parallel-safe groups
# ===========================================================================

class TestParallelGroups:
    """Schemes with no ordering constraints can be applied simultaneously."""

    def test_independent_schemes_form_parallel_group(self) -> None:
        """Schemes with no PREREQUISITE relationship between them must form a ParallelGroup."""
        dets = [_det("PMKISAN"), _det("PMSYM")]
        rels = []  # No ordering constraints

        seq = compute_application_sequence(dets, rels)

        assert len(seq.parallel_groups) >= 1

    def test_parallel_group_contains_independent_schemes(self) -> None:
        """ParallelGroup.schemes must contain the independent scheme IDs."""
        dets = [_det("PMKISAN"), _det("PMSYM")]
        rels = []

        seq = compute_application_sequence(dets, rels)

        all_in_groups = set()
        for grp in seq.parallel_groups:
            assert isinstance(grp, ParallelGroup)
            all_in_groups.update(grp.schemes)

        assert "PMKISAN" in all_in_groups
        assert "PMSYM" in all_in_groups

    def test_sequential_schemes_not_grouped_as_parallel(self) -> None:
        """Schemes with PREREQUISITE relationship must NOT be in the same ParallelGroup."""
        dets = [_det("A"), _det("B")]
        rels = [_rel("A", "B", "PREREQUISITE")]

        seq = compute_application_sequence(dets, rels)

        for grp in seq.parallel_groups:
            # A and B must not appear in the same parallel group
            assert not ("A" in grp.schemes and "B" in grp.schemes)


# ===========================================================================
# Group 6: Scheme status filtering
# ===========================================================================

class TestSchemeStatusFiltering:
    """INELIGIBLE and DISQUALIFIED schemes excluded; NEAR_MISS included."""

    def test_ineligible_schemes_excluded_from_steps(self) -> None:
        """INELIGIBLE schemes must not appear in ApplicationSequence.steps."""
        dets = [
            _det("PMKISAN", status="ELIGIBLE"),
            _det("PMSYM", status="INELIGIBLE"),
        ]
        seq = compute_application_sequence(dets, [])

        step_ids = [s.scheme_id for s in seq.steps]
        assert "PMSYM" not in step_ids

    def test_disqualified_schemes_excluded_from_steps(self) -> None:
        """DISQUALIFIED schemes must not appear in steps."""
        dets = [
            _det("MGNREGA", status="ELIGIBLE"),
            _det("NSAP", status="DISQUALIFIED"),
        ]
        seq = compute_application_sequence(dets, [])

        step_ids = [s.scheme_id for s in seq.steps]
        assert "NSAP" not in step_ids

    def test_near_miss_schemes_included_in_steps(self) -> None:
        """NEAR_MISS schemes must appear in steps (as aspirational)."""
        dets = [
            _det("PMKISAN", status="ELIGIBLE"),
            _det("MGNREGA", status="NEAR_MISS"),
        ]
        seq = compute_application_sequence(dets, [])

        step_ids = [s.scheme_id for s in seq.steps]
        assert "MGNREGA" in step_ids

    def test_near_miss_step_status_preserved(self) -> None:
        """ApplicationStep for a NEAR_MISS scheme must have status = 'NEAR_MISS'."""
        dets = [_det("MGNREGA", status="NEAR_MISS")]
        seq = compute_application_sequence(dets, [])

        near_miss_step = next(s for s in seq.steps if s.scheme_id == "MGNREGA")
        assert near_miss_step.status == "NEAR_MISS"


# ===========================================================================
# Group 7: Edge cases
# ===========================================================================

class TestSequencingEdgeCases:
    """Edge cases: empty input, single scheme, all ineligible."""

    def test_empty_determinations_returns_empty_sequence(self) -> None:
        """Empty determinations list → empty ApplicationSequence with all empty lists."""
        seq = compute_application_sequence([], [])

        assert isinstance(seq, ApplicationSequence)
        assert seq.steps == []
        assert seq.choice_sets == []
        assert seq.complementary_suggestions == []
        assert seq.parallel_groups == []

    def test_single_eligible_scheme_returns_one_step(self) -> None:
        """Single ELIGIBLE scheme → one ApplicationStep."""
        dets = [_det("PMKISAN", status="ELIGIBLE")]
        seq = compute_application_sequence(dets, [])

        assert len(seq.steps) == 1
        assert seq.steps[0].scheme_id == "PMKISAN"
        assert seq.steps[0].order == 1

    def test_all_ineligible_schemes_returns_empty_steps(self) -> None:
        """All INELIGIBLE schemes → steps = []."""
        dets = [
            _det("A", status="INELIGIBLE"),
            _det("B", status="INELIGIBLE"),
        ]
        seq = compute_application_sequence(dets, [])

        assert seq.steps == []

    def test_never_raises_on_any_input(self) -> None:
        """compute_application_sequence must never raise, regardless of input."""
        # Stress test: mix of statuses, relationships, cycles
        dets = [
            _det("A", status="ELIGIBLE"),
            _det("B", status="NEAR_MISS"),
            _det("C", status="INELIGIBLE"),
            _det("D", status="DISQUALIFIED"),
            _det("E", status="REQUIRES_PREREQUISITE"),
        ]
        rels = [
            _rel("A", "B", "PREREQUISITE"),
            _rel("B", "A", "PREREQUISITE"),  # cycle
            _rel("A", "C", "MUTUAL_EXCLUSION"),
            _rel("A", "D", "COMPLEMENTARY"),
        ]

        # Must not raise
        seq = compute_application_sequence(dets, rels)
        assert isinstance(seq, ApplicationSequence)

    def test_application_steps_are_application_step_instances(self) -> None:
        """All items in seq.steps must be ApplicationStep instances."""
        dets = [_det("PMKISAN"), _det("PMSYM")]
        seq = compute_application_sequence(dets, [])

        for step in seq.steps:
            assert isinstance(step, ApplicationStep)

    def test_step_order_numbers_are_sequential_starting_from_1(self) -> None:
        """steps[i].order must be i+1 (1-based sequential numbering)."""
        dets = [_det("A"), _det("B"), _det("C")]
        rels = [_rel("A", "B", "PREREQUISITE"), _rel("B", "C", "PREREQUISITE")]
        seq = compute_application_sequence(dets, rels)

        orders = [s.order for s in seq.steps]
        assert orders == list(range(1, len(seq.steps) + 1))
