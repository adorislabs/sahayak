"""Tests for src.conversation.exceptions."""

from __future__ import annotations

import pytest

from src.conversation.exceptions import (
    ContradictionError,
    ConversationError,
    ExtractionError,
    LLMUnavailableError,
    SessionError,
    TranslationError,
)
from src.exceptions import CBCError


class TestExceptionHierarchy:
    """Verify all Part 5 exceptions inherit correctly."""

    def test_conversation_error_inherits_cbc_error(self) -> None:
        exc = ConversationError("test")
        assert isinstance(exc, CBCError)
        assert isinstance(exc, Exception)

    def test_extraction_error(self) -> None:
        exc = ExtractionError("bad json", raw_response='{"broken"')
        assert isinstance(exc, ConversationError)
        assert exc.raw_response == '{"broken"'
        assert "bad json" in str(exc)

    def test_llm_unavailable_error(self) -> None:
        exc = LLMUnavailableError(
            provider="gemini", attempts=3, last_error="timeout"
        )
        assert isinstance(exc, ConversationError)
        assert exc.provider == "gemini"
        assert exc.attempts == 3
        assert "timeout" in str(exc)
        assert "gemini" in str(exc)

    def test_session_error_with_id(self) -> None:
        exc = SessionError(reason="expired", session_id="abc123")
        assert isinstance(exc, ConversationError)
        assert exc.session_id == "abc123"
        assert "expired" in str(exc)
        assert "abc123" in str(exc)

    def test_session_error_without_id(self) -> None:
        exc = SessionError(reason="corrupt")
        assert exc.session_id is None
        assert "corrupt" in str(exc)

    def test_translation_error(self) -> None:
        exc = TranslationError(
            source_language="hi",
            target_language="en",
            message="API down",
        )
        assert isinstance(exc, ConversationError)
        assert "hi → en" in str(exc)

    def test_contradiction_error(self) -> None:
        exc = ContradictionError(
            field_path="applicant.age",
            existing_value=35,
            new_value=40,
        )
        assert isinstance(exc, ConversationError)
        assert exc.field_path == "applicant.age"
        assert exc.existing_value == 35
        assert exc.new_value == 40
        assert "applicant.age" in str(exc)

    def test_all_catchable_as_cbc_error(self) -> None:
        """All Part 5 exceptions should be catchable as CBCError."""
        exceptions = [
            ConversationError("a"),
            ExtractionError("b"),
            LLMUnavailableError("c", 1, "d"),
            SessionError("e"),
            TranslationError("f", "g"),
            ContradictionError("h", 1, 2),
        ]
        for exc in exceptions:
            try:
                raise exc
            except CBCError:
                pass  # Should always be caught here
