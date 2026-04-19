"""Contradiction detection and resolution for CBC Part 5.

Detects five types of contradictions in user input:
  Type 1: Direct value conflict (field already has a different value)
  Type 2: Intra-message contradiction (conflicting data in same message)
  Type 3: Implicit contradiction (new data contradicts an inference)
  Type 4: Cross-field inconsistency (related fields don't add up)
  Type 5: Logical impossibility (impossible field combinations)
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from src.conversation.templates import get_field_label, get_template, CONTRADICTION_DIRECT

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ContradictionFlag:
    """A detected contradiction in user input."""

    contradiction_id: str
    contradiction_type: int              # 1-5
    contradiction_type_name: str
    field_path: str
    existing_value: Any
    new_value: Any
    existing_source_turn: int
    new_source_turn: int
    existing_source_text: str
    new_source_text: str
    severity: str                        # blocking / warning / info
    resolution_status: str = "pending"   # pending / user_chose_new /
                                         # user_chose_existing / auto_resolved
    resolution_turn: Optional[int] = None
    message_en: str = ""
    message_hi: str = ""


@dataclass
class ContradictionReport:
    """All contradictions detected in one extraction pass."""

    contradictions: list[ContradictionFlag] = field(default_factory=list)

    @property
    def has_blocking(self) -> bool:
        """True if any contradiction has severity 'blocking'."""
        return any(c.severity == "blocking" for c in self.contradictions)

    @property
    def auto_resolved(self) -> list[ContradictionFlag]:
        """Contradictions that were auto-resolved."""
        return [
            c for c in self.contradictions
            if c.resolution_status == "auto_resolved"
        ]


# ---------------------------------------------------------------------------
# Correction intent detection
# ---------------------------------------------------------------------------

_CORRECTION_MARKERS_EN = [
    "actually", "wait", "no", "sorry", "i meant", "correction",
    "my mistake", "let me fix", "i was wrong", "not right",
    "change", "update", "changed", "updated",
    # Temporal update markers — user is reporting a life change, not an error
    "now i", "now i'm", "now i am", "these days", "recently",
    "anymore", "not anymore", "used to", "since then", "nowadays",
    "switched", "moved to", "transitioned", "became", "left",
    "quit", "retired", "got a new", "started",
]

_CORRECTION_MARKERS_HI = [
    "दरअसल", "रुकिए", "नहीं", "माफ़ कीजिए", "मेरा मतलब",
    "सही बात", "गलती हो गई", "बदलिए", "सुधार",
]


def is_intentional_correction(message: str) -> bool:
    """Check if a message contains correction intent markers.

    Returns:
        ``True`` if correction intent detected.
    """
    lower = message.lower()
    for marker in _CORRECTION_MARKERS_EN:
        if marker in lower:
            return True
    for marker in _CORRECTION_MARKERS_HI:
        if marker in message:
            return True
    return False


# ---------------------------------------------------------------------------
# Cross-field validation rules
# ---------------------------------------------------------------------------

_CROSS_FIELD_RULES: list[dict[str, Any]] = [
    {
        "name": "income_monthly_annual_consistency",
        "fields": ("household.income_monthly", "household.income_annual"),
        "check": lambda m, a: abs((m * 12) - a) / max(a, 1) <= 0.20,
        "message_en": (
            "Monthly income (₹{m:,}) × 12 = ₹{m12:,}, but annual income "
            "is ₹{a:,} (>{pct:.0%} difference)."
        ),
        "message_hi": (
            "मासिक आमदनी (₹{m:,}) × 12 = ₹{m12:,}, लेकिन सालाना "
            "आमदनी ₹{a:,} है (>{pct:.0%} अंतर)।"
        ),
        "severity": "warning",
    },
    {
        "name": "tax_payer_income_threshold",
        "fields": ("employment.is_income_tax_payer", "household.income_annual"),
        "check": lambda tax, income: not (tax and income < 250_000),
        "message_en": (
            "You indicated you pay income tax, but your annual income "
            "(₹{income:,}) is below the ₹2.5L taxable threshold."
        ),
        "message_hi": (
            "आपने आयकरदाता होना बताया, लेकिन सालाना आमदनी "
            "(₹{income:,}) कर-योग्य सीमा ₹2.5L से कम है।"
        ),
        "severity": "warning",
    },
    {
        "name": "disability_percentage_without_status",
        "fields": ("applicant.disability_status", "applicant.disability_percentage"),
        "check": lambda status, pct: not (status is False and pct is not None and pct > 0),
        "message_en": (
            "Disability percentage ({pct}%) specified but disability "
            "status is 'No'."
        ),
        "message_hi": (
            "विकलांगता प्रतिशत ({pct}%) दिया गया लेकिन विकलांगता "
            "स्थिति 'नहीं' है।"
        ),
        "severity": "warning",
    },
    {
        "name": "age_birth_year_consistency",
        "fields": ("applicant.age", "applicant.birth_year"),
        "check": lambda age, year: abs(age - (2026 - year)) <= 1,
        "message_en": (
            "Stated age ({age}) doesn't match birth year ({year}) — "
            "expected age ~{expected}."
        ),
        "message_hi": (
            "बताई गई उम्र ({age}) जन्म वर्ष ({year}) से मेल नहीं "
            "खाती — अनुमानित उम्र ~{expected}।"
        ),
        "severity": "blocking",
    },
    {
        "name": "bank_account_type_without_account",
        "fields": ("documents.bank_account", "documents.bank_account_type"),
        "check": lambda has_acct, acct_type: not (has_acct is False and acct_type is not None),
        "message_en": "Bank account type specified but no bank account.",
        "message_hi": "बैंक खाते का प्रकार बताया गया लेकिन खाता 'नहीं' है।",
        "severity": "warning",
    },
    {
        "name": "minor_with_employment",
        "fields": ("applicant.age", "employment.type"),
        "check": lambda age, emp: not (
            age is not None and age < 14
            and emp is not None and emp != "student"
        ),
        "message_en": (
            "Age ({age}) indicates a child, but employment type "
            "'{emp}' is specified."
        ),
        "message_hi": (
            "उम्र ({age}) से बच्चा लगता है, लेकिन रोज़गार "
            "'{emp}' बताया गया।"
        ),
        "severity": "blocking",
    },
    {
        "name": "land_ownership_without_acres",
        "fields": ("applicant.land_ownership_status", "household.land_acres"),
        "check": lambda owns, acres: not (owns is True and (acres is None or acres == 0)),
        "message_en": "You own land but haven't specified acreage.",
        "message_hi": "ज़मीन है कहा लेकिन कितनी ज़मीन नहीं बताई।",
        "severity": "info",
    },
]


# ---------------------------------------------------------------------------
# Detection functions
# ---------------------------------------------------------------------------


def detect_contradictions(
    new_extractions: list[dict[str, Any]],
    existing_profile: dict[str, Any],
    field_provenance: dict[str, dict[str, Any]],
    current_turn: int,
) -> list[ContradictionFlag]:
    """Detect contradictions between new extractions and existing profile.

    Checks:
      - Type 1: Direct value conflicts
      - Type 4: Cross-field inconsistencies
      - Type 5: Logical impossibilities

    Returns:
        List of ``ContradictionFlag``, empty if no contradictions.
    """
    flags: list[ContradictionFlag] = []

    # --- Type 1: Direct value conflicts ---
    for ext in new_extractions:
        fp = ext.get("field_path", "")
        new_val = ext.get("value")
        existing_val = existing_profile.get(fp)

        if existing_val is None or new_val is None:
            continue

        if existing_val == new_val:
            continue

        # Determine severity
        severity = _classify_conflict_severity(fp, existing_val, new_val)

        prov = field_provenance.get(fp, {})
        source_turn = prov.get("source_turn", 0)
        source_text = prov.get("source_text", "")

        flags.append(ContradictionFlag(
            contradiction_id=uuid.uuid4().hex[:12],
            contradiction_type=1,
            contradiction_type_name="direct_value_conflict",
            field_path=fp,
            existing_value=existing_val,
            new_value=new_val,
            existing_source_turn=source_turn,
            new_source_turn=current_turn,
            existing_source_text=source_text,
            new_source_text=ext.get("source_span", ""),
            severity=severity,
        ))

    # --- Type 4 & 5: Cross-field rules ---
    # Merge new extractions into a test profile
    merged = dict(existing_profile)
    for ext in new_extractions:
        fp = ext.get("field_path", "")
        if fp:
            merged[fp] = ext.get("value")

    for rule in _CROSS_FIELD_RULES:
        field_a, field_b = rule["fields"]
        val_a = merged.get(field_a)
        val_b = merged.get(field_b)

        if val_a is None or val_b is None:
            continue

        try:
            passes = rule["check"](val_a, val_b)
        except Exception:
            continue

        if not passes:
            flags.append(ContradictionFlag(
                contradiction_id=uuid.uuid4().hex[:12],
                contradiction_type=4,
                contradiction_type_name="cross_field_inconsistency",
                field_path=f"{field_a} ↔ {field_b}",
                existing_value=val_a,
                new_value=val_b,
                existing_source_turn=0,
                new_source_turn=current_turn,
                existing_source_text="",
                new_source_text="",
                severity=rule["severity"],
                message_en=rule.get("message_en", ""),
                message_hi=rule.get("message_hi", ""),
            ))

    return flags


def detect_intra_message_contradictions(
    extractions: list[dict[str, Any]],
) -> list[ContradictionFlag]:
    """Detect contradictions within a single extraction set (Type 2).

    Example: age=25 + birth_year=1990 in same message → 2026-1990 = 36 ≠ 25.

    Returns:
        List of ``ContradictionFlag``.
    """
    flags: list[ContradictionFlag] = []

    ext_map: dict[str, Any] = {}
    for ext in extractions:
        fp = ext.get("field_path", "")
        ext_map[fp] = ext.get("value")

    # Check age ↔ birth_year
    age = ext_map.get("applicant.age")
    birth_year = ext_map.get("applicant.birth_year")
    if age is not None and birth_year is not None:
        expected_age = 2026 - int(birth_year)
        if abs(int(age) - expected_age) > 1:
            flags.append(ContradictionFlag(
                contradiction_id=uuid.uuid4().hex[:12],
                contradiction_type=2,
                contradiction_type_name="intra_message_contradiction",
                field_path="applicant.age ↔ applicant.birth_year",
                existing_value=age,
                new_value=birth_year,
                existing_source_turn=0,
                new_source_turn=0,
                existing_source_text="",
                new_source_text="",
                severity="blocking",
                message_en=(
                    f"You said you're {age} years old, but birth year "
                    f"{birth_year} would make you ~{expected_age}. "
                    f"Which is correct?"
                ),
                message_hi=(
                    f"आपने उम्र {age} साल बताई, लेकिन जन्म वर्ष "
                    f"{birth_year} के अनुसार उम्र ~{expected_age} होनी चाहिए। "
                    f"कौन सा सही है?"
                ),
            ))

    # Check monthly ↔ annual income
    monthly = ext_map.get("household.income_monthly")
    annual = ext_map.get("household.income_annual")
    if monthly is not None and annual is not None:
        expected_annual = int(monthly) * 12
        if abs(expected_annual - int(annual)) / max(int(annual), 1) > 0.20:
            flags.append(ContradictionFlag(
                contradiction_id=uuid.uuid4().hex[:12],
                contradiction_type=2,
                contradiction_type_name="intra_message_contradiction",
                field_path="household.income_monthly ↔ household.income_annual",
                existing_value=monthly,
                new_value=annual,
                existing_source_turn=0,
                new_source_turn=0,
                existing_source_text="",
                new_source_text="",
                severity="warning",
                message_en=(
                    f"Monthly income ₹{monthly:,} × 12 = ₹{expected_annual:,}, "
                    f"but annual income stated as ₹{annual:,}."
                ),
                message_hi=(
                    f"मासिक आमदनी ₹{monthly:,} × 12 = ₹{expected_annual:,}, "
                    f"लेकिन सालाना आमदनी ₹{annual:,} बताई गई।"
                ),
            ))

    return flags


# ---------------------------------------------------------------------------
# Type 3: Implicit contradiction detection
# ---------------------------------------------------------------------------

# Inference table: value in user text → (field_path, inferred_value)
# These are inferences the system makes from indirect language.
_INFERENCE_TABLE: dict[str, list[tuple[str, Any]]] = {
    # Marital status → gender inferences
    "widow": [("applicant.gender", "female"), ("applicant.marital_status", "widowed")],
    "widower": [("applicant.gender", "male"), ("applicant.marital_status", "widowed")],
    "housewife": [("applicant.gender", "female"), ("applicant.marital_status", "married")],
    "विधवा": [("applicant.gender", "female"), ("applicant.marital_status", "widowed")],
    "विधुर": [("applicant.gender", "male"), ("applicant.marital_status", "widowed")],
    # Occupation inferences
    "farmer": [("employment.type", "agriculture")],
    "kisaan": [("employment.type", "agriculture")],
    "किसान": [("employment.type", "agriculture")],
    "kisan": [("employment.type", "agriculture")],
    # Gender words
    "i am a woman": [("applicant.gender", "female")],
    "i am a man": [("applicant.gender", "male")],
    "i'm a woman": [("applicant.gender", "female")],
    "i'm a man": [("applicant.gender", "male")],
    "मैं महिला हूँ": [("applicant.gender", "female")],
    "मैं पुरुष हूँ": [("applicant.gender", "male")],
}


def extract_inferences(message: str) -> list[tuple[str, Any, str]]:
    """Extract implied field values from message text.

    Returns:
        List of (field_path, inferred_value, trigger_word) tuples.
    """
    lower = message.lower()
    results: list[tuple[str, Any, str]] = []
    seen_fields: set[str] = set()
    for trigger, implications in _INFERENCE_TABLE.items():
        if trigger.lower() in lower:
            for fp, val in implications:
                if fp not in seen_fields:
                    results.append((fp, val, trigger))
                    seen_fields.add(fp)
    return results


def detect_type3_implicit_contradictions(
    new_extractions: list[dict[str, Any]],
    inferred_fields: dict[str, dict],
    current_turn: int,
    source_text: str = "",
) -> tuple[list[ContradictionFlag], list[tuple[str, Any, str]]]:
    """Detect Type 3 implicit contradictions.

    Checks if any new *directly stated* extraction contradicts a
    previously *inferred* field value (e.g. said "widow" → inferred
    gender=female, now says "I'm a man").

    Returns:
        (contradiction_flags, new_inferences_to_record)
        New inferences should be stored in session.inferred_fields.
    """
    flags: list[ContradictionFlag] = []
    new_inferences_from_extractions: list[tuple[str, Any, str]] = []

    for ext in new_extractions:
        fp = ext.get("field_path", "")
        new_val = ext.get("value")
        if fp not in inferred_fields:
            continue

        inferred = inferred_fields[fp]
        inferred_val = inferred.get("value")
        if inferred_val == new_val:
            continue

        # Direct statement contradicts an inference → auto-resolve in
        # favour of the explicit statement (Type 3 = info severity)
        flags.append(ContradictionFlag(
            contradiction_id=uuid.uuid4().hex[:12],
            contradiction_type=3,
            contradiction_type_name="implicit_contradiction",
            field_path=fp,
            existing_value=inferred_val,
            new_value=new_val,
            existing_source_turn=inferred.get("source_turn", 0),
            new_source_turn=current_turn,
            existing_source_text=f"[inferred from '{inferred.get('inferred_from', '')}']",
            new_source_text=source_text[:80],
            severity="info",
            resolution_status="auto_resolved",   # prefer explicit over inference
            message_en=(
                f"I had assumed your {fp.split('.')[-1]} was "
                f"'{inferred_val}' (from what you said earlier), but "
                f"you've now told me it's '{new_val}'. I've updated this."
            ),
            message_hi=(
                f"मैंने पहले अनुमान लगाया था कि आपका "
                f"{fp.split('.')[-1]} '{inferred_val}' है, "
                f"लेकिन अब आपने '{new_val}' बताया। मैंने इसे अपडेट कर दिया है।"
            ),
        ))

    return flags, new_inferences_from_extractions


# Fields used in scheme rules — conflicts on these are blocking
_SCHEME_CRITICAL_FIELDS: frozenset[str] = frozenset({
    "applicant.age",
    "applicant.gender",
    "applicant.caste_category",
    "applicant.marital_status",
    "applicant.land_ownership_status",
    "applicant.disability_status",
    "location.state",
    "household.income_annual",
    "household.income_monthly",
    "household.bpl_status",
    "employment.type",
})


def _classify_conflict_severity(
    field_path: str,
    old_value: Any,
    new_value: Any,
) -> str:
    """Classify a direct value conflict as blocking or warning.

    Blocking if:
    - Field is used in scheme rules (would affect matching results)
    - Numeric value change > 10%

    Warning if:
    - Field is cosmetic or numeric change ≤ 10%
    """
    if field_path in _SCHEME_CRITICAL_FIELDS:
        # For numeric fields, check magnitude of change
        if isinstance(old_value, (int, float)) and isinstance(new_value, (int, float)):
            if old_value == 0:
                return "blocking"
            pct_change = abs(new_value - old_value) / abs(old_value)
            if pct_change <= 0.10:
                return "warning"
        return "blocking"

    return "warning"


# ---------------------------------------------------------------------------
# Resolution dialog generation
# ---------------------------------------------------------------------------


def build_resolution_dialog(
    flag: ContradictionFlag,
    language: str = "en",
) -> str:
    """Build a resolution dialog string for a blocking contradiction.

    Returns:
        Formatted dialog text asking the user to choose.
    """
    if flag.message_en and language == "en":
        return flag.message_en
    if flag.message_hi and language in ("hi", "hinglish"):
        return flag.message_hi

    # Generic template
    label = get_field_label(flag.field_path, language)
    return get_template(
        CONTRADICTION_DIRECT,
        language,
        field_label=label,
        existing_value=flag.existing_value,
        new_value=flag.new_value,
    )
