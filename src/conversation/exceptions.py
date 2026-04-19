"""Custom exception hierarchy for CBC Part 5 — Conversational Interface.

Every error scenario in the conversation layer maps to one of these classes.
The base class ``ConversationError`` inherits from the project-wide ``CBCError``
so that top-level handlers can catch the entire family.
"""

from __future__ import annotations

from typing import Any, Optional

from src.exceptions import CBCError


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class ConversationError(CBCError):
    """Base exception for all conversation-layer errors."""

    def __init__(self, message: str = "") -> None:
        self.message = message
        super().__init__(message)


# ---------------------------------------------------------------------------
# LLM / extraction
# ---------------------------------------------------------------------------


class ExtractionError(ConversationError):
    """LLM extraction returned invalid, unparseable, or empty results.

    Raised when the structured-output response cannot be decoded into
    ``ExtractionResult`` or violates the field schema.
    """

    def __init__(
        self,
        message: str,
        raw_response: Optional[str] = None,
    ) -> None:
        self.raw_response = raw_response
        super().__init__(message)


class LLMUnavailableError(ConversationError):
    """LLM API is unreachable after all retry attempts.

    Triggers the fallback form-filling mode in the conversation engine.
    """

    def __init__(
        self,
        provider: str,
        attempts: int,
        last_error: str,
    ) -> None:
        self.provider = provider
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"LLM provider '{provider}' unreachable after {attempts} "
            f"attempt(s): {last_error}"
        )


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


class SessionError(ConversationError):
    """Session token is corrupt, expired, or otherwise invalid.

    When caught by the engine, the response instructs the user that a
    fresh session will be started.
    """

    def __init__(
        self,
        reason: str,
        session_id: Optional[str] = None,
    ) -> None:
        self.session_id = session_id
        self.reason = reason
        super().__init__(
            f"Session error{f' ({session_id})' if session_id else ''}: {reason}"
        )


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------


class TranslationError(ConversationError):
    """Translation between Hindi/Hinglish and English failed.

    When caught, the engine falls back to the original language text
    without translation and logs the failure.
    """

    def __init__(
        self,
        source_language: str,
        target_language: str,
        message: str = "",
    ) -> None:
        self.source_language = source_language
        self.target_language = target_language
        super().__init__(
            f"Translation failed ({source_language} → {target_language}): {message}"
        )


# ---------------------------------------------------------------------------
# Contradiction
# ---------------------------------------------------------------------------


class ContradictionError(ConversationError):
    """An unresolved blocking contradiction prevents further processing.

    Raised when a new extraction directly conflicts with existing profile
    data and the conflict severity is ``blocking``.  The engine must surface
    a resolution dialog before continuing.
    """

    def __init__(
        self,
        field_path: str,
        existing_value: Any,
        new_value: Any,
    ) -> None:
        self.field_path = field_path
        self.existing_value = existing_value
        self.new_value = new_value
        super().__init__(
            f"Blocking contradiction on '{field_path}': "
            f"existing={existing_value!r} vs new={new_value!r}"
        )
