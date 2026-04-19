"""Configuration constants for CBC Part 1.

All values are read from environment variables when set, falling back to
the defaults defined here.  No value in this codebase should be hardcoded
outside this module.

Usage:
    from src.config import BATCH_SIZE, AUDIT_SIMILARITY_THRESHOLD
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


def _env_path(key: str, default: str) -> Path:
    return Path(os.environ.get(key, default))


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

BATCH_SIZE: int = _env_int("CBC_BATCH_SIZE", 50)

# ---------------------------------------------------------------------------
# Audit / similarity thresholds
# ---------------------------------------------------------------------------

AUDIT_SIMILARITY_THRESHOLD: float = _env_float("AUDIT_SIMILARITY_THRESHOLD", 0.90)
AUDIT_NEEDS_REVIEW_THRESHOLD: float = _env_float("AUDIT_NEEDS_REVIEW_THRESHOLD", 0.70)
STALENESS_CUTOFF_DAYS: int = _env_int("STALENESS_CUTOFF_DAYS", 90)

# ---------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------

GAZETTE_POLL_INTERVAL_HOURS: int = _env_int("GAZETTE_POLL_INTERVAL_HOURS", 24)

# ---------------------------------------------------------------------------
# File / network
# ---------------------------------------------------------------------------

MAX_PDF_SIZE_MB: int = _env_int("MAX_PDF_SIZE_MB", 50)

# ---------------------------------------------------------------------------
# Sentence-Transformers models
# ---------------------------------------------------------------------------

SIMILARITY_MODEL_DEV: str = _env_str("SIMILARITY_MODEL_DEV", "all-MiniLM-L6-v2")
SIMILARITY_MODEL_PROD: str = _env_str("SIMILARITY_MODEL_PROD", "all-mpnet-base-v2")

# Active model — override with CBC_SIMILARITY_MODEL env var
SIMILARITY_MODEL: str = _env_str("CBC_SIMILARITY_MODEL", SIMILARITY_MODEL_DEV)

# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------

TEMP_DIR: Path = _env_path("CBC_TEMP_DIR", "/tmp/cbc_part1")
OUTPUT_DIR: Path = _env_path("CBC_OUTPUT_DIR", "part1-planning/output")

# ---------------------------------------------------------------------------
# myScheme base URL
# ---------------------------------------------------------------------------

MYSCHEME_BASE_URL: str = _env_str(
    "MYSCHEME_BASE_URL", "https://www.myscheme.gov.in/schemes"
)

# ---------------------------------------------------------------------------
# Matching engine constants (Part 3)
# ---------------------------------------------------------------------------

ENGINE_VERSION: str = _env_str("ENGINE_VERSION", "2.0.0")

# Near-miss thresholds
NEAR_MISS_MAX_FAILED_RULES: int = _env_int("NEAR_MISS_MAX_FAILED_RULES", 2)
NEAR_MISS_INCOME_PROXIMITY: float = _env_float("NEAR_MISS_INCOME_PROXIMITY", 0.15)
NEAR_MISS_AGE_PROXIMITY: int = _env_int("NEAR_MISS_AGE_PROXIMITY", 2)
NEAR_MISS_LAND_PROXIMITY: float = _env_float("NEAR_MISS_LAND_PROXIMITY", 0.20)

# Profile completeness
PROFILE_COMPLETE_THRESHOLD: float = _env_float("PROFILE_COMPLETE_THRESHOLD", 0.60)

# Scoring
UNVERIFIED_PASS_SCORE: float = _env_float("UNVERIFIED_PASS_SCORE", 0.70)
CRITICAL_AMB_DATA_CAP: float = _env_float("CRITICAL_AMB_DATA_CAP", 0.30)
HIGH_AMB_PENALTY: float = _env_float("HIGH_AMB_PENALTY", 0.15)
MEDIUM_AMB_PENALTY: float = _env_float("MEDIUM_AMB_PENALTY", 0.05)
MAX_COMPOSITE_NO_VERIFIED: float = _env_float("MAX_COMPOSITE_NO_VERIFIED", 0.50)

# Group nesting
MAX_GROUP_NESTING_DEPTH: int = _env_int("MAX_GROUP_NESTING_DEPTH", 3)

# Tier default confidence
TIER_1_DEFAULT_CONFIDENCE: float = _env_float("TIER_1_DEFAULT_CONFIDENCE", 0.70)
TIER_2_DEFAULT_CONFIDENCE: float = _env_float("TIER_2_DEFAULT_CONFIDENCE", 0.95)
TIER_3_DEFAULT_CONFIDENCE: float = _env_float("TIER_3_DEFAULT_CONFIDENCE", 0.50)

# Kaggle ingestion
KAGGLE_BATCH_SIZE: int = _env_int("KAGGLE_BATCH_SIZE", 50)

# Concurrency cap for asyncio.gather across schemes
MAX_SCHEMES_CONCURRENT: int = _env_int("MAX_SCHEMES_CONCURRENT", 100)

# ---------------------------------------------------------------------------
# Canonical field namespace (50+ paths used in rule.field)
# Full definition lives in spec_04_rule_expression.py (FIELD_NAMESPACE).
# This import path is referenced from config for other modules that need it
# without pulling in the full DSL module.
# ---------------------------------------------------------------------------

# (See FIELD_NAMESPACE in spec_04_rule_expression.py)
