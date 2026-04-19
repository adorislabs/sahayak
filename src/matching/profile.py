"""User profile model for the CBC matching engine.

Accepts profiles as flat dot-path JSON or nested JSON and validates them
against known Indian welfare scheme field requirements.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Set

from pydantic import BaseModel, Field, field_validator, model_validator

from src.exceptions import InvalidProfileError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Valid value sets
# ---------------------------------------------------------------------------

_VALID_STATE_CODES: frozenset[str] = frozenset({
    "AN", "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "GA", "GJ",
    "HP", "HR", "JH", "JK", "KA", "KL", "LA", "LD", "MH", "ML", "MN",
    "MP", "MZ", "NL", "OD", "OR", "PB", "PY", "RJ", "SK", "TN", "TR",
    "TS", "UK", "UP", "WB",
})

_VALID_GENDERS: frozenset[str] = frozenset({"male", "female", "transgender", "other"})

_VALID_CASTE_CATEGORIES: frozenset[str] = frozenset({"SC", "ST", "OBC", "GENERAL", "EWS"})

# Alias map: colloquial / full-form → canonical code
# Why: Survey forms and conversational interfaces often use descriptive terms;
# normalising here prevents UNDETERMINED outcomes on caste-gated rules.
_CASTE_ALIASES: dict[str, str] = {
    # SC aliases
    "DALIT": "SC",
    "SCHEDULED CASTE": "SC",
    "SCHEDULED-CASTE": "SC",
    # ST aliases
    "ADIVASI": "ST",
    "TRIBAL": "ST",
    "SCHEDULED TRIBE": "ST",
    "SCHEDULED-TRIBE": "ST",
    # OBC aliases
    "OTHER BACKWARD CLASS": "OBC",
    "OTHER BACKWARD CASTE": "OBC",
    "BACKWARD CLASS": "OBC",
    "BACKWARD CASTE": "OBC",
    "BC": "OBC",
    # GENERAL aliases
    "GENERAL": "GENERAL",
    "UNRESERVED": "GENERAL",
    "UR": "GENERAL",
    "OPEN": "GENERAL",
    "GEN": "GENERAL",
    # EWS aliases
    "ECONOMICALLY WEAKER SECTION": "EWS",
    "ECONOMICALLY WEAKER SECTIONS": "EWS",
    # Minority (no canonical mapping — kept as-is with warning)
}

# Map flat dot-path keys to Pydantic field names (underscored)
_FIELD_MAP: dict[str, str] = {
    "applicant.age": "applicant_age",
    "applicant.gender": "applicant_gender",
    "applicant.caste_category": "applicant_caste_category",
    "applicant.marital_status": "applicant_marital_status",
    "applicant.disability_status": "applicant_disability_status",
    "applicant.disability_percentage": "applicant_disability_percentage",
    "applicant.land_ownership_status": "applicant_land_ownership_status",
    "location.state": "location_state",
    "household.income_annual": "household_income_annual",
    "household.income_monthly": "household_income_monthly",
    "household.size": "household_size",
    "household.bpl_status": "household_bpl_status",
    "household.ration_card_type": "household_ration_card_type",
    "household.residence_type": "household_residence_type",
    "household.land_acres": "household_land_acres",
    "employment.type": "employment_type",
    "employment.is_epfo_member": "employment_is_epfo_member",
    "employment.is_esic_member": "employment_is_esic_member",
    "employment.is_nps_subscriber": "employment_is_nps_subscriber",
    "employment.is_income_tax_payer": "employment_is_income_tax_payer",
    "documents.aadhaar": "documents_aadhaar",
    "documents.bank_account": "documents_bank_account",
    "documents.bank_account_type": "documents_bank_account_type",
    "documents.mgnrega_job_card": "documents_mgnrega_job_card",
    "documents.caste_certificate": "documents_caste_certificate",
    "documents.income_certificate": "documents_income_certificate",
    "schemes.active_enrollments": "schemes_active_enrollments",
    "health.pregnancy_status": "health_pregnancy_status",
    "health.child_count": "health_child_count",
}

# Reverse map: field name → dot path
_REVERSE_FIELD_MAP: dict[str, str] = {v: k for k, v in _FIELD_MAP.items()}


@dataclass
class ProfileCompleteness:
    """Completeness analysis of a profile relative to a set of required fields."""

    total_relevant_fields: int
    populated_fields: int
    missing_fields: list[str]
    completeness_score: float
    impact_assessment: str  # "complete" / "partial" / "insufficient"


def _flatten_nested(nested: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Recursively flatten a nested dict to dot-path keys."""
    flat: dict[str, Any] = {}
    for k, v in nested.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            flat.update(_flatten_nested(v, key))
        else:
            flat[key] = v
    return flat


def _normalize_value(key: str, value: Any) -> Any:
    """Apply case normalization to specific field values."""
    if key == "location.state" and isinstance(value, str):
        return value.upper()
    if key == "applicant.gender" and isinstance(value, str):
        return value.lower()
    if key == "applicant.caste_category" and isinstance(value, str):
        # First uppercase, then resolve aliases so downstream code always sees
        # canonical codes (SC / ST / OBC / GENERAL / EWS) where possible.
        upper = value.upper().strip()
        return _CASTE_ALIASES.get(upper, upper)
    return value


class UserProfile(BaseModel):
    """User profile for welfare scheme eligibility evaluation.

    Accepts dot-path or nested JSON via class methods. Validates field
    ranges and cross-field consistency. Unknown fields are stored in
    extra_fields without raising.
    """

    # Core fields
    applicant_age: Optional[int] = None
    applicant_gender: Optional[str] = None
    applicant_caste_category: Optional[str] = None
    applicant_marital_status: Optional[str] = None
    applicant_disability_status: Optional[bool] = None
    applicant_disability_percentage: Optional[int] = None
    applicant_land_ownership_status: Optional[bool] = None

    location_state: Optional[str] = None

    household_income_annual: Optional[int] = None
    household_income_monthly: Optional[int] = None
    household_size: Optional[int] = None
    household_bpl_status: Optional[bool] = None
    household_ration_card_type: Optional[str] = None
    household_residence_type: Optional[str] = None
    household_land_acres: Optional[float] = None

    employment_type: Optional[str] = None
    employment_is_epfo_member: Optional[bool] = None
    employment_is_esic_member: Optional[bool] = None
    employment_is_nps_subscriber: Optional[bool] = None
    employment_is_income_tax_payer: Optional[bool] = None

    documents_aadhaar: Optional[bool] = None
    documents_bank_account: Optional[bool] = None
    documents_bank_account_type: Optional[str] = None
    documents_mgnrega_job_card: Optional[bool] = None
    documents_caste_certificate: Optional[bool] = None
    documents_income_certificate: Optional[bool] = None

    schemes_active_enrollments: list[str] = Field(default_factory=list)

    health_pregnancy_status: Optional[bool] = None
    health_child_count: Optional[int] = None

    extra_fields: dict[str, Any] = Field(default_factory=dict)

    # Internal warnings list (not validated but tracked)
    _warnings: list[str] = []

    model_config = {"arbitrary_types_allowed": True}

    @classmethod
    def from_flat_json(cls, data: dict[str, Any]) -> "UserProfile":
        """Construct a UserProfile from a flat dot-path dict.

        Keys like 'applicant.age' are mapped to field 'applicant_age'.
        Unknown keys go into extra_fields. Validation errors for out-of-range
        values raise InvalidProfileError.
        """
        # Normalize values (case, etc.) before mapping
        normalized: dict[str, Any] = {}
        extra: dict[str, Any] = {}

        for dot_key, value in data.items():
            norm_value = _normalize_value(dot_key, value)

            if dot_key in _FIELD_MAP:
                field_name = _FIELD_MAP[dot_key]
                normalized[field_name] = norm_value
            else:
                extra[dot_key] = norm_value

        # Run field-level validation before constructing
        cls._validate_fields(normalized, data)

        normalized["extra_fields"] = extra

        return cls(**normalized)

    @classmethod
    def from_nested_json(cls, data: dict[str, Any]) -> "UserProfile":
        """Construct a UserProfile from a nested dict like {applicant: {age: 30}}.

        Flattens to dot-path format first, then delegates to from_flat_json.
        """
        flat = _flatten_nested(data)
        return cls.from_flat_json(flat)

    @classmethod
    def _validate_fields(cls, normalized: dict[str, Any], original: dict[str, Any]) -> None:
        """Validate field values before model construction. Raises InvalidProfileError."""
        # Age validation
        age = normalized.get("applicant_age")
        if age is not None:
            if not isinstance(age, (int, float)):
                raise InvalidProfileError(
                    field="applicant.age",
                    reason=f"Age must be a number, got {type(age).__name__}",
                    suggestion="Provide age as an integer between 0 and 120",
                )
            if not (0 <= int(age) <= 120):
                raise InvalidProfileError(
                    field="applicant.age",
                    reason=f"Age {age} is outside valid range [0, 120]",
                    suggestion="Provide a valid age between 0 and 120",
                )

        # Gender validation
        gender = normalized.get("applicant_gender")
        if gender is not None:
            if gender not in _VALID_GENDERS:
                raise InvalidProfileError(
                    field="applicant.gender",
                    reason=f"Gender '{gender}' is not recognized",
                    suggestion=f"Valid values: {sorted(_VALID_GENDERS)}",
                )

        # State code validation
        state = normalized.get("location_state")
        if state is not None:
            if state not in _VALID_STATE_CODES:
                raise InvalidProfileError(
                    field="location.state",
                    reason=f"State code '{state}' is not a valid Indian state/UT code",
                    suggestion=f"Valid codes: {sorted(_VALID_STATE_CODES)}",
                )

        # Caste category validation (warn, don't raise — adversarial profiles may use
        # non-standard values like "Minority")
        caste = normalized.get("applicant_caste_category")
        if caste is not None:
            # _normalize_value already resolved aliases; re-check canonical set.
            if caste in _VALID_CASTE_CATEGORIES:
                normalized["applicant_caste_category"] = caste
            else:
                # Keep the value so operators can still evaluate it (e.g. "MINORITY");
                # emit a warning so reviewers can inspect ambiguous profiles.
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "Unrecognized caste category '%s' — stored as-is (aliases resolved before this check)",
                    caste,
                )

    @model_validator(mode="after")
    def _cross_field_validation(self) -> "UserProfile":
        """Apply cross-field consistency checks and auto-computations.

        Generates warnings for inconsistencies; does not raise.
        """
        warnings: list[str] = []

        # Auto-compute annual from monthly if annual is missing
        if self.household_income_annual is None and self.household_income_monthly is not None:
            object.__setattr__(
                self, "household_income_annual", self.household_income_monthly * 12
            )
            warnings.append(
                "household.income_annual auto-computed from income_monthly × 12"
            )

        # Warn about income inconsistency (>20% mismatch)
        elif (
            self.household_income_annual is not None
            and self.household_income_monthly is not None
        ):
            implied_annual = self.household_income_monthly * 12
            if self.household_income_annual > 0:
                ratio = abs(implied_annual - self.household_income_annual) / self.household_income_annual
                if ratio > 0.20:
                    warnings.append(
                        f"Income inconsistency: annual={self.household_income_annual}, "
                        f"monthly×12={implied_annual}. Using annual as primary."
                    )

        # Warn if disability_status=True but no percentage
        if self.applicant_disability_status is True and self.applicant_disability_percentage is None:
            warnings.append(
                "disability_status=True but disability_percentage not provided; "
                "some disability-specific rules may be UNDETERMINED"
            )

        # Warn about bank account type without bank account
        if (
            self.documents_bank_account is False
            and self.documents_bank_account_type is not None
        ):
            warnings.append(
                "documents.bank_account_type provided but bank_account=False; type value noted"
            )

        # Warn about tax payer with income below threshold
        if (
            self.employment_is_income_tax_payer is True
            and self.household_income_annual is not None
            and self.household_income_annual < 250000
        ):
            warnings.append(
                f"is_income_tax_payer=True but income_annual={self.household_income_annual} "
                "is below tax threshold of ₹2.5L; possible data entry error"
            )

        # Warn about minor age
        if self.applicant_age is not None and self.applicant_age < 18:
            warnings.append(
                f"Applicant age {self.applicant_age} indicates a minor; "
                "most schemes require age ≥ 18"
            )

        if warnings:
            logger.debug("UserProfile warnings: %s", warnings)

        return self

    def get_field_value(self, dot_path: str) -> Any:
        """Return the value for a given dot-path field, or None if not set or unknown."""
        field_name = _FIELD_MAP.get(dot_path)
        if field_name is not None:
            return getattr(self, field_name, None)
        # Check extra_fields
        return self.extra_fields.get(dot_path)

    def get_populated_fields(self) -> Set[str]:
        """Return the set of dot-path field names that have non-None values."""
        populated: Set[str] = set()
        for dot_path, field_name in _FIELD_MAP.items():
            value = getattr(self, field_name, None)
            if value is not None:
                # Also include non-empty lists
                if isinstance(value, list) and len(value) == 0:
                    continue
                populated.add(dot_path)
        return populated

    def compute_completeness(self, required_fields: set[str] | list[str]) -> ProfileCompleteness:
        """Compute profile completeness relative to a required field set.

        Args:
            required_fields: Field dot-paths that a scheme requires.

        Returns:
            ProfileCompleteness with score, counts, and impact assessment.
        """
        required = set(required_fields) if not isinstance(required_fields, set) else required_fields

        if not required:
            return ProfileCompleteness(
                total_relevant_fields=0,
                populated_fields=0,
                missing_fields=[],
                completeness_score=0.0,
                impact_assessment="insufficient",
            )

        populated = self.get_populated_fields()
        present = required & populated
        missing = sorted(required - populated)

        score = len(present) / len(required)

        if score >= 1.0:
            impact = "complete"
        elif score >= 0.60:
            impact = "partial"
        else:
            impact = "insufficient"

        return ProfileCompleteness(
            total_relevant_fields=len(required),
            populated_fields=len(present),
            missing_fields=missing,
            completeness_score=score,
            impact_assessment=impact,
        )
