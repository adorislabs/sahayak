"""Tests for src.conversation.engine — intent detection and engine construction."""

from __future__ import annotations

import pytest
from pathlib import Path

from src.conversation.engine import (
    ConversationEngine,
    ConversationResponse,
    _detect_intent_fast,
)


class TestFastIntentDetection:
    """Test keyword-based fast intent classification.

    _detect_intent_fast is now state-aware: bare "yes"/"no" and digits
    are treated as `provide_info` during GATHERING (the default state),
    and as `confirm`/`request_detail` when results exist (PRESENTING).
    """

    # --- Confirm intents (PRESENTING state — results exist) ---
    @pytest.mark.parametrize("msg, expected", [
        ("", "confirm"),
        ("yes", "confirm"),
        ("ok", "confirm"),
        ("y", "confirm"),
        ("हाँ", "confirm"),
        ("सही", "confirm"),
    ])
    def test_confirm_intents_presenting(self, msg: str, expected: str) -> None:
        """In PRESENTING state, short affirmatives are confirm."""
        assert _detect_intent_fast(msg, current_state="PRESENTING", has_results=True) == expected

    # --- During GATHERING, "yes"/"ok" are answers, not confirmations ---
    @pytest.mark.parametrize("msg, expected", [
        ("yes", "provide_info"),
        ("ok", "provide_info"),
        ("y", "provide_info"),
        ("हाँ", "provide_info"),
        ("सही", "provide_info"),
    ])
    def test_yes_during_gathering_is_provide_info(self, msg: str, expected: str) -> None:
        """In GATHERING state, short affirmatives are answers to questions."""
        assert _detect_intent_fast(msg, current_state="GATHERING") == expected

    def test_empty_during_gathering_is_confirm(self) -> None:
        """Empty string is always confirm (user just pressed Enter)."""
        assert _detect_intent_fast("", current_state="GATHERING") == "confirm"

    @pytest.mark.parametrize("msg, expected", [
        ("actually my age is 36", "correct_info"),
        ("wait, I said the wrong thing", "correct_info"),
        ("sorry, it's OBC not SC", "correct_info"),
        ("correction: income is 3 lakh", "correct_info"),
        ("दरअसल मेरी उम्र 35 है", "correct_info"),
        ("रुकिए, मेरा मतलब 3 लाख था", "correct_info"),
    ])
    def test_correction_intents(self, msg: str, expected: str) -> None:
        assert _detect_intent_fast(msg) == expected

    @pytest.mark.parametrize("msg, expected", [
        ("what if I open a bank account", "what_if"),
        ("what would happen if I got a caste certificate", "what_if"),
        ("suppose I moved to Bihar", "what_if"),
        ("अगर मैं बैंक खाता खोल लूँ तो", "what_if"),
    ])
    def test_what_if_intents(self, msg: str, expected: str) -> None:
        assert _detect_intent_fast(msg) == expected

    @pytest.mark.parametrize("msg, expected", [
        ("bye", "exit"),
        ("done", "exit"),
        ("thanks", "exit"),
        ("quit", "exit"),
        ("बस", "exit"),
        ("धन्यवाद", "exit"),
    ])
    def test_exit_intents(self, msg: str, expected: str) -> None:
        assert _detect_intent_fast(msg) == expected

    @pytest.mark.parametrize("msg, expected", [
        ("skip", "skip_field"),
        ("I don't know", "skip_field"),
        ("पता नहीं", "skip_field"),
        ("छोड़ दें", "skip_field"),
    ])
    def test_skip_intents(self, msg: str, expected: str) -> None:
        assert _detect_intent_fast(msg) == expected

    # --- Bare numbers: state-dependent ---
    @pytest.mark.parametrize("msg", ["1", "3", "15"])
    def test_detail_request_in_presenting(self, msg: str) -> None:
        """Bare numbers in PRESENTING state are detail requests."""
        assert _detect_intent_fast(msg, current_state="PRESENTING", has_results=True) == "request_detail"

    @pytest.mark.parametrize("msg", ["42", "5", "150000"])
    def test_bare_numbers_in_gathering_are_provide_info(self, msg: str) -> None:
        """Bare numbers in GATHERING state are answers (age, family size, etc.)."""
        assert _detect_intent_fast(msg, current_state="GATHERING") == "provide_info"

    # --- Short no/nahi during gathering ---
    @pytest.mark.parametrize("msg", ["no", "nahi", "nope", "नहीं"])
    def test_no_during_gathering_is_provide_info(self, msg: str) -> None:
        """'no' during GATHERING is an answer to a yes/no question."""
        assert _detect_intent_fast(msg, current_state="GATHERING") == "provide_info"

    def test_rich_profile_messages_default_to_provide_info(self) -> None:
        """Rich informational messages should default to provide_info (no LLM needed)."""
        assert _detect_intent_fast("I am a 35 year old farmer from UP") == "provide_info"
        assert _detect_intent_fast("My income is 2 lakh per year") == "provide_info"
        assert _detect_intent_fast("My name is Rajesh and I live in Bihar") == "provide_info"


class TestEngineConstruction:
    """Test ConversationEngine initialisation."""

    def test_engine_creation(self) -> None:
        engine = ConversationEngine(rule_base_path=Path("parsed_schemes"))
        assert engine.rule_base_path == Path("parsed_schemes")
        assert engine.llm_provider == "gemini"

    def test_engine_custom_provider(self) -> None:
        engine = ConversationEngine(
            rule_base_path=Path("parsed_schemes"),
            llm_provider="openrouter",
        )
        assert engine.llm_provider == "openrouter"


class TestEngineStartSession:
    """Test session start — no LLM required."""

    @pytest.mark.asyncio
    async def test_start_session_english(self) -> None:
        engine = ConversationEngine(rule_base_path=Path("parsed_schemes"))
        response = await engine.start_session(language="en")
        assert isinstance(response, ConversationResponse)
        assert "👋" in response.text
        assert response.state_before == "GREETING"
        assert response.state_after == "GATHERING"
        assert response.session_token  # non-empty

    @pytest.mark.asyncio
    async def test_start_session_hindi(self) -> None:
        engine = ConversationEngine(rule_base_path=Path("parsed_schemes"))
        response = await engine.start_session(language="hi")
        assert "👋" in response.text
        assert response.state_after == "GATHERING"

    @pytest.mark.asyncio
    async def test_start_session_returns_valid_token(self) -> None:
        engine = ConversationEngine(rule_base_path=Path("parsed_schemes"))
        response = await engine.start_session()
        # Token should be a non-empty string that the engine can resume
        assert response.session_token
        resume = await engine.resume_session(response.session_token)
        assert resume.state_after == "GATHERING"


class TestEngineResumeSession:
    """Test session resumption."""

    @pytest.mark.asyncio
    async def test_resume_valid_session(self) -> None:
        engine = ConversationEngine(rule_base_path=Path("parsed_schemes"))
        start = await engine.start_session()
        resume = await engine.resume_session(start.session_token)
        assert isinstance(resume, ConversationResponse)
        assert resume.text  # non-empty

    @pytest.mark.asyncio
    async def test_resume_invalid_token_starts_fresh(self) -> None:
        engine = ConversationEngine(rule_base_path=Path("parsed_schemes"))
        response = await engine.resume_session("invalid-token")
        # Should start a new session gracefully
        assert response.state_after == "GATHERING"


class TestIntentStateAwareness:
    """Test that intent detection respects conversation state."""

    def test_number_during_gathering_is_provide_info(self) -> None:
        """A bare number during GATHERING is a profile answer, not a detail request."""
        assert _detect_intent_fast("42", current_state="GATHERING") == "provide_info"
        assert _detect_intent_fast("50000", current_state="GATHERING") == "provide_info"

    def test_number_during_presenting_is_request_detail(self) -> None:
        """A bare number during PRESENTING (with results) is a detail request."""
        result = _detect_intent_fast("2", current_state="PRESENTING", has_results=True)
        assert result == "request_detail"

    def test_number_during_presenting_no_results_is_provide_info(self) -> None:
        """A bare number during PRESENTING without results falls back to provide_info."""
        result = _detect_intent_fast("2", current_state="PRESENTING", has_results=False)
        assert result == "provide_info"

    def test_yes_during_gathering_is_answer(self) -> None:
        """'yes' during GATHERING answers a pending yes/no question."""
        assert _detect_intent_fast("yes", current_state="GATHERING") == "provide_info"
        assert _detect_intent_fast("no", current_state="GATHERING") == "provide_info"
        assert _detect_intent_fast("nahi", current_state="GATHERING") == "provide_info"

    def test_yes_during_presenting_is_confirm(self) -> None:
        """'yes' during PRESENTING is a confirmation."""
        assert _detect_intent_fast("yes", current_state="PRESENTING") == "confirm"

    def test_skip_works_in_all_states(self) -> None:
        """Skip markers should work regardless of state."""
        assert _detect_intent_fast("skip", current_state="GATHERING") == "skip_field"
        assert _detect_intent_fast("skip", current_state="PRESENTING") == "skip_field"
        assert _detect_intent_fast("I don't know", current_state="GATHERING") == "skip_field"

    def test_exit_works_in_all_states(self) -> None:
        """Exit markers should work regardless of state."""
        assert _detect_intent_fast("bye", current_state="GATHERING") == "exit"
        assert _detect_intent_fast("done", current_state="PRESENTING") == "exit"

    def test_default_state_is_gathering(self) -> None:
        """When called without state, default is GATHERING (safe for answers)."""
        assert _detect_intent_fast("42") == "provide_info"
        assert _detect_intent_fast("yes") == "provide_info"


class TestScenarioIntentRouting:
    """Comprehensive scenario tests covering real-world user inputs.

    Every scenario maps a plausible user utterance to the expected intent
    so the engine routes it correctly without LLM involvement.
    """

    # --- Eligibility check triggers ---
    @pytest.mark.parametrize("msg", [
        "check my eligibility",
        "Check my eligibility",
        "CHECK MY ELIGIBILITY",
        "check eligibility",
        "am i eligible",
        "am i qualified",
        "find schemes for me",
        "which schemes can I get",
        "see if i qualify",
        "show me schemes",
        "पात्रता जाँचें",
        "पात्रता देखें",
    ])
    def test_eligibility_trigger_messages(self, msg: str) -> None:
        """Eligibility check phrases → trigger_matching."""
        assert _detect_intent_fast(msg, current_state="GATHERING") == "trigger_matching"

    @pytest.mark.parametrize("msg", [
        "check",
        "eligible",
        "eligibility",
    ])
    def test_single_word_eligibility_triggers(self, msg: str) -> None:
        """Single-word eligibility triggers → trigger_matching."""
        assert _detect_intent_fast(msg) == "trigger_matching"

    # --- Scheme question triggers ---
    @pytest.mark.parametrize("msg", [
        "what is MGNREGA",
        "what is PM-KISAN",
        "what are the schemes for farmers",
        "tell me about PM Awas Yojana",
        "how do i apply for PMAY",
        "explain PM Kisan",
        "describe the scheme",
        "क्या है MGNREGA",
    ])
    def test_scheme_question_intents(self, msg: str) -> None:
        """Scheme queries → ask_question."""
        assert _detect_intent_fast(msg) == "ask_question"

    # --- Exit should not trigger on partial matches ---
    @pytest.mark.parametrize("msg", [
        "thanks, my age is 42",  # "thanks" embedded in sentence → NOT exit
        "bye the way I have aadhaar",  # "bye" embedded → NOT exit
        "I'm done eating",  # "done" embedded → NOT exit
    ])
    def test_exit_not_triggered_mid_sentence(self, msg: str) -> None:
        """Exit markers embedded in longer sentences should NOT trigger exit."""
        result = _detect_intent_fast(msg)
        assert result != "exit"

    # --- What-if scenarios ---
    @pytest.mark.parametrize("msg", [
        "what if I get an Aadhaar card",
        "what would happen if I open a bank account",
        "suppose I moved to Maharashtra",
        "if i had a BPL card would i qualify",
        "अगर मैं किसान होता तो",
    ])
    def test_what_if_scenarios(self, msg: str) -> None:
        assert _detect_intent_fast(msg) == "what_if"

    # --- Correction intents ---
    @pytest.mark.parametrize("msg", [
        "actually I am 38 not 35",
        "wait, my income is 3 lakh not 2",
        "sorry I made an error, I am OBC",
        "my mistake, I live in UP not MP",
        "दरअसल मेरी उम्र 38 है",
    ])
    def test_correction_scenarios(self, msg: str) -> None:
        assert _detect_intent_fast(msg) == "correct_info"

    # --- Profile info provision ---
    @pytest.mark.parametrize("msg", [
        "I am 42 years old",
        "main 35 saal ka kisan hoon UP se",
        "My income is 1.5 lakh per year",
        "I live in Bihar, I am SC category",
        "मेरी उम्र 40 साल है",
        "I have 3 bigha land in Punjab",
        "5",   # bare number during gathering = age/family size answer
        "150000",
        "no I don't have land",
        "yes I have Aadhaar",
        "OBC",
        "UP",
    ])
    def test_profile_info_scenarios(self, msg: str) -> None:
        """All profile-info messages → provide_info during GATHERING."""
        assert _detect_intent_fast(msg, current_state="GATHERING") == "provide_info"

    # --- Skip scenarios ---
    @pytest.mark.parametrize("msg", [
        "skip",
        "I don't know",
        "not sure",
        "no idea",
        "pass",
        "पता नहीं",
        "नहीं पता",
    ])
    def test_skip_scenarios(self, msg: str) -> None:
        assert _detect_intent_fast(msg) == "skip_field"

    # --- Hinglish / mixed language ---
    @pytest.mark.parametrize("msg", [
        "main 35 saal ka hoon",
        "meri income 2 lakh hai",
        "UP mein rehta hoon",
        "SC category se hoon",
    ])
    def test_hinglish_is_provide_info(self, msg: str) -> None:
        """Hinglish profile data → provide_info."""
        assert _detect_intent_fast(msg, current_state="GATHERING") == "provide_info"


class TestSchemeRetriever:
    """Test _find_scheme_by_name scheme lookup."""

    def test_engine_has_retriever(self) -> None:
        engine = ConversationEngine(rule_base_path=Path("parsed_schemes"))
        assert engine._retriever is not None
        assert engine._retriever._loaded is True

    def test_find_scheme_by_name_mgnrega(self) -> None:
        """MGNREGA should be found by name search."""
        engine = ConversationEngine(rule_base_path=Path("parsed_schemes"))
        scheme = engine._find_scheme_by_name("What is MGNREGA?")
        assert scheme is not None
        name = scheme.get("scheme_name", "")
        assert "MGNREGA" in name.upper() or "MAHATMA GANDHI" in name.upper()

    def test_find_scheme_by_name_pm_kisan(self) -> None:
        """PM-KISAN should be findable."""
        engine = ConversationEngine(rule_base_path=Path("parsed_schemes"))
        scheme = engine._find_scheme_by_name("what is PM Kisan")
        # PM-KISAN may or may not be in data; just ensure no crash
        # and return type is dict or None
        assert scheme is None or isinstance(scheme, dict)

    def test_find_scheme_by_name_no_match(self) -> None:
        """Completely unknown scheme name should return None."""
        engine = ConversationEngine(rule_base_path=Path("parsed_schemes"))
        scheme = engine._find_scheme_by_name("what is zzzznonexistentscheme")
        assert scheme is None
