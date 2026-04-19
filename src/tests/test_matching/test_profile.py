"""Tests for Feature 1: UserProfile model, validation, completeness, and normalisation.

Spec reference: docs/part2-planning/specs/01-user-profile-input.md
Architecture:   docs/part2-planning/ARCHITECTURE-CONTRACT.md § src/matching/profile.py

All tests in this file exercise src.matching.profile.UserProfile and
src.matching.profile.ProfileCompleteness. Tests will fail (ImportError) until
Agent B implements src/matching/profile.py — this is the expected Red phase.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.exceptions import InvalidProfileError  # Part 1 exception, extended in Part 2


# ---------------------------------------------------------------------------
# Module-level import (will fail until Agent B implements — expected Red phase)
# ---------------------------------------------------------------------------

from src.matching.profile import ProfileCompleteness, UserProfile  # type: ignore[import]


# ===========================================================================
# Group 1: Construction from flat JSON
# ===========================================================================

class TestFromFlatJson:
    """Spec 01 §: UserProfile.from_flat_json constructs correctly from dot-path dicts."""

    def test_from_flat_json_valid_complete_returns_profile(
        self, valid_profile_farmer: dict[str, Any]
    ) -> None:
        """Valid flat JSON with all core fields should return a UserProfile without error."""
        profile = UserProfile.from_flat_json(valid_profile_farmer)

        assert profile is not None
        assert profile.applicant_age == 38

    def test_from_flat_json_sets_location_state(
        self, valid_profile_farmer: dict[str, Any]
    ) -> None:
        """location.state field must map to location_state attribute."""
        profile = UserProfile.from_flat_json(valid_profile_farmer)

        assert profile.location_state == "UP"

    def test_from_flat_json_sets_boolean_fields_correctly(
        self, valid_profile_farmer: dict[str, Any]
    ) -> None:
        """Boolean fields must survive JSON round-trip without type coercion errors."""
        profile = UserProfile.from_flat_json(valid_profile_farmer)

        assert profile.applicant_disability_status is False
        assert profile.documents_aadhaar is True

    def test_from_flat_json_extra_fields_stored_in_extra_fields(self) -> None:
        """Unrecognised fields must go into extra_fields dict, not cause an error."""
        data = {
            "applicant.age": 25,
            "location.state": "MH",
            "some.unknown.field": "mystery_value",
        }
        profile = UserProfile.from_flat_json(data)

        assert "some.unknown.field" in profile.extra_fields
        assert profile.extra_fields["some.unknown.field"] == "mystery_value"

    def test_from_flat_json_invalid_age_raises_invalid_profile_error(self) -> None:
        """Age outside [0, 120] must raise InvalidProfileError, not crash silently."""
        data = {"applicant.age": 150, "location.state": "MH"}

        with pytest.raises(InvalidProfileError) as exc_info:
            UserProfile.from_flat_json(data)

        assert exc_info.value.field == "applicant.age"

    def test_from_flat_json_negative_age_raises_invalid_profile_error(self) -> None:
        """Negative age must raise InvalidProfileError."""
        data = {"applicant.age": -1, "location.state": "MH"}

        with pytest.raises(InvalidProfileError) as exc_info:
            UserProfile.from_flat_json(data)

        assert "applicant.age" in exc_info.value.field

    def test_from_flat_json_invalid_gender_raises_invalid_profile_error(self) -> None:
        """Gender not in {male, female, transgender, other} must raise InvalidProfileError."""
        data = {
            "applicant.age": 30,
            "applicant.gender": "attack_helicopter",
            "location.state": "MH",
        }

        with pytest.raises(InvalidProfileError):
            UserProfile.from_flat_json(data)

    def test_from_flat_json_invalid_state_code_raises_invalid_profile_error(self) -> None:
        """An invalid state code like 'XX' must raise InvalidProfileError with suggestion."""
        data = {"applicant.age": 30, "location.state": "XX"}

        with pytest.raises(InvalidProfileError) as exc_info:
            UserProfile.from_flat_json(data)

        assert exc_info.value.field == "location.state"
        assert exc_info.value.suggestion  # must provide valid state codes

    def test_from_flat_json_state_code_case_insensitive(self) -> None:
        """State code 'mh' should be normalised to 'MH' without error."""
        data = {"applicant.age": 30, "location.state": "mh"}
        profile = UserProfile.from_flat_json(data)

        assert profile.location_state == "MH"

    def test_from_flat_json_caste_category_case_insensitive(self) -> None:
        """'sc' must be normalised to 'SC' — case-insensitive enum matching."""
        data = {"applicant.age": 30, "applicant.caste_category": "sc", "location.state": "MH"}
        profile = UserProfile.from_flat_json(data)

        assert profile.applicant_caste_category == "SC"

    def test_from_flat_json_missing_optional_fields_are_none(self) -> None:
        """Optional fields not provided must default to None, not raise."""
        data = {"applicant.age": 30, "location.state": "MH"}
        profile = UserProfile.from_flat_json(data)

        assert profile.household_income_annual is None
        assert profile.applicant_disability_percentage is None

    def test_from_flat_json_empty_dict_returns_profile_with_all_none(self) -> None:
        """Empty dict must return a valid UserProfile with all fields None."""
        profile = UserProfile.from_flat_json({})

        assert profile is not None
        assert profile.applicant_age is None


# ===========================================================================
# Group 2: Construction from nested JSON
# ===========================================================================

class TestFromNestedJson:
    """Spec 01 §: UserProfile.from_nested_json flattens nested dicts to dot-path."""

    def test_from_nested_json_valid_nested_returns_profile(self) -> None:
        """Nested format {applicant: {age: 30}} must produce same result as flat format."""
        nested = {
            "applicant": {"age": 30, "gender": "male"},
            "location": {"state": "MH"},
            "household": {"income_annual": 200000},
        }
        profile = UserProfile.from_nested_json(nested)

        assert profile.applicant_age == 30
        assert profile.applicant_gender == "male"
        assert profile.location_state == "MH"

    def test_from_nested_json_produces_same_profile_as_flat_json(self) -> None:
        """Nested and flat representations of the same data must produce equal profiles."""
        flat = {
            "applicant.age": 38,
            "applicant.gender": "male",
            "location.state": "UP",
            "household.income_annual": 150000,
        }
        nested = {
            "applicant": {"age": 38, "gender": "male"},
            "location": {"state": "UP"},
            "household": {"income_annual": 150000},
        }
        from_flat = UserProfile.from_flat_json(flat)
        from_nested = UserProfile.from_nested_json(nested)

        assert from_flat.applicant_age == from_nested.applicant_age
        assert from_flat.location_state == from_nested.location_state

    def test_from_nested_json_invalid_type_raises_invalid_profile_error(self) -> None:
        """String in age field (nested) must raise InvalidProfileError."""
        nested = {"applicant": {"age": "thirty"}}

        with pytest.raises(InvalidProfileError):
            UserProfile.from_nested_json(nested)


# ===========================================================================
# Group 3: Field access
# ===========================================================================

class TestFieldAccess:
    """Spec 01 §: get_field_value and get_populated_fields behave correctly."""

    def test_get_field_value_returns_value_for_populated_field(
        self, valid_profile_farmer: dict[str, Any]
    ) -> None:
        """get_field_value('applicant.age') must return the stored value."""
        profile = UserProfile.from_flat_json(valid_profile_farmer)

        assert profile.get_field_value("applicant.age") == 38

    def test_get_field_value_returns_none_for_missing_field(self) -> None:
        """get_field_value for an unprovided field must return None, not raise."""
        profile = UserProfile.from_flat_json({"applicant.age": 30})

        result = profile.get_field_value("household.income_annual")

        assert result is None

    def test_get_field_value_never_raises_for_unknown_field(self) -> None:
        """get_field_value for a completely unknown field path must return None, never raise."""
        profile = UserProfile.from_flat_json({})

        result = profile.get_field_value("nonexistent.totally.fake.path")

        assert result is None

    def test_get_populated_fields_returns_set_of_provided_paths(
        self, valid_profile_farmer: dict[str, Any]
    ) -> None:
        """get_populated_fields must return the exact set of dot-paths with non-None values."""
        profile = UserProfile.from_flat_json(valid_profile_farmer)
        populated = profile.get_populated_fields()

        assert "applicant.age" in populated
        assert "location.state" in populated

    def test_get_populated_fields_excludes_none_fields(self) -> None:
        """Fields with None values must NOT appear in get_populated_fields."""
        profile = UserProfile.from_flat_json({"applicant.age": 30, "location.state": "MH"})
        populated = profile.get_populated_fields()

        assert "household.income_annual" not in populated
        assert "applicant.disability_percentage" not in populated

    def test_get_populated_fields_empty_profile_returns_empty_set(self) -> None:
        """Empty profile must return empty set from get_populated_fields."""
        profile = UserProfile.from_flat_json({})

        assert profile.get_populated_fields() == set()


# ===========================================================================
# Group 4: Profile completeness
# ===========================================================================

class TestProfileCompleteness:
    """Spec 01 §: compute_completeness correctly tracks field coverage."""

    def test_compute_completeness_all_required_fields_provided_score_one(
        self, valid_profile_farmer: dict[str, Any]
    ) -> None:
        """When all required fields are present, completeness_score must be 1.0."""
        profile = UserProfile.from_flat_json(valid_profile_farmer)
        required = {"applicant.age", "applicant.land_ownership_status", "employment.type"}

        result = profile.compute_completeness(required)

        assert result.completeness_score == 1.0
        assert result.missing_fields == []

    def test_compute_completeness_partial_fields_reflects_ratio(self) -> None:
        """When 2 of 4 required fields are provided, completeness_score must be 0.5."""
        profile = UserProfile.from_flat_json({
            "applicant.age": 30,
            "location.state": "MH",
        })
        required = {
            "applicant.age",
            "location.state",
            "household.income_annual",
            "household.bpl_status",
        }

        result = profile.compute_completeness(required)

        assert result.completeness_score == 0.5
        assert "household.income_annual" in result.missing_fields
        assert "household.bpl_status" in result.missing_fields

    def test_compute_completeness_empty_required_set_returns_zero(self) -> None:
        """When required_fields is empty, completeness_score must be 0.0 (not ZeroDivisionError)."""
        profile = UserProfile.from_flat_json({"applicant.age": 30})

        result = profile.compute_completeness(set())

        assert result.completeness_score == 0.0

    def test_compute_completeness_returns_profile_completeness_dataclass(
        self, valid_profile_farmer: dict[str, Any]
    ) -> None:
        """Return type must be ProfileCompleteness dataclass with expected fields."""
        profile = UserProfile.from_flat_json(valid_profile_farmer)
        result = profile.compute_completeness({"applicant.age"})

        assert isinstance(result, ProfileCompleteness)
        assert hasattr(result, "total_relevant_fields")
        assert hasattr(result, "populated_fields")
        assert hasattr(result, "missing_fields")
        assert hasattr(result, "completeness_score")
        assert hasattr(result, "impact_assessment")

    def test_compute_completeness_total_fields_matches_required_count(
        self, valid_profile_farmer: dict[str, Any]
    ) -> None:
        """total_relevant_fields must equal len(required_fields)."""
        profile = UserProfile.from_flat_json(valid_profile_farmer)
        required = {"applicant.age", "location.state", "household.income_annual"}

        result = profile.compute_completeness(required)

        assert result.total_relevant_fields == 3


# ===========================================================================
# Group 5: Cross-field validation (warnings)
# ===========================================================================

class TestCrossFieldValidation:
    """Spec 01 §: Cross-field inconsistencies produce warnings, not hard errors."""

    def test_disability_status_true_without_percentage_warns_not_raises(
        self, profile_with_disability: dict[str, Any]
    ) -> None:
        """disability_status=True without disability_percentage must produce a warning,
        not an InvalidProfileError — user can still be evaluated."""
        # Should NOT raise — a warning is acceptable
        profile = UserProfile.from_flat_json(profile_with_disability)

        assert profile is not None
        assert profile.applicant_disability_status is True

    def test_income_monthly_auto_computes_annual_when_annual_missing(self) -> None:
        """When only income_monthly is provided, income_annual must be auto-computed
        as income_monthly × 12 and flagged in profile warnings."""
        data = {
            "applicant.age": 30,
            "location.state": "MH",
            "household.income_monthly": 15000,
            # income_annual intentionally omitted
        }
        profile = UserProfile.from_flat_json(data)

        assert profile.household_income_annual == 15000 * 12

    def test_income_inconsistency_warns_uses_annual_as_primary(
        self, profile_income_inconsistency: dict[str, Any]
    ) -> None:
        """When income_annual and income_monthly × 12 differ by > 20%, income_annual
        must be used as primary and a warning generated — profile is still valid."""
        profile = UserProfile.from_flat_json(profile_income_inconsistency)

        # Profile must still be created — not rejected
        assert profile is not None
        # Annual declared value must be preserved as primary
        assert profile.household_income_annual == 180000

    def test_bank_account_type_without_bank_account_warns_and_ignores_type(self) -> None:
        """bank_account_type provided when bank_account=False: warning, type value ignored."""
        data = {
            "applicant.age": 30,
            "location.state": "MH",
            "documents.bank_account": False,
            "documents.bank_account_type": "jan_dhan",  # contradicts bank_account=False
        }
        profile = UserProfile.from_flat_json(data)

        assert profile is not None
        # The type should be cleared/None since bank_account is False
        assert profile.documents_bank_account is False

    def test_tax_payer_with_low_income_warns_not_raises(
        self, profile_tax_payer_low_income: dict[str, Any]
    ) -> None:
        """is_income_tax_payer=True with income < ₹2.5L: warning generated, profile valid."""
        profile = UserProfile.from_flat_json(profile_tax_payer_low_income)

        assert profile is not None
        assert profile.employment_is_income_tax_payer is True

    def test_minor_age_under_18_flagged(self) -> None:
        """age < 18 must produce a flag/warning about minor status — not an error."""
        data = {"applicant.age": 15, "location.state": "MH"}
        profile = UserProfile.from_flat_json(data)

        assert profile is not None
        assert profile.applicant_age == 15
