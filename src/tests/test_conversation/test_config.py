"""Additional tests for src.conversation.config."""

from __future__ import annotations

import os

import pytest

from src.conversation.config import (
    DEFAULT_LANGUAGE,
    DEFAULT_RULE_BASE_PATH,
    LLM_MAX_RETRIES,
    LLM_MODEL,
    LLM_PROVIDER,
    LLM_TIMEOUT_SECONDS,
    MAX_FOLLOWUP_QUESTIONS_PER_TURN,
    MAX_MESSAGE_LENGTH,
    MAX_TURNS_BEFORE_MATCHING,
    MIN_VIABLE_FIELDS,
    MINIMUM_VIABLE_FIELDS,
    RECOMMENDED_FIELDS,
    SESSION_ENCRYPTION_KEY_ENV,
    SESSION_MAX_TOKEN_SIZE_KB,
    SESSION_TTL_HOURS,
    SUPPORTED_LANGUAGES,
)


class TestConfigDefaults:
    """Verify config defaults are sane."""

    def test_llm_provider(self) -> None:
        assert LLM_PROVIDER == "gemini"

    def test_llm_model(self) -> None:
        assert "gemini" in LLM_MODEL or "flash" in LLM_MODEL

    def test_session_ttl(self) -> None:
        assert SESSION_TTL_HOURS >= 1
        assert SESSION_TTL_HOURS <= 24

    def test_max_message_length(self) -> None:
        assert MAX_MESSAGE_LENGTH >= 1000
        assert MAX_MESSAGE_LENGTH <= 50000

    def test_max_retries(self) -> None:
        assert LLM_MAX_RETRIES >= 1
        assert LLM_MAX_RETRIES <= 5

    def test_supported_languages(self) -> None:
        assert "en" in SUPPORTED_LANGUAGES
        assert "hi" in SUPPORTED_LANGUAGES
        assert "hinglish" in SUPPORTED_LANGUAGES

    def test_default_language(self) -> None:
        assert DEFAULT_LANGUAGE == "en"

    def test_minimum_viable_fields(self) -> None:
        assert len(MINIMUM_VIABLE_FIELDS) >= 3
        assert "applicant.age" in MINIMUM_VIABLE_FIELDS
        assert "location.state" in MINIMUM_VIABLE_FIELDS

    def test_recommended_fields(self) -> None:
        assert len(RECOMMENDED_FIELDS) >= 3
        # Recommended fields should not overlap with minimum
        assert not MINIMUM_VIABLE_FIELDS & RECOMMENDED_FIELDS

    def test_followup_limit(self) -> None:
        assert MAX_FOLLOWUP_QUESTIONS_PER_TURN >= 1
        assert MAX_FOLLOWUP_QUESTIONS_PER_TURN <= 5

    def test_token_size_limit(self) -> None:
        assert SESSION_MAX_TOKEN_SIZE_KB >= 5
        assert SESSION_MAX_TOKEN_SIZE_KB <= 50
