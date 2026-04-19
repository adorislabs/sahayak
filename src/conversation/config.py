"""Configuration constants for CBC Part 5 — Conversational Interface.

All values are read from environment variables when set, falling back to
the defaults defined here.  Mirrors the pattern established in ``src.config``.
"""

from __future__ import annotations

import os
from pathlib import Path


def _env_int(key: str, default: int) -> int:
    return int(os.environ.get(key, default))


def _env_float(key: str, default: float) -> float:
    return float(os.environ.get(key, default))


def _env_str(key: str, default: str) -> str:
    return os.environ.get(key, default)


# ---------------------------------------------------------------------------
# LLM provider
# ---------------------------------------------------------------------------

LLM_PROVIDER: str = _env_str("CBC_LLM_PROVIDER", "gemini")
LLM_MODEL: str = _env_str("CBC_LLM_MODEL", "gemini-2.0-flash")
LLM_FALLBACK_MODEL: str = _env_str(
    "CBC_LLM_FALLBACK_MODEL", "google/gemma-3-27b-it"
)
LLM_TIMEOUT_SECONDS: int = _env_int("CBC_LLM_TIMEOUT", 10)
LLM_MAX_RETRIES: int = _env_int("CBC_LLM_MAX_RETRIES", 2)

# API keys (read at runtime — never hardcoded)
GEMINI_API_KEY_ENV: str = "GEMINI_API_KEY"
OPENROUTER_API_KEY_ENV: str = "OPENROUTER_API_KEY"

# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

SESSION_TTL_HOURS: int = _env_int("CBC_SESSION_TTL_HOURS", 72)  # 3 days
SESSION_MAX_TOKEN_SIZE_KB: int = _env_int("CBC_SESSION_MAX_TOKEN_KB", 10)
SESSION_ENCRYPTION_KEY_ENV: str = "CBC_SESSION_KEY"

# ---------------------------------------------------------------------------
# Conversation flow
# ---------------------------------------------------------------------------

MAX_TURNS_BEFORE_MATCHING: int = _env_int("CBC_MAX_TURNS", 10)
MIN_VIABLE_FIELDS: int = _env_int("CBC_MIN_FIELDS", 4)
MAX_FOLLOWUP_QUESTIONS_PER_TURN: int = _env_int("CBC_MAX_QUESTIONS", 3)
MAX_MESSAGE_LENGTH: int = _env_int("CBC_MAX_MSG_LEN", 5000)

# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

RESPONSE_TIMEOUT_SECONDS: int = _env_int("CBC_RESPONSE_TIMEOUT", 5)
EXTRACTION_TIMEOUT_SECONDS: int = _env_int("CBC_EXTRACTION_TIMEOUT", 3)

# ---------------------------------------------------------------------------
# Language
# ---------------------------------------------------------------------------

DEFAULT_LANGUAGE: str = _env_str("CBC_DEFAULT_LANG", "en")
SUPPORTED_LANGUAGES: list[str] = ["en", "hi", "hinglish"]

# ---------------------------------------------------------------------------
# Rule base (overridable — defaults to shared parsed_schemes dir)
# ---------------------------------------------------------------------------

DEFAULT_RULE_BASE_PATH: Path = Path(
    _env_str("CBC_RULE_BASE_PATH", "parsed_schemes")
)

# ---------------------------------------------------------------------------
# Minimum viable profile — fields needed before first matching run
# ---------------------------------------------------------------------------

MINIMUM_VIABLE_FIELDS: frozenset[str] = frozenset({
    "applicant.age",
    "location.state",
    "household.income_annual",
    "applicant.caste_category",
})

RECOMMENDED_FIELDS: frozenset[str] = frozenset({
    "applicant.gender",
    "employment.type",
    "applicant.land_ownership_status",
    "documents.aadhaar",
    "documents.bank_account",
})
