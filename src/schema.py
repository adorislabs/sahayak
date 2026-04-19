"""Pydantic v2 data models for CBC Part 1.

These models are the single source of truth for schema validation across all specs.
All Rule objects, ambiguity flags, scheme metadata, and relationships are defined here.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SchemeStatus(str, Enum):
    """Lifecycle status of a welfare scheme."""

    ACTIVE = "active"
    DORMANT = "dormant"
    DISCONTINUED = "discontinued"


class AuditStatus(str, Enum):
    """Result of reverse-audit verification for a rule."""

    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    DISPUTED = "DISPUTED"
    OVERRIDDEN = "OVERRIDDEN"


class Operator(str, Enum):
    """14-operator vocabulary for DSL rule expressions."""

    EQ = "EQ"
    NEQ = "NEQ"
    LT = "LT"
    LTE = "LTE"
    GT = "GT"
    GTE = "GTE"
    BETWEEN = "BETWEEN"
    IN = "IN"
    NOT_IN = "NOT_IN"
    NOT_MEMBER = "NOT_MEMBER"
    IS_NULL = "IS_NULL"
    IS_NOT_NULL = "IS_NOT_NULL"
    CONTAINS = "CONTAINS"
    MATCHES = "MATCHES"


class AmbiguitySeverity(str, Enum):
    """Severity level of an ambiguity flag."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# ---------------------------------------------------------------------------
# SourceAnchor
# ---------------------------------------------------------------------------


class SourceAnchor(BaseModel):
    """Provenance record linking a rule back to the exact clause in the source document.

    Why: Every rule must be auditable — policy officers must be able to locate the
    original text that generated each rule without additional tooling.
    """

    source_url: str
    document_title: str
    source_quote: str
    page_number: Optional[int] = None
    section: Optional[str] = None
    clause: Optional[str] = None
    gazette_ref: Optional[str] = None
    notification_date: str  # ISO 8601
    language: str = "en"
    alternate_language_ref: Optional[str] = None


# ---------------------------------------------------------------------------
# AmbiguityFlag
# ---------------------------------------------------------------------------


class AmbiguityFlag(BaseModel):
    """Record of a detected ambiguity in scheme language or rules.

    Why: Ambiguities must be tracked explicitly so policy teams can resolve them
    before rules are used for eligibility determination.
    """

    ambiguity_id: str  # AMB-001, AMB-002 …
    scheme_id: str
    rule_id: Optional[str] = None
    ambiguity_type_code: int  # 1–30 per 30-type taxonomy
    ambiguity_type_name: str
    description: str
    severity: AmbiguitySeverity
    resolution_status: str = "OPEN"  # OPEN | RESOLVED | ACCEPTED | ESCALATED

    @field_validator("ambiguity_type_code")
    @classmethod
    def _type_code_in_range(cls, v: int) -> int:
        """Enforce type code is within the 1–30 taxonomy range."""
        if not (1 <= v <= 30):
            raise ValueError(f"ambiguity_type_code must be 1–30, got {v}")
        return v


# ---------------------------------------------------------------------------
# Rule
# ---------------------------------------------------------------------------


class Rule(BaseModel):
    """A single parsed eligibility rule extracted from a welfare scheme document.

    Why: Structured rules enable programmatic eligibility evaluation, cross-scheme
    comparison, and automated audit — none of which is possible with raw prose.
    """

    rule_id: str  # e.g. "PMKISAN-R001"
    scheme_id: str
    rule_type: str  # "eligibility" | "disqualifying" | "prerequisite" | "administrative_discretion"
    condition_type: str  # "income_ceiling" | "age_range" | "caste_category" | …
    field: str  # DSL path: "applicant.age", "household.income_annual"
    operator: Operator
    value: Optional[Any] = None
    value_min: Optional[float] = None
    value_max: Optional[float] = None
    values: List[Any] = Field(default_factory=list)
    unit: Optional[str] = None
    logic_group: Optional[str] = None
    logic_operator: Optional[str] = None  # "AND" | "OR"
    prerequisite_scheme_ids: List[str] = Field(default_factory=list)
    state_scope: str = "central"
    source_anchor: SourceAnchor
    ambiguity_flags: List[AmbiguityFlag] = Field(default_factory=list)
    confidence: float  # 0.0–1.0
    audit_status: AuditStatus = AuditStatus.PENDING
    verified_by: Optional[str] = None
    parse_run_id: str
    version: str = "1.0.0"
    effective_from: Optional[str] = None
    supersedes_rule_id: Optional[str] = None
    display_text: str
    notes: Optional[str] = None

    @field_validator("confidence")
    @classmethod
    def _confidence_in_range(cls, v: float) -> float:
        """Confidence must be between 0.0 and 1.0 inclusive."""
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {v}")
        return v

    @model_validator(mode="after")
    def _between_requires_min_max(self) -> "Rule":
        """BETWEEN operator requires both value_min and value_max to be set."""
        if self.operator == Operator.BETWEEN:
            if self.value_min is None or self.value_max is None:
                raise ValueError(
                    "BETWEEN operator requires both value_min and value_max; got "
                    f"value_min={self.value_min}, value_max={self.value_max}"
                )
        return self


# ---------------------------------------------------------------------------
# RuleGroup
# ---------------------------------------------------------------------------

_VALID_LOGIC_VALUES = {"AND", "OR", "AND_OR_AMBIGUOUS"}


class RuleGroup(BaseModel):
    """A named grouping of rules with explicit AND/OR logic.

    Why: Compound eligibility criteria often require multiple rules to be evaluated
    together (e.g. land AND income criteria for PM-KISAN).
    """

    rule_group_id: str  # e.g. "PMKISAN-GROUP-A"
    scheme_id: str
    logic: str  # "AND" | "OR" | "AND_OR_AMBIGUOUS"
    rule_ids: List[str]
    group_ids: List[str] = Field(default_factory=list)
    display_text: str
    notes: Optional[str] = None

    @field_validator("logic")
    @classmethod
    def _logic_must_be_valid(cls, v: str) -> str:
        if v not in _VALID_LOGIC_VALUES:
            raise ValueError(
                f"logic must be one of {sorted(_VALID_LOGIC_VALUES)}, got '{v}'"
            )
        return v


# ---------------------------------------------------------------------------
# Scheme
# ---------------------------------------------------------------------------


class Scheme(BaseModel):
    """Metadata record for a single welfare scheme.

    Why: Scheme-level metadata provides the container for all rules, anchors,
    and relationships — necessary for versioning and provenance tracking.
    """

    scheme_id: str
    scheme_name: str
    short_name: str
    ministry: str
    state_scope: str = "central"
    status: SchemeStatus
    version: str = "1.0.0"
    last_verified: str  # ISO 8601
    source_urls: List[str]
    tags: List[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# SchemeRelationship
# ---------------------------------------------------------------------------


class SchemeRelationship(BaseModel):
    """Detected relationship between two welfare schemes.

    Why: Cross-scheme relationships (mutual exclusion, prerequisites, complementary)
    are critical for accurate eligibility advice — a user eligible for PMSYM
    cannot simultaneously benefit from NPS.
    """

    relationship_id: str
    scheme_a: str
    scheme_b: str
    relationship_type: str  # "PREREQUISITE" | "MUTUAL_EXCLUSION" | "COMPLEMENTARY" | "OVERLAP"
    confidence: float  # 0.0–1.0
    display_to_user: bool  # False if confidence < 0.60
    source_evidence: str
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _enforce_display_threshold(self) -> "SchemeRelationship":
        """Relationships with confidence < 0.60 must not be shown to users.

        Why: Low-confidence relationships would create confusing or incorrect advice.
        """
        if self.confidence < 0.60:
            object.__setattr__(self, "display_to_user", False)
        return self
