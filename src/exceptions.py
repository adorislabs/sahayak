"""Custom exception hierarchy for CBC Part 1.

Every error scenario tested by Agent A maps to one of these exception classes.
Raise the most specific subclass; catch the base class when handling families of errors.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Sourcing errors
# ---------------------------------------------------------------------------


class SourceError(Exception):
    """Generic sourcing failure (base class for all data-acquisition errors)."""


class PDFError(SourceError):
    """PDF missing, corrupt, too large, or non-PDF content returned."""


class NetworkError(SourceError):
    """HTTP 4xx/5xx, DNS failure, or request timeout during data fetch."""


class SchemeNotFoundError(SourceError):
    """Scheme ID not found in any data tier (Tier 1 myScheme, Tier 2 PDF, Tier 3 Kaggle)."""


# ---------------------------------------------------------------------------
# Parsing / validation errors
# ---------------------------------------------------------------------------


class ParseError(Exception):
    """Cannot extract rules from input text (malformed, empty, or unsupported structure)."""


class ValidationError(Exception):
    """Rule dict missing required field(s), has wrong type, or violates a field constraint."""


# ---------------------------------------------------------------------------
# Audit errors
# ---------------------------------------------------------------------------


class AuditError(Exception):
    """Source URL unreachable after all retries during reverse-audit."""


class AmbiguityError(Exception):
    """Ambiguity taxonomy lookup failed (bad type_code or taxonomy not loaded)."""


# ---------------------------------------------------------------------------
# Monitoring errors
# ---------------------------------------------------------------------------


class GazetteMonitorError(Exception):
    """Gazette RSS/Atom feed is malformed, unreachable, or failed to parse."""


# ---------------------------------------------------------------------------
# Matching engine errors (Part 3)
# ---------------------------------------------------------------------------


class CBCError(Exception):
    """Base class for all matching-engine errors."""


class InvalidProfileError(CBCError):
    """Profile validation failure — a mandatory field is missing or inconsistent."""

    def __init__(self, field: str, reason: str, suggestion: str = "") -> None:
        self.field = field
        self.reason = reason
        self.suggestion = suggestion
        super().__init__(f"Invalid profile field '{field}': {reason}")


class RuleBaseError(CBCError):
    """Rule base loading failure — empty directory, broken supersession chain, or DMN parse error."""

    def __init__(self, message: str, affected_schemes: list[str] | None = None) -> None:
        self.message = message
        self.affected_schemes = affected_schemes or []
        super().__init__(message)


class EvaluationError(CBCError):
    """Per-rule evaluation error — caught internally by the engine and marked UNDETERMINED."""

    def __init__(self, rule_id: str, reason: str) -> None:
        self.rule_id = rule_id
        self.reason = reason
        super().__init__(f"Evaluation error for rule '{rule_id}': {reason}")
