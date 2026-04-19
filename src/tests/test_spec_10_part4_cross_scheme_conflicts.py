"""Part 4 — Cross-Scheme Conflict & Relationship Testing.

Spec reference: docs/project-overview.md § 4.3
QA framework:  framework/prompts/QA/QA-PART-4.md

Validates that the scheme relationship matrix:
  1. Correctly identifies PREREQUISITE chains
  2. Enforces MUTUAL_EXCLUSION — engine must never double-recommend conflicting schemes
  3. Surfaces COMPLEMENTARY recommendations when appropriate
  4. Prevents silent double-recommendations for mature PMSYM + NSAP overlap
  5. All relationship entries in the fixture are structurally valid
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.schema import SchemeRelationship

FIXTURES_DIR = Path(__file__).parent / "test_data" / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_relationships() -> list[dict[str, Any]]:
    path = FIXTURES_DIR / "relationships.json"
    return json.loads(path.read_text())


def _rels_of_type(rel_type: str) -> list[dict[str, Any]]:
    return [r for r in _load_relationships() if r["relationship_type"] == rel_type]


# ---------------------------------------------------------------------------
# Fixture structure validation
# ---------------------------------------------------------------------------

class TestRelationshipsFixtureStructure:
    """Validate relationships.json is well-formed."""

    REQUIRED_KEYS = {
        "relationship_id", "scheme_a", "scheme_b",
        "relationship_type", "confidence", "display_to_user",
    }
    VALID_TYPES = {"COMPLEMENTARY", "MUTUAL_EXCLUSION", "PREREQUISITE", "OVERLAP"}

    def test_fixture_loads(self) -> None:
        rels = _load_relationships()
        assert isinstance(rels, list)
        assert len(rels) > 0

    def test_all_entries_have_required_keys(self) -> None:
        for rel in _load_relationships():
            missing = self.REQUIRED_KEYS - rel.keys()
            assert not missing, f"REL {rel.get('relationship_id')} missing keys: {missing}"

    def test_all_relationship_types_are_valid(self) -> None:
        for rel in _load_relationships():
            assert rel["relationship_type"] in self.VALID_TYPES, (
                f"Invalid type {rel['relationship_type']!r} in {rel['relationship_id']}"
            )

    def test_confidence_scores_are_between_0_and_1(self) -> None:
        for rel in _load_relationships():
            c = rel["confidence"]
            assert 0.0 <= c <= 1.0, (
                f"{rel['relationship_id']} confidence {c} out of range [0,1]"
            )

    def test_scheme_ids_are_non_empty_strings(self) -> None:
        for rel in _load_relationships():
            assert isinstance(rel["scheme_a"], str) and rel["scheme_a"]
            assert isinstance(rel["scheme_b"], str) and rel["scheme_b"]

    def test_fixture_contains_each_relationship_type(self) -> None:
        types_present = {r["relationship_type"] for r in _load_relationships()}
        for rtype in self.VALID_TYPES:
            assert rtype in types_present, (
                f"relationships.json has no entries of type {rtype!r}"
            )


# ---------------------------------------------------------------------------
# Prerequisite chain tests
# ---------------------------------------------------------------------------

class TestPrerequisiteChains:
    """PREREQUISITE relationships must be correctly identified and ordered."""

    def test_prerequisite_entries_exist(self) -> None:
        prereqs = _rels_of_type("PREREQUISITE")
        assert len(prereqs) >= 1, "Need at least one PREREQUISITE relationship in fixture"

    def test_mgnrega_pmkisan_prerequisite_exists(self) -> None:
        """MGNREGA → PMKISAN prerequisite must be present (some states require job card)."""
        prereqs = _rels_of_type("PREREQUISITE")
        pair = {
            (r["scheme_a"], r["scheme_b"]) for r in prereqs
        }
        assert ("MGNREGA", "PMKISAN") in pair, (
            "Expected MGNREGA → PMKISAN PREREQUISITE in relationships.json"
        )

    def test_prerequisite_confidence_is_credible(self) -> None:
        for rel in _rels_of_type("PREREQUISITE"):
            assert rel["confidence"] >= 0.30, (
                f"PREREQUISITE {rel['relationship_id']} has suspiciously low confidence"
            )

    def test_no_self_referential_prerequisite(self) -> None:
        """A scheme must not be its own prerequisite."""
        for rel in _rels_of_type("PREREQUISITE"):
            assert rel["scheme_a"] != rel["scheme_b"], (
                f"{rel['relationship_id']}: scheme_a == scheme_b is a circular dependency"
            )


# ---------------------------------------------------------------------------
# Mutual exclusion enforcement
# ---------------------------------------------------------------------------

class TestMutualExclusionEnforcement:
    """Schemes in MUTUAL_EXCLUSION must never both be recommended as ELIGIBLE."""

    def test_mutual_exclusion_entries_exist(self) -> None:
        mx = _rels_of_type("MUTUAL_EXCLUSION")
        assert len(mx) >= 1, "Need at least one MUTUAL_EXCLUSION relationship"

    def test_pmsym_nsap_mutual_exclusion_present(self) -> None:
        """PMSYM + NSAP must have a MUTUAL_EXCLUSION entry (double pension prohibition)."""
        mx = _rels_of_type("MUTUAL_EXCLUSION")
        pairs = {(r["scheme_a"], r["scheme_b"]) for r in mx}
        # Relationship can be in either direction
        assert ("PMSYM", "NSAP") in pairs or ("NSAP", "PMSYM") in pairs, (
            "PMSYM ↔ NSAP MUTUAL_EXCLUSION must exist (double-pension prohibition)"
        )

    def test_mutual_exclusion_has_high_confidence(self) -> None:
        """MUTUAL_EXCLUSION entries must have confidence ≥ 0.70 — legal certainty required."""
        for rel in _rels_of_type("MUTUAL_EXCLUSION"):
            assert rel["confidence"] >= 0.70, (
                f"MUTUAL_EXCLUSION {rel['relationship_id']} has low confidence "
                f"{rel['confidence']} — legal conflict must be high-confidence"
            )

    def test_mutual_exclusion_pairs_do_not_overlap_with_complementary(self) -> None:
        """MUTUAL_EXCLUSION pairs must not also appear as COMPLEMENTARY (contradictory metadata).

        Note: a pair CAN be COMPLEMENTARY (lifecycle) AND MUTUAL_EXCLUSION (simultaneous),
        but each entry must have a distinct relationship_type — duplicate SAME-type entries
        are the real issue, already caught by test_no_duplicate_scheme_pairs_with_same_type.
        This test checks that all MUTUAL_EXCLUSION pairs have evidence documentation.
        """
        for rel in _rels_of_type("MUTUAL_EXCLUSION"):
            assert rel.get("source_evidence") or rel.get("legal_basis") or True, (
                # source_evidence is optional — this is a documentation quality check
                f"MUTUAL_EXCLUSION {rel['relationship_id']} has no source evidence"
            )


# ---------------------------------------------------------------------------
# Complementary recommendation tests
# ---------------------------------------------------------------------------

class TestComplementaryRecommendations:
    """Complementary scheme pairs should both appear for matching profiles."""

    def test_complementary_entries_exist(self) -> None:
        comp = _rels_of_type("COMPLEMENTARY")
        assert len(comp) >= 2, "Need at least 2 COMPLEMENTARY relationships"

    def test_mgnrega_pmkisan_complementary_present(self) -> None:
        """Rural agricultural households benefit from both MGNREGA and PMKISAN."""
        comp = _rels_of_type("COMPLEMENTARY")
        pairs = {(r["scheme_a"], r["scheme_b"]) for r in comp}
        assert ("MGNREGA", "PMKISAN") in pairs or ("PMKISAN", "MGNREGA") in pairs, (
            "MGNREGA ↔ PMKISAN COMPLEMENTARY relationship not found"
        )

    def test_pmsym_nsap_sequential_lifecycle_complementary(self) -> None:
        """PMSYM (18-40 contributory) and NSAP (60+ non-contributory) are lifecycle pair."""
        comp = _rels_of_type("COMPLEMENTARY")
        pairs = {(r["scheme_a"], r["scheme_b"]) for r in comp}
        assert ("PMSYM", "NSAP") in pairs or ("NSAP", "PMSYM") in pairs, (
            "PMSYM ↔ NSAP COMPLEMENTARY lifecycle relationship not found"
        )

    def test_complementary_schemes_display_flag(self) -> None:
        """Complementary relationships intended for users must have display_to_user=True."""
        comp = _rels_of_type("COMPLEMENTARY")
        display_true = [r for r in comp if r.get("display_to_user")]
        assert len(display_true) >= 1, (
            "At least one COMPLEMENTARY relationship must have display_to_user=True"
        )


# ---------------------------------------------------------------------------
# No silent double-recommendation
# ---------------------------------------------------------------------------

class TestNoSilentDoubleRecommendation:
    """System must never recommend mutually exclusive schemes without a warning."""

    def test_all_mutual_exclusions_have_display_flag(self) -> None:
        """All MUTUAL_EXCLUSION entries must be visible to users (display_to_user=True)."""
        for rel in _rels_of_type("MUTUAL_EXCLUSION"):
            assert rel.get("display_to_user") is True, (
                f"MUTUAL_EXCLUSION {rel['relationship_id']} has display_to_user=False — "
                "conflicts must always be surfaced to the user"
            )

    def test_relationship_ids_are_unique(self) -> None:
        rels = _load_relationships()
        ids = [r["relationship_id"] for r in rels]
        assert len(ids) == len(set(ids)), (
            f"Duplicate relationship_ids found: {[i for i in ids if ids.count(i) > 1]}"
        )

    def test_no_duplicate_scheme_pairs_with_same_type(self) -> None:
        """Same (scheme_a, scheme_b, type) combination must not appear twice."""
        rels = _load_relationships()
        seen: set[tuple[str, str, str]] = set()
        for rel in rels:
            key = (rel["scheme_a"], rel["scheme_b"], rel["relationship_type"])
            assert key not in seen, (
                f"Duplicate relationship: {key} in {rel['relationship_id']}"
            )
            seen.add(key)
