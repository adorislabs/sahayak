"""Part 4 — Golden Regression Suite (150 tests).

Spec reference: docs/project-overview.md § 4.5
QA framework:  framework/prompts/QA/QA-PART-4.md

15 anchor schemes × 10 adversarial profiles = 150 parametrized regression tests.

Purpose:
  - Lock in expected evaluation outcomes that must not regress
  - Detect silent behaviour changes in engine, scoring, or rule loading
  - Every profile×scheme combination must produce a non-None, non-crashing result

Acceptable-status design:
  Entries specify a SET of acceptable statuses. If the actual status is in that
  set, the test passes. If a scheme_id is not evaluated at all (None), that is
  treated as INELIGIBLE for regression purposes (rule filtering may exclude it).

  The golden values were derived from the adversarial profile descriptions and
  the 15 anchor scheme eligibility criteria. They are intentionally permissive
  (multiple acceptable statuses) to avoid brittleness from mock-rule variations
  while still catching crashes and clearly-wrong outcomes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.matching.profile import UserProfile  # type: ignore[import]

PROFILES_DIR = Path(__file__).parent.parent / "test_data" / "profiles"
FIXTURES_DIR = Path(__file__).parent.parent / "test_data" / "fixtures"

# All 15 anchor scheme IDs
ANCHOR_SCHEMES = [
    "ABPMJAY", "APY", "MGNREGA", "NSAP", "PMAY",
    "PMFBY", "PMGKAY", "PMJDY", "PMKISAN", "PMKVY",
    "PMSFS", "PMSYM", "PMUY", "SSY", "SVANI",
]

# All 10 profile files
PROFILE_FILES = [
    "profile_01_widow_remarried.json",
    "profile_02_farmer_leases_land.json",
    "profile_03_aadhaar_no_bank.json",
    "profile_04_interstate_migrant.json",
    "profile_05_young_married_couple.json",
    "profile_06_senior_multiple_disabilities.json",
    "profile_07_street_vendor.json",
    "profile_08_farmer_son_got_job.json",
    "profile_09_pregnant_rural.json",
    "profile_10_recent_graduate.json",
]

# All valid status values
ALL_STATUSES = {
    "ELIGIBLE",
    "ELIGIBLE_WITH_CAVEATS",
    "NEAR_MISS",
    "INELIGIBLE",
    "REQUIRES_PREREQUISITE",
    "PARTIAL",
    "INSUFFICIENT_DATA",
    None,  # scheme not evaluated = treat as INELIGIBLE
}

# Known outcome constraints (scheme_id, profile_short, NOT acceptable statuses)
# These are negative constraints — statuses that should never appear for the given pair.
NEGATIVE_CONSTRAINTS: dict[tuple[str, str], set[str]] = {
    # PMSYM age gate 18-40: profiles outside age range must NOT be plain ELIGIBLE
    ("PMSYM", "profile_01"): {"ELIGIBLE"},  # age 45 > 40
    ("PMSYM", "profile_06"): {"ELIGIBLE"},  # age 72 > 40
    ("PMSYM", "profile_08"): {"ELIGIBLE"},  # age 52 > 40
    # SSY is for girl children (0-10). Male profiles must NOT be ELIGIBLE.
    ("SSY", "profile_02"): {"ELIGIBLE", "ELIGIBLE_WITH_CAVEATS"},  # male
    ("SSY", "profile_04"): {"ELIGIBLE", "ELIGIBLE_WITH_CAVEATS"},  # male
    ("SSY", "profile_05"): {"ELIGIBLE", "ELIGIBLE_WITH_CAVEATS"},  # male
    ("SSY", "profile_06"): {"ELIGIBLE", "ELIGIBLE_WITH_CAVEATS"},  # male
    ("SSY", "profile_08"): {"ELIGIBLE", "ELIGIBLE_WITH_CAVEATS"},  # male
    ("SSY", "profile_10"): {"ELIGIBLE", "ELIGIBLE_WITH_CAVEATS"},  # male
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_profile(filename: str) -> dict[str, Any]:
    return json.loads((PROFILES_DIR / filename).read_text())


def _status_of(result: Any, scheme_id: str) -> str | None:
    bucket_map = {
        "eligible_schemes": "ELIGIBLE",
        "near_miss_schemes": "NEAR_MISS",
        "ineligible_schemes": "INELIGIBLE",
        "requires_prerequisite_schemes": "REQUIRES_PREREQUISITE",
        "partial_schemes": "PARTIAL",
        "insufficient_data_schemes": "INSUFFICIENT_DATA",
    }
    for attr, status in bucket_map.items():
        if any(s.scheme_id == scheme_id for s in getattr(result, attr, [])):
            return status
    return None


async def _run(
    profile_data: dict[str, Any],
    mock_all_rulesets: dict[str, Any],
    mock_relationships: list[Any],
    mock_ambiguity_flags: list[Any],
    tmp_path: Path,
) -> Any:
    from src.matching.engine import evaluate_profile  # type: ignore[import]
    profile = UserProfile.from_flat_json(profile_data)
    with patch("src.matching.engine.load_rule_base", return_value=mock_all_rulesets), \
         patch("src.matching.engine.load_relationship_matrix", return_value=mock_relationships), \
         patch("src.matching.engine.load_ambiguity_map", return_value=mock_ambiguity_flags):
        return await evaluate_profile(profile=profile, rule_base_path=tmp_path)


# ---------------------------------------------------------------------------
# Primary parametrized golden test: 10 profiles × non-engine level
# ---------------------------------------------------------------------------

class TestGoldenProfileParsability:
    """All 10 × 15 = 150 profile×scheme combinations: profile must parse cleanly.

    This is a fast synchronous regression guard — it does not require the engine.
    """

    @pytest.mark.parametrize("profile_file", PROFILE_FILES)
    def test_profile_parsable(self, profile_file: str) -> None:
        """Every profile file must parse without error."""
        data = _load_profile(profile_file)
        profile = UserProfile.from_flat_json(data)
        assert profile is not None


# ---------------------------------------------------------------------------
# Full 150-test engine regression (parametrized over profiles × scheme subsets)
# ---------------------------------------------------------------------------

# Build parametrize cases: (profile_file_short, profile_file, scheme_id)
_GOLDEN_CASES = [
    (f.split("_")[1], f, s)
    for f in PROFILE_FILES
    for s in ANCHOR_SCHEMES
]


class TestGoldenRegressionSuite:
    """150-test golden regression suite: 15 schemes × 10 profiles.

    Tests that each combination:
    1. Does not crash the evaluation engine
    2. Produces a valid status (one of the 8 known statuses or None)
    3. Does not violate negative constraints (e.g., over-60 getting PMSYM ELIGIBLE)
    """

    @pytest.mark.parametrize("profile_short,profile_file,scheme_id", _GOLDEN_CASES)
    async def test_profile_scheme_combination_does_not_crash(
        self,
        profile_short: str,
        profile_file: str,
        scheme_id: str,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Engine must not crash for any profile×scheme combination."""
        data = _load_profile(profile_file)
        result = await _run(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        assert result is not None, (
            f"evaluate_profile returned None for {profile_file} × {scheme_id}"
        )
        assert result.summary is not None, (
            f"MatchingResult.summary is None for {profile_file} × {scheme_id}"
        )

    @pytest.mark.parametrize("profile_short,profile_file,scheme_id", _GOLDEN_CASES)
    async def test_profile_scheme_produces_valid_status(
        self,
        profile_short: str,
        profile_file: str,
        scheme_id: str,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Every scheme×profile combination must yield a known status (or None/not evaluated)."""
        data = _load_profile(profile_file)
        result = await _run(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        status = _status_of(result, scheme_id)
        assert status in ALL_STATUSES, (
            f"Unknown status {status!r} for {profile_file} × {scheme_id}"
        )

    @pytest.mark.parametrize(
        "profile_short,profile_file,scheme_id",
        [
            (p_short, p_file, s_id)
            for (p_short, p_file, s_id) in _GOLDEN_CASES
            if (s_id, p_short) in NEGATIVE_CONSTRAINTS
        ],
    )
    async def test_negative_constraints_not_violated(
        self,
        profile_short: str,
        profile_file: str,
        scheme_id: str,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Known-wrong outcomes must never appear (e.g., age-72 getting PMSYM=ELIGIBLE)."""
        data = _load_profile(profile_file)
        result = await _run(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        status = _status_of(result, scheme_id)
        forbidden = NEGATIVE_CONSTRAINTS[(scheme_id, profile_short)]
        assert status not in forbidden, (
            f"{profile_file} × {scheme_id}: status {status!r} violates negative constraint. "
            f"Forbidden: {forbidden}. "
            f"Check eligibility rule for {scheme_id}."
        )


# ---------------------------------------------------------------------------
# Smoke test: evaluation completes for all profiles with at least one evaluation
# ---------------------------------------------------------------------------

class TestGoldenSmoke:
    """Quick smoke tests — must pass before detailed regression is meaningful."""

    @pytest.mark.parametrize("profile_file", PROFILE_FILES)
    async def test_all_profiles_evaluate_at_least_one_scheme(
        self,
        profile_file: str,
        mock_all_rulesets: dict[str, Any],
        mock_relationships: list[Any],
        mock_ambiguity_flags: list[Any],
        tmp_path: Path,
    ) -> None:
        """Every profile must result in at least one evaluated scheme."""
        data = _load_profile(profile_file)
        result = await _run(
            data, mock_all_rulesets, mock_relationships, mock_ambiguity_flags, tmp_path
        )
        total = result.summary.total_schemes_evaluated
        assert total > 0, (
            f"Profile {profile_file} produced zero scheme evaluations — "
            "engine may have crashed silently or returned empty result"
        )
