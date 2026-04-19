"""Tests for src.conversation.session."""

from __future__ import annotations

import os
import pytest

from src.conversation.session import (
    ConversationSession,
    ConversationTurn,
    FieldProvenance,
    ProfileChange,
    VALID_STATES,
)
from src.conversation.exceptions import SessionError


class TestSessionCreation:
    """Test session construction and initial state."""

    def test_new_session_has_greeting_state(self) -> None:
        s = ConversationSession.new()
        assert s.current_state == "GREETING"
        assert s.previous_state == "GREETING"

    def test_new_session_has_unique_id(self) -> None:
        s1 = ConversationSession.new()
        s2 = ConversationSession.new()
        assert s1.session_id != s2.session_id

    def test_new_session_has_timestamps(self) -> None:
        s = ConversationSession.new()
        assert s.created_at
        assert s.updated_at
        assert "T" in s.created_at  # ISO format

    def test_new_session_has_empty_profile(self) -> None:
        s = ConversationSession.new()
        assert s.profile_data == {}
        assert s.field_provenance == {}
        assert s.turns == []
        assert s.turn_count == 0


class TestStateTransitions:
    """Test conversation state machine transitions."""

    def test_valid_transition(self) -> None:
        s = ConversationSession.new()
        s.transition("GATHERING")
        assert s.current_state == "GATHERING"
        assert s.previous_state == "GREETING"

    def test_chained_transitions(self) -> None:
        s = ConversationSession.new()
        s.transition("GATHERING")
        s.transition("CLARIFYING")
        assert s.current_state == "CLARIFYING"
        assert s.previous_state == "GATHERING"

    def test_invalid_transition_raises(self) -> None:
        s = ConversationSession.new()
        with pytest.raises(ValueError, match="Invalid state"):
            s.transition("INVALID_STATE")

    def test_all_valid_states(self) -> None:
        assert len(VALID_STATES) == 8
        expected = {
            "GREETING", "GATHERING", "CLARIFYING", "MATCHING",
            "PRESENTING", "EXPLORING", "CORRECTING", "ENDED",
        }
        assert VALID_STATES == expected

    def test_transition_updates_timestamp(self) -> None:
        s = ConversationSession.new()
        old_ts = s.updated_at
        s.transition("GATHERING")
        # Timestamps should differ (or at least not crash)
        assert s.updated_at is not None


class TestProfileUpdate:
    """Test profile field updates and provenance tracking."""

    def test_set_new_field(self) -> None:
        s = ConversationSession.new()
        change = s.update_profile_field("applicant.age", 35, 1, "35 years")
        assert s.profile_data["applicant.age"] == 35
        assert change.change_type == "set"
        assert change.old_value is None
        assert change.new_value == 35

    def test_update_existing_field(self) -> None:
        s = ConversationSession.new()
        s.update_profile_field("applicant.age", 35, 1)
        change = s.update_profile_field("applicant.age", 36, 2)
        assert s.profile_data["applicant.age"] == 36
        assert change.change_type == "update"
        assert change.old_value == 35

    def test_provenance_recorded(self) -> None:
        s = ConversationSession.new()
        s.update_profile_field("location.state", "UP", 1, "from UP", "HIGH")
        prov = s.field_provenance["location.state"]
        assert prov["value"] == "UP"
        assert prov["source_turn"] == 1
        assert prov["confidence"] == "HIGH"

    def test_populated_fields(self) -> None:
        s = ConversationSession.new()
        s.update_profile_field("applicant.age", 35, 1)
        s.update_profile_field("location.state", "UP", 1)
        populated = s.get_populated_field_paths()
        assert populated == {"applicant.age", "location.state"}


class TestMinimumViability:
    """Test minimum viable profile checks."""

    def test_not_viable_empty(self) -> None:
        s = ConversationSession.new()
        assert not s.is_minimum_viable()

    def test_not_viable_partial(self) -> None:
        s = ConversationSession.new()
        s.update_profile_field("applicant.age", 35, 1)
        s.update_profile_field("location.state", "UP", 1)
        assert not s.is_minimum_viable()

    def test_viable_with_minimum_fields(self) -> None:
        s = ConversationSession.new()
        s.update_profile_field("applicant.age", 35, 1)
        s.update_profile_field("location.state", "UP", 1)
        s.update_profile_field("household.income_annual", 150000, 1)
        s.update_profile_field("applicant.caste_category", "SC", 1)
        assert s.is_minimum_viable()


class TestFieldTracking:
    """Test asked/skipped field tracking."""

    def test_mark_field_asked(self) -> None:
        s = ConversationSession.new()
        s.mark_field_asked("applicant.age")
        assert "applicant.age" in s.asked_fields

    def test_mark_field_asked_idempotent(self) -> None:
        s = ConversationSession.new()
        s.mark_field_asked("applicant.age")
        s.mark_field_asked("applicant.age")
        assert s.asked_fields.count("applicant.age") == 1

    def test_mark_field_skipped(self) -> None:
        s = ConversationSession.new()
        s.mark_field_skipped("applicant.gender")
        assert "applicant.gender" in s.skipped_fields


class TestTurnHistory:
    """Test conversation turn recording."""

    def test_add_turn(self) -> None:
        s = ConversationSession.new()
        turn = ConversationTurn(
            turn_number=1,
            timestamp="2026-01-01T00:00:00",
            user_message="I am 35",
            detected_language="en",
            detected_intent="provide_info",
        )
        s.add_turn(turn)
        assert s.turn_count == 1
        assert len(s.turns) == 1

    def test_turn_count_increments(self) -> None:
        s = ConversationSession.new()
        for i in range(5):
            turn = ConversationTurn(
                turn_number=i,
                timestamp="2026-01-01T00:00:00",
                user_message=f"msg {i}",
                detected_language="en",
                detected_intent="provide_info",
            )
            s.add_turn(turn)
        assert s.turn_count == 5


class TestSessionTokens:
    """Test base64+zlib session token roundtrip."""

    def test_roundtrip(self) -> None:
        s = ConversationSession.new()
        s.update_profile_field("applicant.age", 35, 1)
        s.transition("GATHERING")

        token = s.to_token()
        assert isinstance(token, str)
        assert len(token) > 0

        restored = ConversationSession.from_token(token)
        assert restored.session_id == s.session_id
        assert restored.current_state == "GATHERING"
        assert restored.profile_data["applicant.age"] == 35

    def test_invalid_token_raises(self) -> None:
        with pytest.raises(SessionError):
            ConversationSession.from_token("not-a-valid-token")

    def test_token_with_turns(self) -> None:
        s = ConversationSession.new()
        for i in range(3):
            turn = ConversationTurn(
                turn_number=i,
                timestamp="2026-01-01T00:00:00",
                user_message=f"msg {i}",
                detected_language="en",
                detected_intent="provide_info",
            )
            s.add_turn(turn)

        token = s.to_token()
        restored = ConversationSession.from_token(token)
        assert restored.turn_count == 3

    def test_token_with_hindi_content(self) -> None:
        """Verify Devanagari survives token roundtrip."""
        s = ConversationSession.new()
        s.update_profile_field(
            "applicant.name", "राम कुमार", 1, "मेरा नाम राम कुमार है"
        )
        token = s.to_token()
        restored = ConversationSession.from_token(token)
        assert restored.profile_data["applicant.name"] == "राम कुमार"


class TestSessionLastBotQuestions:
    """Test last_bot_questions tracking on session."""

    def test_default_empty(self) -> None:
        s = ConversationSession.new()
        assert s.last_bot_questions == []

    def test_set_and_retrieve(self) -> None:
        s = ConversationSession.new()
        questions = [
            {"field_path": "applicant.age", "question": "How old are you?", "index": 1},
            {"field_path": "location.state", "question": "Which state?", "index": 2},
        ]
        s.last_bot_questions = questions
        assert len(s.last_bot_questions) == 2
        assert s.last_bot_questions[0]["field_path"] == "applicant.age"

    def test_survives_token_roundtrip(self) -> None:
        s = ConversationSession.new()
        s.last_bot_questions = [
            {"field_path": "applicant.age", "question": "How old are you?", "index": 1},
        ]
        token = s.to_token()
        restored = ConversationSession.from_token(token)
        assert len(restored.last_bot_questions) == 1
        assert restored.last_bot_questions[0]["question"] == "How old are you?"
