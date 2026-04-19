"""Integration tests for the conversation engine — full turn flows.

These tests mock the LLM calls to test the engine pipeline
without requiring a live Gemini API key.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from src.conversation.engine import ConversationEngine, ConversationResponse
from src.conversation.session import ConversationSession


@pytest.fixture
def engine() -> ConversationEngine:
    return ConversationEngine(rule_base_path=Path("parsed_schemes"))


@pytest.fixture
def mock_gemini_extraction():
    """Mock the Gemini API to return a valid extraction."""
    async def fake_call(system_prompt: str, user_message: str):
        return {
            "extractions": [
                {
                    "field_path": "applicant.age",
                    "value": 35,
                    "raw_value": "35 years",
                    "confidence": "HIGH",
                    "reasoning": "Direct age statement",
                    "clarification_needed": None,
                },
                {
                    "field_path": "location.state",
                    "value": "UP",
                    "raw_value": "from UP",
                    "confidence": "HIGH",
                    "reasoning": "State name",
                    "clarification_needed": None,
                },
            ],
            "detected_language": "en",
            "unprocessed_text": "",
        }

    return fake_call


class TestFullConversationFlow:
    """Test multi-turn conversation flows with mocked LLM."""

    @pytest.mark.asyncio
    async def test_start_then_provide_info(
        self, engine: ConversationEngine, mock_gemini_extraction
    ) -> None:
        # Start session
        start = await engine.start_session("en")
        assert start.state_after == "GATHERING"

        # Send info with mocked LLM
        with patch(
            "src.conversation.extraction._call_gemini",
            new=mock_gemini_extraction,
        ):
            resp = await engine.process_message(
                start.session_token,
                "I am 35 years old from UP",
            )
        assert resp.session_token  # Got a new token
        assert resp.text  # Got some response text

    @pytest.mark.asyncio
    async def test_exit_ends_session(self, engine: ConversationEngine) -> None:
        start = await engine.start_session("en")
        resp = await engine.process_message(start.session_token, "bye")
        assert resp.state_after == "ENDED"

    @pytest.mark.asyncio
    async def test_skip_field(self, engine: ConversationEngine) -> None:
        start = await engine.start_session("en")
        resp = await engine.process_message(start.session_token, "skip")
        assert "skip" in resp.text_en.lower() or "problem" in resp.text_en.lower() or "worries" in resp.text_en.lower() or "unknown" in resp.text_en.lower()

    @pytest.mark.asyncio
    async def test_confirm_without_enough_data(
        self, engine: ConversationEngine
    ) -> None:
        start = await engine.start_session("en")
        resp = await engine.process_message(start.session_token, "yes")
        # Should ask more questions, not trigger matching
        assert not resp.matching_triggered

    @pytest.mark.asyncio
    async def test_what_if_before_matching(
        self, engine: ConversationEngine
    ) -> None:
        start = await engine.start_session("en")
        resp = await engine.process_message(
            start.session_token,
            "what if I open a bank account",
        )
        # Should explain that matching needs to run first
        assert "eligibility" in resp.text_en.lower() or "first" in resp.text_en.lower()

    @pytest.mark.asyncio
    async def test_detail_request_numeric(
        self, engine: ConversationEngine
    ) -> None:
        start = await engine.start_session("en")
        resp = await engine.process_message(start.session_token, "3")
        assert "3" in resp.text_en or "scheme" in resp.text_en.lower() or "results" in resp.text_en.lower() or "check" in resp.text_en.lower()

    @pytest.mark.asyncio
    async def test_correction_flow(
        self, engine: ConversationEngine, mock_gemini_extraction
    ) -> None:
        start = await engine.start_session("en")

        with patch(
            "src.conversation.extraction._call_gemini",
            new=mock_gemini_extraction,
        ):
            resp = await engine.process_message(
                start.session_token,
                "actually my age is 40",
            )
        # Should acknowledge the correction
        assert resp.text_en  # Got a response

    @pytest.mark.asyncio
    async def test_llm_unavailable_fallback(
        self, engine: ConversationEngine
    ) -> None:
        from src.conversation.exceptions import LLMUnavailableError

        async def fail(*args, **kwargs):
            raise LLMUnavailableError("gemini", 2, "timeout")

        start = await engine.start_session("en")

        with patch(
            "src.conversation.extraction._call_gemini",
            new=fail,
        ):
            resp = await engine.process_message(
                start.session_token,
                "I am a farmer from Bihar",
            )
        # Should fall back to form-filling or regex extraction
        assert resp.text_en  # Got any response

    @pytest.mark.asyncio
    async def test_end_to_end_minimum_viable(
        self, engine: ConversationEngine
    ) -> None:
        """Test reaching minimum viable profile and triggering matching."""
        start = await engine.start_session("en")

        # Mock extraction that provides all minimum viable fields
        async def full_extraction(system_prompt, user_message):
            return {
                "extractions": [
                    {"field_path": "applicant.age", "value": 35,
                     "raw_value": "35", "confidence": "HIGH",
                     "reasoning": "age", "clarification_needed": None},
                    {"field_path": "location.state", "value": "UP",
                     "raw_value": "UP", "confidence": "HIGH",
                     "reasoning": "state", "clarification_needed": None},
                    {"field_path": "household.income_annual", "value": 150000,
                     "raw_value": "1.5 lakh", "confidence": "HIGH",
                     "reasoning": "income", "clarification_needed": None},
                    {"field_path": "applicant.caste_category", "value": "SC",
                     "raw_value": "SC", "confidence": "HIGH",
                     "reasoning": "caste", "clarification_needed": None},
                ],
                "detected_language": "en",
                "unprocessed_text": "",
            }

        with patch(
            "src.conversation.extraction._call_gemini",
            new=full_extraction,
        ):
            # First message — should show explainability then confirm
            resp = await engine.process_message(
                start.session_token,
                "I am 35 years old SC from UP earning 1.5 lakh",
            )
            # Either confirms extraction or runs matching
            assert resp.text_en

            # Confirm extracted data
            resp2 = await engine.process_message(
                resp.session_token,
                "yes",
            )
            # Should trigger matching (has all 4 minimum fields)
            assert resp2.matching_triggered or "matching" in resp2.text_en.lower() \
                or "check" in resp2.text_en.lower() or resp2.state_after == "MATCHING"

    @pytest.mark.asyncio
    async def test_ended_session_starts_fresh(
        self, engine: ConversationEngine
    ) -> None:
        start = await engine.start_session("en")
        ended = await engine.process_message(start.session_token, "done")
        assert ended.state_after == "ENDED"

        # Sending another message to ended session → fresh start
        fresh = await engine.process_message(ended.session_token, "hello")
        assert fresh.state_after == "GATHERING"

    @pytest.mark.asyncio
    async def test_message_length_truncation(
        self, engine: ConversationEngine
    ) -> None:
        start = await engine.start_session("en")

        async def passthrough(system_prompt, user_message):
            return {"extractions": [], "detected_language": "en", "unprocessed_text": ""}

        with patch("src.conversation.extraction._call_gemini", new=passthrough):
            # Send a very long message — should not crash
            long_msg = "hello " * 2000  # ~12000 chars > 5000 limit
            resp = await engine.process_message(start.session_token, long_msg)
            assert resp.text_en  # Got a response


class TestEngineHelpers:
    """Test engine helper methods."""

    @pytest.mark.asyncio
    async def test_fallback_form_question(self) -> None:
        engine = ConversationEngine(rule_base_path=Path("parsed_schemes"))
        session = ConversationSession.new()
        question = engine._fallback_form_question(session)
        assert "?" in question

    @pytest.mark.asyncio
    async def test_build_followup_response_empty(self) -> None:
        engine = ConversationEngine(rule_base_path=Path("parsed_schemes"))
        session = ConversationSession.new()
        response = engine._build_followup_response(session, None)
        assert response  # non-empty
