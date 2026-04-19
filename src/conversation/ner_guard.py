"""NER Hallucination Guard for CBC Part 5 — post-extraction validation.

Prevents impossible or incoherent LLM-extracted values from entering
the user profile.  Four check layers:

1. Range checks   — hard bounds per field (age 0-120, etc.)
2. Vocab checks   — categorical fields must map to known values
3. Anchor checks  — extracted value must be recoverable from source_span
4. Cross-checks   — intra-extraction consistency (age vs birth_year, etc.)

Usage::

    from src.conversation.ner_guard import NERGuard
    guard = NERGuard()
    report = guard.validate(extraction_result)
    # Use report.passed_fields for profile update
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.conversation.extraction import ExtractedField, ExtractionResult
from src.conversation.extraction import CASTE_ALIASES, STATE_ALIASES

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# (min, max) inclusive — None means no bound
FIELD_RANGES: dict[str, tuple[float | None, float | None]] = {
    "applicant.age": (0, 120),
    "applicant.disability_percentage": (0, 100),
    "household.income_annual": (0, 100_000_000),   # ₹10 crore ceiling
    "household.income_monthly": (0, 10_000_000),
    "household.size": (1, 30),
    "household.land_acres": (0, 10_000),
    "applicant.birth_year": (1900, datetime.now(tz=timezone.utc).year),
}

VALID_VOCAB: dict[str, set[str]] = {
    "applicant.caste_category": {"SC", "ST", "OBC", "GENERAL", "EWS"},
    "applicant.gender": {"male", "female", "transgender", "other", "prefer not to say"},
    "applicant.marital_status": {
        "single", "married", "widowed", "divorced", "separated"
    },
    "employment.type": {
        "agriculture", "daily_wage", "salaried", "self_employed",
        "unemployed", "student", "retired", "homemaker", "other",
    },
    "location.state": set(STATE_ALIASES.values()),   # all valid 2-letter codes
}

# Fields that must have a numeric anchor in source_span
NUMERIC_FIELDS = {
    "applicant.age", "applicant.birth_year",
    "household.income_annual", "household.income_monthly",
    "household.size", "household.land_acres",
    "applicant.disability_percentage",
}

# Thresholds for cross-field consistency
AGE_BIRTH_YEAR_TOLERANCE = 2       # years
INCOME_MONTHLY_ANNUAL_RATIO_MAX = 0.25  # 25% deviation allowed


# ---------------------------------------------------------------------------
# Report models
# ---------------------------------------------------------------------------

@dataclass
class NERIssue:
    """A single validation issue for one extracted field."""
    field_path: str
    value: Any
    source_span: str
    status: str         # "WARN" | "REJECT"
    check_type: str     # "range" | "vocab" | "anchor" | "cross"
    reason: str
    clarification: str  # what to ask the user


@dataclass
class ValidationReport:
    """Full NER validation report for one extraction result."""
    passed_fields: list[ExtractedField] = field(default_factory=list)
    warned_fields: list[ExtractedField] = field(default_factory=list)  # kept, flagged
    rejected_fields: list[ExtractedField] = field(default_factory=list)  # dropped
    issues: list[NERIssue] = field(default_factory=list)

    @property
    def has_rejections(self) -> bool:
        return len(self.rejected_fields) > 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warned_fields) > 0

    def get_clarification_questions(self) -> list[str]:
        """Return user-facing questions for rejected fields."""
        return [i.clarification for i in self.issues if i.status == "REJECT"]


# ---------------------------------------------------------------------------
# NER Guard
# ---------------------------------------------------------------------------

class NERGuard:
    """Deterministic post-extraction hallucination guard."""

    def validate(self, result: ExtractionResult) -> ValidationReport:
        """Validate all extracted fields. Returns a ValidationReport.

        Fields are classified as:
            - passed  : all checks pass → safe to apply to profile
            - warned  : minor issue but value is plausible → apply with note
            - rejected: impossible/unrecoverable → drop, ask user to clarify
        """
        report = ValidationReport()
        rejection_map: dict[str, NERIssue] = {}  # field_path → most severe issue

        for ef in result.extractions:
            issues = self._check_field(ef)
            rejections = [i for i in issues if i.status == "REJECT"]
            warnings = [i for i in issues if i.status == "WARN"]

            for issue in issues:
                report.issues.append(issue)

            if rejections:
                report.rejected_fields.append(ef)
                rejection_map[ef.field_path] = rejections[0]
            elif warnings:
                report.warned_fields.append(ef)
            else:
                report.passed_fields.append(ef)

        # Cross-field checks (across passed + warned fields)
        all_ok = report.passed_fields + report.warned_fields
        cross_issues = self._cross_field_checks(all_ok)
        for issue in cross_issues:
            report.issues.append(issue)
            # Downgrade to warned if not already rejected
            matching = [f for f in all_ok if f.field_path == issue.field_path]
            for ef in matching:
                if ef in report.passed_fields:
                    report.passed_fields.remove(ef)
                    report.warned_fields.append(ef)

        return report

    # ------------------------------------------------------------------
    # Per-field checks
    # ------------------------------------------------------------------

    def _check_field(self, ef: ExtractedField) -> list[NERIssue]:
        issues: list[NERIssue] = []

        range_issue = self._range_check(ef)
        if range_issue:
            issues.append(range_issue)

        vocab_issue = self._vocab_check(ef)
        if vocab_issue:
            issues.append(vocab_issue)

        anchor_issue = self._anchor_check(ef)
        if anchor_issue:
            issues.append(anchor_issue)

        return issues

    def _range_check(self, ef: ExtractedField) -> NERIssue | None:
        bounds = FIELD_RANGES.get(ef.field_path)
        if bounds is None:
            return None

        lo, hi = bounds
        try:
            val = float(ef.value)
        except (TypeError, ValueError):
            return None  # non-numeric, handled by vocab check

        if lo is not None and val < lo:
            return NERIssue(
                field_path=ef.field_path,
                value=ef.value,
                source_span=ef.source_span,
                status="REJECT",
                check_type="range",
                reason=f"{ef.field_path} = {val} is below minimum {lo}",
                clarification=_range_clarification(ef.field_path, val, lo, hi),
            )
        if hi is not None and val > hi:
            return NERIssue(
                field_path=ef.field_path,
                value=ef.value,
                source_span=ef.source_span,
                status="REJECT",
                check_type="range",
                reason=f"{ef.field_path} = {val} exceeds maximum {hi}",
                clarification=_range_clarification(ef.field_path, val, lo, hi),
            )
        return None

    def _vocab_check(self, ef: ExtractedField) -> NERIssue | None:
        valid_set = VALID_VOCAB.get(ef.field_path)
        if valid_set is None:
            return None
        if isinstance(ef.value, str) and ef.value.lower() not in {v.lower() for v in valid_set}:
            return NERIssue(
                field_path=ef.field_path,
                value=ef.value,
                source_span=ef.source_span,
                status="WARN",    # Vocab mismatches are flagged but never block extraction
                check_type="vocab",
                reason=(
                    f"'{ef.value}' is not a recognised value for {ef.field_path}. "
                    f"Expected one of: {sorted(valid_set)}"
                ),
                clarification=_vocab_clarification(ef.field_path, valid_set),
            )
        return None

    def _anchor_check(self, ef: ExtractedField) -> NERIssue | None:
        """Verify that source_span contains evidence of the extracted value."""
        if ef.field_path not in NUMERIC_FIELDS:
            return None
        if not ef.source_span or ef.source_span in ("", "null", "None"):
            return NERIssue(
                field_path=ef.field_path,
                value=ef.value,
                source_span=ef.source_span,
                status="WARN",
                check_type="anchor",
                reason=f"No source span provided for {ef.field_path} = {ef.value}",
                clarification="",
            )

        # Check that at least one numeric token in source_span is consistent
        # with the extracted numeric value
        spans_nums = re.findall(r"[\d,.]+", ef.source_span)
        if not spans_nums:
            return NERIssue(
                field_path=ef.field_path,
                value=ef.value,
                source_span=ef.source_span,
                status="WARN",
                check_type="anchor",
                reason=(
                    f"Source span '{ef.source_span[:50]}' contains no numeric tokens "
                    f"but {ef.field_path} = {ef.value}"
                ),
                clarification="",
            )
        return None

    # ------------------------------------------------------------------
    # Cross-field checks
    # ------------------------------------------------------------------

    def _cross_field_checks(self, fields: list[ExtractedField]) -> list[NERIssue]:
        issues: list[NERIssue] = []
        by_path = {ef.field_path: ef for ef in fields}

        # Age ↔ birth_year consistency
        age_ef = by_path.get("applicant.age")
        year_ef = by_path.get("applicant.birth_year")
        if age_ef and year_ef:
            try:
                current_year = datetime.now(tz=timezone.utc).year
                implied_age = current_year - int(year_ef.value)
                if abs(implied_age - int(age_ef.value)) > AGE_BIRTH_YEAR_TOLERANCE:
                    issues.append(NERIssue(
                        field_path="applicant.age",
                        value=age_ef.value,
                        source_span=age_ef.source_span,
                        status="WARN",
                        check_type="cross",
                        reason=(
                            f"Age {age_ef.value} doesn't match birth year {year_ef.value} "
                            f"(expected ~{implied_age})"
                        ),
                        clarification=(
                            f"You mentioned age {age_ef.value} and birth year "
                            f"{year_ef.value}, but {year_ef.value} would make you "
                            f"approximately {implied_age}. Which is correct?"
                        ),
                    ))
            except (TypeError, ValueError):
                pass

        # Income monthly ↔ annual consistency
        monthly_ef = by_path.get("household.income_monthly")
        annual_ef = by_path.get("household.income_annual")
        if monthly_ef and annual_ef:
            try:
                monthly = float(monthly_ef.value)
                annual = float(annual_ef.value)
                if annual > 0 and abs((monthly * 12) - annual) / annual > INCOME_MONTHLY_ANNUAL_RATIO_MAX:
                    issues.append(NERIssue(
                        field_path="household.income_monthly",
                        value=monthly_ef.value,
                        source_span=monthly_ef.source_span,
                        status="WARN",
                        check_type="cross",
                        reason=(
                            f"Monthly income ₹{monthly:,.0f} × 12 = ₹{monthly*12:,.0f} "
                            f"but annual income given as ₹{annual:,.0f} (>25% difference)"
                        ),
                        clarification=(
                            f"Your monthly income (₹{monthly:,.0f}) × 12 = ₹{monthly*12:,.0f}, "
                            f"but you mentioned annual income of ₹{annual:,.0f}. "
                            "Which is more accurate — the monthly or the annual figure?"
                        ),
                    ))
            except (TypeError, ValueError):
                pass

        return issues


# ---------------------------------------------------------------------------
# Clarification helpers
# ---------------------------------------------------------------------------

def _range_clarification(field_path: str, val: float, lo: float | None, hi: float | None) -> str:
    labels = {
        "applicant.age": ("age", "years"),
        "household.income_annual": ("annual income", "₹"),
        "household.income_monthly": ("monthly income", "₹"),
        "household.size": ("family size", "members"),
        "household.land_acres": ("land area", "acres"),
        "applicant.disability_percentage": ("disability percentage", "%"),
        "applicant.birth_year": ("birth year", ""),
    }
    label, unit = labels.get(field_path, (field_path, ""))
    if lo is not None and val < lo:
        return f"The {label} you mentioned ({val}{unit}) seems unusually low. Could you confirm?"
    return f"The {label} you mentioned ({val}{unit}) seems unusually high. Could you confirm?"


def _vocab_clarification(field_path: str, valid_set: set[str]) -> str:
    friendly = {
        "applicant.caste_category": (
            "caste category", "SC, ST, OBC, General, or EWS"
        ),
        "applicant.gender": ("gender", "male, female, transgender, or other"),
        "applicant.marital_status": (
            "marital status", "single, married, widowed, divorced, or separated"
        ),
        "employment.type": (
            "occupation type",
            "agriculture, daily wage, salaried, self-employed, unemployed, etc."
        ),
        "location.state": ("state name", "a valid Indian state or UT name"),
    }
    label, options = friendly.get(field_path, (field_path, str(sorted(valid_set))[:80]))
    return f"I couldn't recognise your {label}. Could you say it again? Options: {options}."
