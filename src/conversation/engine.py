"""Conversation engine for CBC Part 5 — the state machine core.

Orchestrates the full conversation lifecycle: greeting → profile gathering
→ clarification → matching → result presentation → exploration.
Framework-agnostic: callable from CLI, web, or tests.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.conversation.config import (
    DEFAULT_LANGUAGE,
    MAX_FOLLOWUP_QUESTIONS_PER_TURN,
    MAX_MESSAGE_LENGTH,
    MAX_TURNS_BEFORE_MATCHING,
    MIN_VIABLE_FIELDS,
)
from src.conversation.exceptions import (
    ConversationError,
    ContradictionError,
    ExtractionError,
    LLMUnavailableError,
    SessionError,
)
from src.conversation.extraction import (
    ExtractionResult,
    extract_fields,
    format_extraction_summary,
)
from src.conversation.ner_guard import NERGuard
from src.conversation.contradiction import (
    detect_contradictions,
    detect_intra_message_contradictions,
    detect_type3_implicit_contradictions,
    extract_inferences,
    build_resolution_dialog,
    is_intentional_correction,
)
from src.conversation.prompts import INTENT_DETECTION_PROMPT
from src.conversation.rag import SchemeRetriever
from src.conversation.session import (
    ConversationSession,
    ConversationTurn,
    ProfileChange,
)
from src.conversation.templates import (
    CLARIFYING,
    ENDED,
    ERROR_MATCHING,
    EXPLORING_PROMPT,
    FIELD_QUESTION_MAP,
    GATHERING_ACK,
    GATHERING_FIRST_ACK,
    GREETING,
    LLM_FALLBACK,
    MATCHING_STARTED,
    PRESENTING_HEADER,
    SESSION_EXPIRED,
    SKIP_ACK,
    UNCLEAR_INPUT,
    get_field_label,
    get_template,
)
from src.conversation.translation import (
    LanguageDetection,
    detect_language,
    translate_to_english,
    translate_response,
    translate_to_hindi,
    translate_to_hinglish,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Serialisation helpers (module-level, no side-effects)
# ---------------------------------------------------------------------------

def _safe_serialise(value: Any) -> Any:
    """Convert a rule/user value to a JSON-safe scalar for the audit panel."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_safe_serialise(v) for v in value]
    return str(value)




def _conf_explanation(conf: dict) -> str:
    """Return a plain-English sentence explaining what drove this confidence score."""
    bottleneck = conf.get("bottleneck", "")
    composite = float(conf.get("composite", 0) or 0)
    rule_match = float(conf.get("rule_match_score", 0) or 0)
    data_conf = float(conf.get("data_confidence", 0) or 0)
    completeness = float(conf.get("profile_completeness", 0) or 0)

    parts: list[str] = []
    if rule_match < 0.5:
        parts.append(f"only {int(rule_match*100)}% of eligibility rules could be verified")
    if data_conf < 0.6:
        parts.append("some of your answers couldn't be independently verified (this is normal — scores improve as you share more details)")
    if completeness < 0.7:
        parts.append(f"profile is {int(completeness*100)}% complete for this scheme's required fields")
    if not parts:
        if composite >= 0.85:
            return "High confidence — all criteria clearly matched."
        elif composite >= 0.65:
            return "Moderate confidence — most criteria matched but some are uncertain."
        else:
            return "Low confidence — several criteria could not be fully verified."
    return "Score is lower because " + "; ".join(parts) + "."


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


@dataclass
class ConversationResponse:
    """System response for one conversation turn."""

    text: str                       # Response in user's language
    text_en: str                    # Always English (audit)
    state_before: str = ""
    state_after: str = ""
    extractions: list[dict] = field(default_factory=list)
    profile_changes: list[dict] = field(default_factory=list)
    contradictions: list[dict] = field(default_factory=list)
    what_if_result: Optional[dict] = None
    matching_triggered: bool = False
    session_token: str = ""
    turn_audit: dict = field(default_factory=dict)  # Full explainability payload


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

# Fast keyword-based markers before falling back to LLM
_CORRECTION_MARKERS = {
    "actually", "wait", "no i meant", "sorry", "correction",
    "my mistake", "let me fix", "i was wrong",
    # Hindi — "नहीं" removed: too broad, clashes with "पता नहीं" (skip)
    "दरअसल", "रुकिए", "माफ़ कीजिए", "मेरा मतलब",
    "सही बात", "गलती हो गई",
}

_WHAT_IF_MARKERS = {
    "what if", "what would happen", "if i", "suppose i",
    "what happens if", "what about if",
    # Hindi
    "अगर", "क्या हो अगर", "मान लो", "अगर मैं",
}

_EXIT_MARKERS = {
    "bye", "done", "quit", "exit", "thanks", "thank you",
    "that's all", "no more",
    # Hindi
    "बस", "धन्यवाद", "अलविदा", "ठीक है बस",
}

_SKIP_MARKERS = {
    "skip", "don't know", "not sure", "i don't know",
    "no idea", "pass",
    # Hindi
    "पता नहीं", "छोड़ दें", "नहीं पता", "छोड़ो",
}

_CONFIRM_MARKERS = {
    "yes", "correct", "right", "ok", "okay", "sure",
    "that's right", "yep", "yeah",
    # Hindi
    "हाँ", "सही", "ठीक", "जी हाँ", "बिल्कुल",
}

# Informational queries about schemes / application process
_QUESTION_MARKERS = {
    "what is", "what are", "what's", "whats", "what about the",
    "how does", "how do i apply", "how can i apply", "how to apply",
    "how to get", "how do i get",
    "tell me about", "explain", "describe",
    "information about", "info about", "details about",
    # Hindi
    "क्या है", "क्या हैं", "कैसे", "बताइए", "बताएं", "समझाइए",
}

# Greeting markers — exact-match only to avoid false positives
_GREETING_MARKERS = {
    "hi", "hello", "hey", "sup", "yo", "hola", "namaste", "namaskar",
    "नमस्ते", "नमस्कार", "हेलो", "हाय", "सुप्रभात", "good morning",
    "good afternoon", "good evening",
}

# Explicit requests to run eligibility matching
_MATCHING_TRIGGER_MARKERS = {
    "check my eligibility", "check eligibility",
    "check schemes", "am i eligible", "am i qualified",
    "find schemes", "find me schemes", "which schemes",
    "what schemes", "see if i qualify", "see results",
    "run eligibility", "see if im eligible",
    "show me schemes", "tell me my eligibility",
    "recheck", "check again", "re-check", "re run", "run again",
    # Hindi
    "पात्रता जाँचें", "पात्रता देखें", "योजनाएँ देखें",
    "मेरी पात्रता जाँचें", "पात्रता चेक",
}
# Single-word exact matches that trigger matching
_MATCHING_TRIGGER_EXACT = {"check", "eligible", "eligibility"}


def _detect_intent_fast(
    message: str,
    current_state: str = "GATHERING",
    has_results: bool = False,
) -> str:
    """Keyword-based fast intent detection. Always returns an intent (never None).

    Args:
        message: User message.
        current_state: Current conversation state (GATHERING, PRESENTING, etc.)
        has_results: Whether matching results exist in the session.
    """
    lower = message.lower().strip()
    is_gathering = current_state in ("GATHERING", "CLARIFYING", "GREETING")

    # Empty or very short trivial responses
    if lower == "":
        return "confirm"
    if lower in ("y", "yes", "ok", "हाँ", "सही"):
        if is_gathering:
            return "provide_info"
        return "confirm"

    # Greeting — check before anything else; strip trailing punctuation
    stripped = lower.rstrip("!.?,")
    if stripped in _GREETING_MARKERS:
        return "greeting"

    # Check SKIP markers first — they contain multi-word phrases
    for marker in _SKIP_MARKERS:
        if marker in lower:
            return "skip_field"

    # EXIT markers — single-word: exact match only to avoid false triggers
    # (e.g. "thanks, my age is 42" should NOT exit)
    for marker in _EXIT_MARKERS:
        if " " not in marker:
            # Single-word: require exact match (allow trailing punctuation)
            if lower == marker or lower.rstrip("!.?") == marker:
                return "exit"
        else:
            # Multi-word phrase: allow startswith
            if lower.startswith(marker):
                return "exit"

    # Corrections — explicit markers only
    for marker in _CORRECTION_MARKERS:
        if marker in lower:
            return "correct_info"

    # Eligibility check triggers — check BEFORE what_if since "see if i qualify"
    # contains "if i" which is also a what_if marker
    for marker in _MATCHING_TRIGGER_MARKERS:
        if marker in lower:
            return "trigger_matching"
    if lower in _MATCHING_TRIGGER_EXACT:
        return "trigger_matching"

    # What-if hypotheticals
    for marker in _WHAT_IF_MARKERS:
        if marker in lower:
            return "what_if"

    # Informational queries about schemes
    for marker in _QUESTION_MARKERS:
        if lower.startswith(marker + " ") or lower == marker:
            return "ask_question"

    # Bare digit — detail request only when results are showing
    if lower.strip().isdigit():
        if has_results and not is_gathering:
            return "request_detail"
        return "provide_info"

    # Short yes/no answers during gathering are answers to questions
    if is_gathering and lower in (
        "no", "nahi", "nope", "na", "नहीं", "ना",
        "yeah", "yep", "sure", "okay", "हां", "जी",
    ):
        return "provide_info"

    # Default: treat as profile information provision
    return "provide_info"


async def _detect_intent_llm(message: str) -> tuple[str, str]:
    """Use LLM to classify intent. Returns (intent, confidence)."""
    try:
        from src.conversation.extraction import _call_gemini
        result = await _call_gemini(
            system_prompt=INTENT_DETECTION_PROMPT,
            user_message=message,
        )
        return (
            result.get("intent", "provide_info"),
            result.get("confidence", "MEDIUM"),
        )
    except (LLMUnavailableError, ExtractionError):
        # Default to provide_info when LLM is unavailable
        return ("provide_info", "LOW")


# ---------------------------------------------------------------------------
# Conversation engine
# ---------------------------------------------------------------------------


class ConversationEngine:
    """Core conversation engine.  Framework-agnostic.

    Usage::

        engine = ConversationEngine(rule_base_path=Path("parsed_schemes"))
        resp = await engine.start_session()
        print(resp.text)
        resp = await engine.process_message(resp.session_token, user_input)
    """

    def __init__(
        self,
        rule_base_path: Path,
        llm_provider: str = "gemini",
    ) -> None:
        self.rule_base_path = rule_base_path
        self.llm_provider = llm_provider
        self._llm_available = True  # flipped to False on LLMUnavailableError
        self._ner_guard = NERGuard()
        self._retriever = SchemeRetriever(rule_base_path)
        # Stateless sessions — all state travels in the client's session token (cookie)
        # No server-side storage needed. This enables serverless deployments (Vercel, Lambda)
        # and horizontal scaling without session affinity.
        # Rule base cache — loaded once per process, reused across all sessions.
        self._rule_base_cache: dict | None = None

    # ------------------------------------------------------------------
    # Public API — Stateless Sessions
    # ------------------------------------------------------------------

    async def start_session(
        self,
        language: str = DEFAULT_LANGUAGE,
    ) -> ConversationResponse:
        """Start a new conversation session.

        Returns the greeting message and a stateless session token (cookie-safe).
        All session state is encoded in the token; no server-side storage.
        """
        session = ConversationSession.new()
        session.detected_language = language

        greeting_text = get_template(GREETING, language)

        # Record greeting turn
        turn = ConversationTurn(
            turn_number=0,
            timestamp=session.created_at,
            user_message="",
            detected_language=language,
            detected_intent="start",
            system_response=greeting_text,
            system_response_en=get_template(GREETING, "en"),
            state_before="GREETING",
            state_after="GATHERING",
        )
        session.add_turn(turn)
        session.transition("GATHERING")

        # Encode session state into a portable, stateless token
        # No server-side storage — all state travels with the client
        session_token = session.to_token()

        return ConversationResponse(
            text=greeting_text,
            text_en=get_template(GREETING, "en"),
            state_before="GREETING",
            state_after="GATHERING",
            session_token=session_token,
        )

    async def process_message(
        self,
        session_token: str,
        user_message: str,
    ) -> ConversationResponse:
        """Process a user message within an existing session.

        This is the main turn-processing pipeline:
        1. Decode session from token (all state is client-side)
        2. Detect language
        3. Detect intent
        4. Route to handler
        5. Update state
        6. Generate response
        7. Encode session state back into token

        Raises:
            ConversationError: On unrecoverable processing error.
        """
        # --- 1. Decode session from stateless token ---
        try:
            session = ConversationSession.from_token(session_token)
        except Exception as exc:
            # Token is invalid or expired; start fresh
            logger.debug("Failed to decode session token: %s", exc)
            return await self.start_session()

        if session.current_state == "ENDED":
            lang = session.detected_language
            return await self.start_session(lang)

        # --- 2. Validate input ---
        user_message = user_message.strip()
        if len(user_message) > MAX_MESSAGE_LENGTH:
            user_message = user_message[:MAX_MESSAGE_LENGTH]

        # --- 3. Detect language ---
        # Only override language for substantive messages (short replies like
        # "ok" or "yes" shouldn't flip a Hindi session to English).
        lang_det = await detect_language(user_message)
        if lang_det.language != "en" or session.detected_language == "en":
            session.detected_language = lang_det.language
        lang = session.detected_language

        # --- 4. Detect intent ---
        # Fast keyword-based detection always returns an intent.
        # _detect_intent_llm is no longer called, saving Gemini quota.
        intent = _detect_intent_fast(
            user_message,
            current_state=session.current_state,
            has_results=session.latest_result is not None,
        )

        # --- 5. Route to handler ---
        state_before = session.current_state

        try:
            response_text_en, profile_changes, extraction_data = (
                await self._route_intent(session, user_message, intent, lang)
            )
        except LLMUnavailableError:
            self._llm_available = False
            response_text_en = get_template(LLM_FALLBACK, "en")
            response_text_en += self._fallback_form_question(session)
            profile_changes = []
            extraction_data = {}

        # --- 6. Translate response if needed ---
        if lang in ("hi", "hinglish"):
            try:
                response_text = await translate_response(response_text_en, lang)
            except Exception:
                response_text = response_text_en
        else:
            response_text = response_text_en

        # --- 7. Record turn ---
        turn = ConversationTurn(
            turn_number=session.turn_count,
            timestamp=session.updated_at,
            user_message=user_message,
            detected_language=lang,
            detected_intent=intent,
            extractions=extraction_data.get("extractions", []),
            profile_changes=[asdict(pc) for pc in profile_changes],
            system_response=response_text,
            system_response_en=response_text_en,
            state_before=state_before,
            state_after=session.current_state,
        )
        session.add_turn(turn)

        # --- 8. Encode session state back into stateless token ---
        session_token = session.to_token()

        return ConversationResponse(
            text=response_text,
            text_en=response_text_en,
            state_before=state_before,
            state_after=session.current_state,
            extractions=extraction_data.get("extractions", []),
            profile_changes=[asdict(pc) for pc in profile_changes],
            matching_triggered=extraction_data.get("matching_triggered", False),
            session_token=session_token,
            turn_audit=extraction_data.get("turn_audit", {}),
        )

    async def resume_session(
        self,
        session_token: str,
    ) -> ConversationResponse:
        """Resume a session from an existing token.

        Returns a welcome-back message with current state summary.
        """
        try:
            session = ConversationSession.from_token(session_token)
        except Exception:
            # Invalid or expired token
            return await self.start_session()

        lang = session.detected_language
        populated = len(session.get_populated_field_paths())
        state = session.current_state

        summary = (
            f"Welcome back! You have {populated} fields populated and "
            f"are in the {state} stage. Continue where you left off."
        )

        if lang in ("hi", "hinglish"):
            try:
                summary = await translate_response(summary, lang)
            except Exception:
                pass

        # Encode updated session back into token
        updated_token = session.to_token()

        return ConversationResponse(
            text=summary,
            text_en=summary,
            state_before=state,
            state_after=state,
            session_token=updated_token,
        )

    # ------------------------------------------------------------------
    # Intent routing
    # ------------------------------------------------------------------

    async def _route_intent(
        self,
        session: ConversationSession,
        message: str,
        intent: str,
        language: str,
    ) -> tuple[str, list[ProfileChange], dict[str, Any]]:
        """Route a classified intent to the appropriate handler.

        Returns:
            (response_text_en, profile_changes, extraction_data_dict)
        """
        if intent == "exit":
            return self._handle_exit(session)

        if intent == "greeting":
            return self._handle_greeting(session, language)

        # When waiting for contradiction resolution, route directly to the
        # resolver — don't re-run extraction which would re-trigger the same conflict
        if session.current_state == "CLARIFYING" and session.pending_contradiction:
            return await self._handle_contradiction_resolution(
                session, message, language
            )

        if intent == "skip_field":
            return await self._handle_skip(session)

        if intent == "confirm":
            return await self._handle_confirm(session)

        if intent == "what_if":
            return await self._handle_what_if(session, message, language)

        if intent == "correct_info":
            return await self._handle_correction(session, message, language)

        if intent == "request_detail":
            return self._handle_detail_request(session, message)

        if intent == "ask_question":
            return await self._handle_ask_question(session, message, language)

        if intent == "trigger_matching":
            return await self._handle_trigger_matching(session, message, language)

        # Post-results: if session already has results, allow normal chat without
        # re-triggering the full matching pipeline every turn.
        if session.current_state in ("PRESENTING", "EXPLORING") and session.latest_result is not None:
            return await self._handle_post_results_chat(session, message, language)

        # Default: provide_info
        return await self._handle_provide_info(session, message, language)

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    async def _handle_trigger_matching(
        self,
        session: ConversationSession,
        message: str,
        language: str,
    ) -> tuple[str, list[ProfileChange], dict[str, Any]]:
        """Handle explicit 'check eligibility' requests.

        Always extracts fields from the current message first so that a
        one-shot message like "I am 35, OBC, UP, income 120000. Check my
        eligibility." works without a prior extraction turn.
        """
        # --- Extract fields from the current message before checking populated ---
        extraction = await extract_fields(
            message=message,
            existing_profile=session.profile_data,
            conversation_history=list(session.turns[-3:]),
            language=language,
        )
        changes: list[ProfileChange] = []
        for ef in extraction.extractions:
            change = session.update_profile_field(
                field_path=ef.field_path,
                value=ef.value,
                turn_number=session.turn_count,
                source_text=ef.source_span,
                confidence=ef.confidence,
            )
            changes.append(change)

        ext_dicts = [
            {"field_path": e.field_path, "value": e.value, "source_span": e.source_span}
            for e in extraction.extractions
        ]

        populated = session.get_populated_field_paths()
        if populated:
            # We have some profile data — run matching now
            return await self._run_matching(
                session, changes, {"extractions": ext_dicts, "matching_triggered": False}
            )

        # No profile data at all — ask for the essentials
        response_en = (
            "I'd love to check your eligibility! To get started, could you share:\n\n"
            "  1. Your age\n"
            "  2. Which state you live in\n"
            "  3. Your annual household income (approximate is fine)\n"
            "  4. Your caste/community category (SC/ST/OBC/General/EWS)\n\n"
            "Even just two or three of these will let me find relevant schemes for you."
        )
        # Mark these fields as asked
        for fp in ["applicant.age", "location.state",
                   "household.income_annual", "applicant.caste_category"]:
            session.mark_field_asked(fp)
        session.last_bot_questions = [
            {"field_path": "applicant.age", "question": "Your age", "index": 1},
            {"field_path": "location.state", "question": "Which state you live in", "index": 2},
            {"field_path": "household.income_annual", "question": "Annual household income", "index": 3},
            {"field_path": "applicant.caste_category", "question": "Caste/community category", "index": 4},
        ]
        session.transition("GATHERING")
        return response_en, [], {"extractions": ext_dicts, "matching_triggered": False}

    def _handle_greeting(
        self,
        session: ConversationSession,
        language: str,
    ) -> tuple[str, list[ProfileChange], dict[str, Any]]:
        """Respond warmly to greetings without treating them as data."""
        import random
        responses_en = [
            "Hey! Great to have you here. I can help you discover government schemes you might be eligible for — just tell me a bit about yourself: your age, state, what you do, and your family situation.",
            "Hello! Happy to help you find benefits and schemes from the government. Share a bit about your background — age, location, income, occupation — and I'll do the search for you.",
            "Hi there! I'm here to help you find government welfare schemes that match your profile. Go ahead and tell me about yourself — anything you share helps!",
        ]
        responses_hi = [
            "नमस्ते! आपका स्वागत है। मैं आपको सरकारी योजनाओं की जानकारी दे सकता/सकती हूँ। बस अपनी उम्र, राज्य, काम और परिवार के बारे में बताएं।",
            "हेलो! यहाँ आने का शुक्रिया। अपने बारे में थोड़ा बताइए — उम्र, आमदनी, राज्य, और रोज़गार — मैं सही योजनाएँ ढूंढूँगा/ढूंढूँगी।",
        ]
        response = random.choice(responses_hi if language == "hi" else responses_en)
        return response, [], {"matching_triggered": False}

    async def _handle_contradiction_resolution(
        self,
        session: ConversationSession,
        message: str,
        language: str,
    ) -> tuple[str, list[ProfileChange], dict[str, Any]]:
        """Parse user's numbered choice for a pending contradiction and apply it."""
        pending = session.pending_contradiction
        existing = pending["existing_value"]
        new_val = pending["new_value"]
        field_path = pending["field_path"]
        field_label = pending["field_label"]

        lower = message.lower().strip()

        # Determine which option the user chose
        chosen_value: Optional[str] = None
        if lower.startswith("1") or existing.lower() in lower:
            chosen_value = existing
        elif lower.startswith("2") or new_val.lower() in lower:
            chosen_value = new_val
        elif (
            lower.startswith("3")
            or "neither" in lower
            or "कोई नहीं" in lower
            or "दोनों नहीं" in lower
        ):
            # User wants to give a fresh value
            session.pending_contradiction = None
            session.transition("GATHERING")
            label = get_field_label(field_path, language)
            if language == "hi":
                prompt = f"ठीक है! तो आपका सही {label} क्या है?"
            else:
                prompt = f"No problem — what is your correct {label}?"
            return prompt, [], {"matching_triggered": False}
        else:
            # Choice is ambiguous — re-display the options
            if language == "hi":
                clarify = (
                    f"कृपया एक विकल्प चुनें:\n"
                    f"  1. {existing} (पहले वाला)\n"
                    f"  2. {new_val} (अभी वाला)\n"
                    f"  3. दोनों नहीं — मैं सही बताता/बताती हूँ"
                )
            else:
                clarify = (
                    f"Please choose one:\n"
                    f"  1. {existing} (your earlier answer)\n"
                    f"  2. {new_val} (what you just said)\n"
                    f"  3. Neither — I'll give the correct value"
                )
            return clarify, [], {"matching_triggered": False}

        # Apply the chosen value
        change = session.update_profile_field(
            field_path=field_path,
            value=chosen_value,
            turn_number=session.turn_count,
            source_text=f"[user resolved contradiction: chose '{chosen_value}']",
            confidence="HIGH",
        )

        # Clear pending contradiction and return to gathering
        session.pending_contradiction = None
        session.transition("GATHERING")

        if language == "hi":
            ack = f"ठीक है, {field_label} के लिए **{chosen_value}** रखता/रखती हूँ।"
        else:
            ack = f"Got it — I'll use **{chosen_value}** as your {field_label}."

        followup = self._build_followup_response(session, None)
        return f"{ack}\n\n{followup}", [change], {"matching_triggered": False}

    async def _handle_provide_info(
        self,
        session: ConversationSession,
        message: str,
        language: str,
    ) -> tuple[str, list[ProfileChange], dict[str, Any]]:
        """Handle information provision — full pipeline with NER + contradiction + RAG."""
        # --- Step 1: LLM extraction ---
        # Build conversation history with last_bot_questions context
        history = list(session.turns[-3:])
        if history and session.last_bot_questions:
            # Inject last_bot_questions into the most recent turn for extraction context
            last = dict(history[-1])
            last["last_bot_questions"] = session.last_bot_questions
            history[-1] = last

        extraction = await extract_fields(
            message=message,
            existing_profile=session.profile_data,
            conversation_history=history,
            language=language,
        )

        # --- Step 2: NER hallucination guard (verification only) ---
        # NER catches impossible numeric values (age 999, negative income).
        # Vocab mismatches are warned but NOT rejected — they still apply.
        # The audit trail records NER status for every field.
        ner_report = self._ner_guard.validate(extraction)
        safe_extractions = extraction.extractions  # keep ALL extractions

        # --- Step 3: Extract inferences from message (for Type 3 tracking) ---
        raw_inferences = extract_inferences(message)
        # Record new inferences that don't already have an explicit value
        for fp, val, trigger in raw_inferences:
            if fp not in session.profile_data and fp not in session.inferred_fields:
                session.inferred_fields[fp] = {
                    "value": val,
                    "inferred_from": trigger,
                    "source_turn": session.turn_count,
                }

        # --- Step 4: Contradiction detection pipeline ---
        ext_dicts = [{"field_path": e.field_path, "value": e.value,
                      "source_span": e.source_span} for e in safe_extractions]

        # Type 2: intra-message
        type2_flags = detect_intra_message_contradictions(ext_dicts)

        # Type 3: implicit (explicit statement vs. inferred field)
        type3_flags, _ = detect_type3_implicit_contradictions(
            ext_dicts, session.inferred_fields, session.turn_count, message
        )

        # Types 1, 4, 5: vs. existing profile
        type145_flags = detect_contradictions(
            ext_dicts, session.profile_data, session.field_provenance,
            session.turn_count,
        )

        all_flags = type2_flags + type3_flags + type145_flags

        # Log all contradictions to session
        for flag in all_flags:
            from dataclasses import asdict as _asdict
            session.contradiction_log.append(_asdict(flag))

        # --- Step 5: Handle blocking contradictions ---
        blocking = [f for f in all_flags if f.severity == "blocking"]

        # If the user explicitly indicates they are updating/changing their info
        # (temporal markers like "changed", "now I'm", "these days", etc.),
        # downgrade direct-value-conflict blocks to soft update confirmations.
        if blocking and is_intentional_correction(message):
            for flag in blocking[:]:
                if flag.contradiction_type == 1:  # direct value conflict
                    label = get_field_label(flag.field_path, language)
                    flag.severity = "info"
                    flag.resolution_status = "auto_resolved"
                    flag.message_en = (
                        f"Got it — updating your {label} from "
                        f"'{flag.existing_value}' to '{flag.new_value}'."
                    )
                    flag.message_hi = (
                        f"समझ गया — {label} को "
                        f"'{flag.existing_value}' से '{flag.new_value}' में अपडेट कर रहे हैं।"
                    )
            blocking = [f for f in all_flags if f.severity == "blocking"]

        if blocking:
            session.transition("CLARIFYING")
            # Store the pending contradiction so the next turn routes to resolution
            b = blocking[0]
            session.pending_contradiction = {
                "field_path": b.field_path,
                "existing_value": str(b.existing_value),
                "new_value": str(b.new_value),
                "field_label": get_field_label(b.field_path, language),
            }
            dialog = build_resolution_dialog(blocking[0], language)
            turn_audit = self._build_turn_audit(
                session, extraction, ner_report, all_flags, message
            )
            return dialog, [], {
                "extractions": ext_dicts,
                "matching_triggered": False,
                "turn_audit": turn_audit,
            }

        # Auto-resolved Type 3 flags — notify user
        auto_note = ""
        for flag in type3_flags:
            if flag.resolution_status == "auto_resolved":
                # Apply explicit value, remove from inferred_fields
                session.inferred_fields.pop(flag.field_path, None)
                auto_note += flag.message_en + "\n"

        # --- Step 6: Apply safe extractions ---
        changes: list[ProfileChange] = []
        for ef in safe_extractions:
            change = session.update_profile_field(
                field_path=ef.field_path,
                value=ef.value,
                turn_number=session.turn_count,
                source_text=ef.source_span,
                confidence=ef.confidence,
            )
            changes.append(change)

        # Also apply inferred fields without explicit values
        for fp, inferred in session.inferred_fields.items():
            if fp not in session.profile_data:
                session.update_profile_field(
                    field_path=fp,
                    value=inferred["value"],
                    turn_number=inferred["source_turn"],
                    source_text=f"[inferred from '{inferred['inferred_from']}']",
                    confidence="LOW",
                )

        # --- Step 7: Build turn audit ---
        turn_audit = self._build_turn_audit(
            session, extraction, ner_report, all_flags, message
        )

        extraction_data: dict[str, Any] = {
            "extractions": ext_dicts,
            "matching_triggered": False,
            "turn_audit": turn_audit,
        }

        # --- Step 8: Build response ---
        prefix = auto_note

        # First extraction → show detailed explainability summary
        if session.turn_count <= 1 and extraction.reasoning_chain:
            summary = format_extraction_summary(extraction.reasoning_chain, "en")
            response = prefix + get_template(
                GATHERING_FIRST_ACK, "en",
                extraction_reasoning=summary,
            )
            session.transition("GATHERING")
            return response, changes, extraction_data

        # Check if ready to match
        if session.is_minimum_viable():
            return await self._run_matching(session, changes, extraction_data)

        # Auto-trigger matching if too many turns have passed and we have *some* data
        if (session.turn_count >= MAX_TURNS_BEFORE_MATCHING
                and len(session.get_populated_field_paths()) >= 2):
            return await self._run_matching(session, changes, extraction_data)

        # Need more fields → RAG-enhanced follow-up (always show what was extracted)
        response = prefix + self._build_followup_response(session, extraction)
        if session.current_state != "CLARIFYING":
            session.transition("GATHERING")

        return response, changes, extraction_data

    async def _handle_correction(
        self,
        session: ConversationSession,
        message: str,
        language: str,
    ) -> tuple[str, list[ProfileChange], dict[str, Any]]:
        """Handle a correction to previously provided data."""
        session.transition("CORRECTING")

        # Re-extract — the new message should contain the corrected value
        extraction = await extract_fields(
            message=message,
            existing_profile={},  # empty context to force re-extraction
            conversation_history=session.turns[-3:],
            language=language,
        )

        changes: list[ProfileChange] = []
        corrections_text: list[str] = []

        for ef in extraction.extractions:
            old_val = session.profile_data.get(ef.field_path)
            change = session.update_profile_field(
                field_path=ef.field_path,
                value=ef.value,
                turn_number=session.turn_count,
                source_text=ef.source_span,
                confidence=ef.confidence,
            )
            change.change_type = "correct"
            changes.append(change)

            label = get_field_label(ef.field_path, "en")
            corrections_text.append(f"  {label}: {old_val} → {ef.value}")

        # Update provenance
        for ef in extraction.extractions:
            prov = session.field_provenance.get(ef.field_path, {})
            prov["was_corrected"] = True
            prov["correction_turn"] = session.turn_count
            session.field_provenance[ef.field_path] = prov

        if corrections_text:
            correction_summary = "\n".join(corrections_text)
            response = (
                f"Got it! I've updated your profile:\n{correction_summary}\n\n"
                "Should I re-check your eligibility with these changes?"
            )
        else:
            response = (
                "I couldn't identify what to correct. Could you tell me "
                "which field to change and the new value?"
            )

        session.transition(session.previous_state)

        return response, changes, {
            "extractions": [asdict(e) for e in extraction.extractions],
            "matching_triggered": False,
        }

    async def _handle_what_if(
        self,
        session: ConversationSession,
        message: str,
        language: str,
    ) -> tuple[str, list[ProfileChange], dict[str, Any]]:
        """Handle a 'What If' scenario query."""
        session.transition("EXPLORING")

        # For now, extract the hypothetical change and re-run matching
        try:
            from src.conversation.what_if import (
                detect_what_if_intent,
                process_what_if,
            )

            modification = await detect_what_if_intent(
                message=message,
                profile=session.profile_data,
            )

            if modification and session.latest_result:
                comparison = await process_what_if(
                    modification=modification,
                    current_profile=session.profile_data,
                    current_result=session.latest_result,
                    rule_base_path=self.rule_base_path,
                )
                from src.conversation.what_if import format_what_if_comparison
                response = format_what_if_comparison(comparison, "en")
                return response, [], {"matching_triggered": True}

        except ImportError:
            logger.warning("what_if module not yet available")
        except Exception as exc:
            logger.warning("What If processing failed: %s", exc)

        response = (
            "I'd love to explore that scenario, but I need to check your "
            "eligibility first. Let me have enough information to run an "
            "initial check, then we can explore 'What If' questions."
        )
        return response, [], {"matching_triggered": False}

    def _handle_exit(
        self,
        session: ConversationSession,
    ) -> tuple[str, list[ProfileChange], dict[str, Any]]:
        """Handle session end."""
        session.transition("ENDED")
        response = get_template(ENDED, "en")
        return response, [], {"matching_triggered": False}

    async def _handle_skip(
        self,
        session: ConversationSession,
    ) -> tuple[str, list[ProfileChange], dict[str, Any]]:
        """Handle field skip."""
        # Mark the most recently asked field as skipped
        unanswered = [
            f for f in session.asked_fields
            if f not in session.get_populated_field_paths()
            and f not in session.skipped_fields
        ]
        if unanswered:
            skipped = unanswered[-1]
            session.mark_field_skipped(skipped)

        # If we have enough fields, run matching
        if session.is_minimum_viable():
            return await self._run_matching(
                session, [], {"extractions": [], "matching_triggered": False}
            )

        response = get_template(SKIP_ACK, "en")
        return response, [], {"matching_triggered": False}

    async def _handle_confirm(
        self,
        session: ConversationSession,
    ) -> tuple[str, list[ProfileChange], dict[str, Any]]:
        """Handle confirmation of extracted data."""
        if session.is_minimum_viable():
            return await self._run_matching(
                session, [], {"extractions": [], "matching_triggered": False}
            )

        # Not enough data — ask more questions
        response = self._build_followup_response(session, None)
        return response, [], {"matching_triggered": False}

    def _handle_detail_request(
        self,
        session: ConversationSession,
        message: str,
    ) -> tuple[str, list[ProfileChange], dict[str, Any]]:
        """Handle request for scheme details — render full rule trace & gap analysis."""
        from src.conversation.presentation import render_scheme_detail

        result = session.latest_result
        if not result:
            return (
                "No results yet. Please share your profile and type 'check' to see your eligibility.",
                [],
                {"matching_triggered": False},
            )

        schemes = result.get("scheme_results", [])
        if not schemes:
            return (
                "No schemes found in your results.",
                [],
                {"matching_triggered": False},
            )

        # Parse scheme number from message (e.g. "2", "scheme 2", "tell me about 2")
        import re as _re
        nums = _re.findall(r"\d+", message)
        idx = (int(nums[0]) - 1) if nums else 0
        idx = max(0, min(idx, len(schemes) - 1))

        scheme = schemes[idx]
        response = render_scheme_detail(scheme, session.detected_language)
        return response, [], {"matching_triggered": False}

    def _find_scheme_by_name(self, query: str) -> dict | None:
        """Search for a scheme by name or abbreviation using substring matching.

        Strips question-word filler from the query, then finds the scheme whose
        name or short_name best overlaps with the remaining meaningful words.
        """
        import re as _re
        q_lower = query.lower()
        q_words = set(_re.findall(r'[a-zA-Z0-9]+', q_lower))

        # Remove generic question/filler words that appear in every query
        stop = {
            'what', 'is', 'are', 'how', 'does', 'the', 'a', 'an',
            'tell', 'me', 'about', 'can', 'i', 'apply', 'for', 'do',
            'explain', 'describe', 'information', 'details', 'scheme',
            'which', 'to', 'get', 'please', 'where',
        }
        q_words -= stop
        if not q_words:
            return None

        best_scheme: dict | None = None
        best_score = 0

        for scheme in self._retriever._schemes.values():
            name_text = (
                scheme.get("scheme_name", "").lower() + " " +
                scheme.get("short_name", "").lower()
            )
            score = sum(1 for w in q_words if w in name_text)
            if score > best_score:
                best_score = score
                best_scheme = scheme

        # Require at least one meaningful word to match
        return best_scheme if best_score >= 1 else None

    async def _handle_ask_question(
        self,
        session: ConversationSession,
        message: str,
        language: str,
    ) -> tuple[str, list[ProfileChange], dict[str, Any]]:
        """Handle informational questions about schemes (e.g., 'What is MGNREGA?').

        Uses LLM for a direct conversational answer when available; falls back
        to the scheme database lookup.
        """
        # 1. Try LLM direct answer first — richest response
        try:
            from src.conversation.extraction import _call_gemini
            llm_system = (
                "You are Sahayak, a helpful Indian government welfare scheme assistant. "
                "Answer the user's question concisely (2-4 sentences) in plain English. "
                "Focus on what the scheme does, who it helps, and what benefit it provides. "
                "Do NOT output JSON. Do NOT say you cannot answer. "
                "If you don't know the specific scheme, give a general helpful answer. "
                "End with a brief prompt to share their profile so you can check eligibility."
            )
            # Simple text response — not JSON
            from google import genai as _genai
            import os as _os
            api_key = _os.environ.get("GEMINI_API_KEY")
            if api_key:
                _client = _genai.Client(api_key=api_key)
                resp = _client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=[{"role": "user", "parts": [{"text": message}]}],
                    config={"system_instruction": llm_system, "temperature": 0.3},
                )
                llm_answer = (resp.text or "").strip()
                if llm_answer and len(llm_answer) > 20:
                    return llm_answer, [], {"matching_triggered": False}
        except Exception:
            pass  # Fall through to database lookup

        # 2. Try direct name search in scheme database
        scheme_data = self._find_scheme_by_name(message)

        if scheme_data:
            name = scheme_data.get("scheme_name", "This scheme")
            description = scheme_data.get("description", "")
            ministry = scheme_data.get("ministry", "")
            eligibility_summary = scheme_data.get("eligibility_summary", "")
            benefit_summary = scheme_data.get("benefit_summary", "")

            parts = [f"**{name}**"]

            # Use description if available, else construct a brief summary
            if description and len(description) > 20:
                # Trim to first 2 sentences for conversational feel
                sentences = description.replace(".\n", ". ").split(". ")
                brief = ". ".join(sentences[:2]).strip()
                if brief and not brief.endswith("."):
                    brief += "."
                parts.append(brief)
            elif eligibility_summary:
                parts.append(eligibility_summary)
            elif benefit_summary:
                parts.append(benefit_summary)
            elif ministry:
                parts.append(f"It's a government scheme run by the {ministry}.")

            response = "\n\n".join(parts)
            response += (
                "\n\nWould you like to check if you're eligible? "
                "Share your age, state, income, and community category — "
                "or just tell me about yourself in your own words."
            )
            return response, [], {"matching_triggered": False}

        # 3. Fall back to TF-IDF retrieval
        scheme_contexts = self._retriever.retrieve(
            message, session.profile_data, top_k=3
        )

        if scheme_contexts:
            sc = scheme_contexts[0]
            raw = self._retriever._schemes.get(sc.scheme_id, {})
            description = raw.get("description", "")
            eligibility_summary = raw.get("eligibility_summary", "")
            benefit_summary = raw.get("benefit_summary", "")
            ministry = raw.get("ministry", "")
            name = sc.scheme_name

            parts = [f"**{name}**"]
            detail = description or eligibility_summary or benefit_summary
            if detail and len(detail) > 20:
                sentences = detail.replace(".\n", ". ").split(". ")
                brief = ". ".join(sentences[:2]).strip()
                if brief and not brief.endswith("."):
                    brief += "."
                parts.append(brief)
            elif ministry:
                parts.append(f"It's a government scheme run by the {ministry}.")

            response = "\n\n".join(parts)
            if len(scheme_contexts) > 1:
                related = ", ".join(s.scheme_name for s in scheme_contexts[1:])
                response += f"\n\nYou might also be interested in: {related}"
            response += (
                "\n\nWant me to check your eligibility for these schemes? "
                "Tell me a bit about yourself."
            )
            return response, [], {"matching_triggered": False}

        # 4. No results
        response = (
            "I don't have specific information about that in my database. "
            "For official details, visit india.gov.in or your local government office.\n\n"
            "Meanwhile, let me find schemes you might qualify for — tell me about yourself."
        )
        return response, [], {"matching_triggered": False}

    async def _handle_post_results_chat(
        self,
        session: ConversationSession,
        message: str,
        language: str,
    ) -> tuple[str, list[ProfileChange], dict[str, Any]]:
        """Handle free-form conversation after matching results have been shown.

        Allows the user to:
        - Ask follow-up questions about their results
        - Provide profile corrections (triggers a re-match if significant)
        - Ask "what if" questions
        - Get scheme details

        Does NOT re-show the full results list — that's handled by the UI panel.
        """
        session.transition("EXPLORING")

        # Extract any new profile info from the message
        from src.conversation.extraction import extract_fields as _extract
        extraction = await _extract(
            message=message,
            existing_profile=session.profile_data,
            conversation_history=list(session.turns[-3:]),
            language=language,
        )

        changes: list[ProfileChange] = []
        for ef in extraction.extractions:
            change = session.update_profile_field(
                field_path=ef.field_path,
                value=ef.value,
                turn_number=session.turn_count,
                source_text=ef.source_span,
                confidence=ef.confidence,
            )
            changes.append(change)

        # If the user gave new profile data, re-run matching automatically
        if changes:
            return await self._run_matching(
                session, changes, {"extractions": [], "matching_triggered": True}
            )

        # Try to answer conversationally using LLM
        try:
            from src.conversation.extraction import _call_gemini
            import os as _os, json as _json
            api_key = _os.environ.get("GEMINI_API_KEY")
            if api_key:
                from google import genai as _genai
                result = session.latest_result or {}
                eligible_count = len([s for s in result.get("scheme_results", []) if s.get("status") == "ELIGIBLE"])
                near_miss_count = len([s for s in result.get("scheme_results", []) if s.get("status") == "NEAR_MISS"])
                top_names = [s["name"] for s in result.get("scheme_results", [])
                             if s.get("status") == "ELIGIBLE"][:5]
                profile_summary = _json.dumps(session.profile_data, default=str)
                system = (
                    "You are Sahayak, an Indian government welfare scheme assistant. "
                    f"The user has already completed their eligibility check. "
                    f"Results: {eligible_count} eligible schemes, {near_miss_count} near-miss. "
                    f"Top eligible: {', '.join(top_names) if top_names else 'none yet'}. "
                    f"User profile: {profile_summary}. "
                    "Answer the user's question helpfully in 2-3 sentences. "
                    "Do NOT re-list all the results. Be conversational and direct."
                )
                _c = _genai.Client(api_key=api_key)
                resp = _c.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=[{"role": "user", "parts": [{"text": message}]}],
                    config={"system_instruction": system, "temperature": 0.4},
                )
                llm_ans = (resp.text or "").strip()
                if llm_ans and len(llm_ans) > 10:
                    return llm_ans, [], {"matching_triggered": False}
        except Exception:
            pass

        # Fallback: generic helpful response
        result = session.latest_result or {}
        eligible_count = len([s for s in result.get("scheme_results", []) if s.get("status") == "ELIGIBLE"])
        if eligible_count:
            response = (
                f"You have {eligible_count} eligible schemes — tap 'View Results' to explore them. "
                "You can ask me about any specific scheme, or share more about yourself to refine the results."
            )
        else:
            response = (
                "Your results are in the panel on the right. "
                "Share more details about yourself to improve your matches, "
                "or ask me about any specific scheme."
            )
        return response, [], {"matching_triggered": False}

    # ------------------------------------------------------------------
    # Matching engine integration
    # ------------------------------------------------------------------

    async def _run_matching(
        self,
        session: ConversationSession,
        changes: list[ProfileChange],
        extraction_data: dict[str, Any],
    ) -> tuple[str, list[ProfileChange], dict[str, Any]]:
        """Run the Part 3 matching engine against the current profile."""
        import asyncio as _asyncio
        from src.alerting.telegram import alert

        session.transition("MATCHING")
        extraction_data["matching_triggered"] = True

        lang = session.detected_language

        try:
            from src.matching.engine import evaluate_scheme, evaluate_profile
            from src.matching.sequencing import compute_application_sequence
            from src.matching.output import assemble_matching_result
            from src.matching.profile import UserProfile
            from src.conversation.presentation import render_summary

            # Build UserProfile from flat profile_data dict
            profile = UserProfile.from_flat_json(session.profile_data)

            # Load rule base (cached across sessions — only read files once)
            if self._rule_base_cache is None:
                from src.matching.loader import load_rule_base
                self._rule_base_cache = await load_rule_base(self.rule_base_path)

            # Run evaluation, keeping raw SchemeDetermination objects for traceability
            determinations = await _asyncio.gather(
                *[evaluate_scheme(profile, rs, []) for rs in self._rule_base_cache.values()],
                return_exceptions=False,
            )
            sequence = compute_application_sequence(list(determinations), [])
            result = assemble_matching_result(profile, list(determinations), sequence, [])

            # Build rich result dict from raw determinations (full traceability)
            result_dict = self._result_to_dict(result, list(determinations))

            # Store for detail lookups and What-If comparisons
            session.latest_result = result_dict

            session.transition("PRESENTING")

            # --- Short conversational summary (full results go to frontend via turn_audit) ---
            all_results = result_dict.get("scheme_results", [])
            eligible_schemes = [s for s in all_results
                                if s["status"] in ("ELIGIBLE", "ELIGIBLE_WITH_CAVEATS")]
            near_miss_schemes = [s for s in all_results if s["status"] == "NEAR_MISS"]
            total = result_dict.get("total_evaluated", len(all_results))
            top_3 = [s["name"] for s in eligible_schemes[:3]]
            top_str = "\n".join(f"  • {n}" for n in top_3) if top_3 else "  (none found yet)"

            if lang in ("hi", "hinglish"):
                response_en_matching = (
                    f"Eligibility check complete! I reviewed {total:,} schemes.\n\n"
                    f"✅ {len(eligible_schemes)} schemes you qualify for\n"
                    f"🔶 {len(near_miss_schemes)} schemes — almost eligible\n\n"
                    f"Top 3 schemes:\n{top_str}\n\n"
                    "Tap 'See All Results' below."
                )
                try:
                    response = await translate_response(response_en_matching, lang)
                except Exception:
                    response = response_en_matching
            else:
                response = (
                    f"Eligibility check complete! I reviewed {total:,} schemes.\n\n"
                    f"✅ {len(eligible_schemes)} schemes you qualify for\n"
                    f"🔶 {len(near_miss_schemes)} schemes you're almost eligible for\n\n"
                    f"Top matches:\n{top_str}\n\n"
                    "Tap 'View All Results' below to explore details and apply."
                )

            # --- Attach full matching result to turn_audit for frontend rendering ---
            extraction_data["matching_result"] = result_dict
            if "turn_audit" in extraction_data:
                extraction_data["turn_audit"]["matching_result"] = result_dict
                # Replace per_rule_trace with real rule evaluations from top schemes
                per_rule_trace_from_matching: list[dict] = []
                for scheme in all_results[:8]:
                    for rule in scheme.get("rule_evaluations", [])[:6]:
                        per_rule_trace_from_matching.append({
                            "scheme_name": scheme["name"],
                            "scheme_status": scheme["status"],
                            "rule_id": rule.get("rule_id", ""),
                            "description": rule.get("display_text") or rule.get("rule_id", ""),
                            "passed": rule.get("outcome") == "PASS",
                            "user_value": rule.get("user_value"),
                            "rule_value": rule.get("rule_value"),
                            "source_ref": rule.get("source_quote", ""),
                            "caveat": "",
                        })
                if per_rule_trace_from_matching:
                    extraction_data["turn_audit"]["per_rule_trace"] = per_rule_trace_from_matching

            return response, changes, extraction_data

        except ImportError:
            logger.warning("Matching engine not available — returning partial response")
            session.transition("PRESENTING")
            populated = len(session.get_populated_field_paths())
            response = (
                "I gathered your information, but the eligibility engine is "
                "still loading its rule base.\n\n"
                f"Profile: {populated} fields recorded.\n"
                "Please try again in a moment, or type 'check' to retry."
            )
            return response, changes, extraction_data

        except Exception as exc:
            logger.error("Matching engine error: %s", exc)
            _asyncio.ensure_future(alert(
                f"⚠️ *Matching engine error* in session `{session.session_id[:8]}`\n"
                f"`{type(exc).__name__}: {exc}`"
            ))
            session.transition("PRESENTING")
            response = get_template(ERROR_MATCHING, lang)
            return response, changes, extraction_data

    def _result_to_dict(self, result: Any, determinations: list[Any] | None = None) -> dict[str, Any]:
        """Convert a MatchingResult to a fully-traced, presentation-compatible dict.

        When *determinations* are provided (raw SchemeDetermination objects), each
        scheme entry is enriched with:
          - per-rule evaluation trace (outcome, user_value, rule_value, source_url, display_text)
          - full confidence breakdown (composite + sub-scores + bottleneck label)
          - gap analysis (failed rules, remediation actions, near-miss score)
          - ambiguity flags from rule evaluations
        """
        # Build a fast lookup from scheme_id → SchemeDetermination
        det_by_id: dict[str, Any] = {}
        if determinations:
            for d in determinations:
                sid = getattr(d, "scheme_id", "")
                if sid:
                    det_by_id[sid] = d

        all_schemes: list[dict[str, Any]] = []

        for bucket in (
            getattr(result, "eligible_schemes", []),
            getattr(result, "near_miss_schemes", []),
            getattr(result, "requires_prerequisite_schemes", []),
            getattr(result, "partial_schemes", []),
            getattr(result, "insufficient_data_schemes", []),
            getattr(result, "ineligible_schemes", []),
        ):
            for scheme in bucket:
                raw = scheme.to_dict() if hasattr(scheme, "to_dict") else (
                    scheme if isinstance(scheme, dict) else {}
                )
                scheme_id = raw.get("scheme_id", "")

                # --- Confidence breakdown (explainable sub-scores) ---
                conf_raw = raw.get("confidence", {})
                if isinstance(conf_raw, dict):
                    conf_value = float(conf_raw.get("composite", 0.0) or 0.0)
                    confidence_breakdown = {
                        "composite": conf_value,
                        "composite_pct": int(conf_value * 100),
                        "label": conf_raw.get("composite_label", ""),
                        "rule_match_score": conf_raw.get("rule_match_score", 0),
                        "data_confidence": conf_raw.get("data_confidence", 0),
                        "profile_completeness": conf_raw.get("profile_completeness", 0),
                        "bottleneck": conf_raw.get("bottleneck", ""),
                        # Human explanation: why this score
                        "explanation": _conf_explanation(conf_raw),
                    }
                else:
                    conf_value = float(conf_raw) if conf_raw else 0.0
                    confidence_breakdown = {"composite": conf_value, "composite_pct": int(conf_value * 100)}

                # --- Rule evaluations + source traceability (from determination) ---
                rule_evals: list[dict] = []
                ambiguity_flags: list[dict] = []
                gap_analysis_dict: dict = {}

                det = det_by_id.get(scheme_id)
                if det is not None:
                    # Rule-by-rule trace with source citations
                    for ev in getattr(det, "rule_evaluations", []):
                        rule_evals.append({
                            "rule_id": ev.rule_id,
                            "field": ev.field,
                            "operator": ev.operator,
                            "rule_value": _safe_serialise(ev.rule_value),
                            "user_value": _safe_serialise(ev.user_value),
                            "outcome": ev.outcome,  # PASS/FAIL/UNDETERMINED
                            "outcome_score": ev.outcome_score,
                            "display_text": ev.display_text,
                            "source_quote": ev.source_quote,
                            "source_url": ev.source_url,
                            "audit_status": ev.audit_status,
                            "undetermined_reason": ev.undetermined_reason,
                            "ambiguity_notes": list(ev.ambiguity_notes or []),
                        })
                        # Collect unique ambiguity notes
                        for note in (ev.ambiguity_notes or []):
                            if note and note not in ambiguity_flags:
                                ambiguity_flags.append({"description": note, "rule_id": ev.rule_id})

                    # Gap analysis (for non-ELIGIBLE schemes)
                    ga = getattr(det, "gap_analysis", None)
                    if ga is not None:
                        failed = []
                        for fr in getattr(ga, "failed_rules", []):
                            failed.append({
                                "rule_id": fr.rule_id,
                                "field": fr.field,
                                "operator": fr.operator,
                                "required_value": _safe_serialise(fr.required_value),
                                "user_value": _safe_serialise(fr.user_value),
                                "gap_type": fr.gap_type,
                                "gap_magnitude": fr.gap_magnitude,
                                "display_text": fr.display_text,
                            })
                        remediations = []
                        for ra in getattr(ga, "remediation_actions", []):
                            remediations.append({
                                "action_id": ra.action_id,
                                "description": ra.description,
                                "urgency": ra.urgency,
                                "document_needed": ra.document_needed,
                                "estimated_effort": ra.estimated_effort,
                            })
                        gap_analysis_dict = {
                            "near_miss_score": getattr(ga, "near_miss_score", None),
                            "failed_rules": failed,
                            "remediation_actions": remediations,
                            "ambiguity_notes": [
                                {"id": an.ambiguity_id, "severity": an.severity,
                                 "description": an.description, "affects_rule": an.affects_rule}
                                for an in getattr(ga, "ambiguity_notes", [])
                            ],
                            "missing_documents": [
                                {"field": dg.document_field, "name": dg.document_name,
                                 "obtainable": dg.is_obtainable}
                                for dg in getattr(ga, "missing_documents", [])
                            ],
                        }

                all_schemes.append({
                    "id": scheme_id,
                    "name": raw.get("scheme_name", "Unknown"),
                    "status": raw.get("status", "INELIGIBLE"),
                    "confidence": conf_value,
                    "confidence_breakdown": confidence_breakdown,
                    "gap": raw.get("summary_text", ""),
                    "gap_short": "",
                    "action": self._status_to_action(raw.get("status", "")),
                    "required_documents": [],
                    "rule_evaluations": rule_evals,
                    "gap_analysis": gap_analysis_dict,
                    "ambiguity_flags": ambiguity_flags,
                    "discretion_warnings": raw.get("discretion_warnings", []),
                    "ministry": raw.get("ministry", ""),
                    "caveats": raw.get("caveats", []),
                })

        # Document checklist
        doc_checklist: list[dict] = []
        checklist_obj = getattr(result, "document_checklist", None)
        if checklist_obj:
            for item in getattr(checklist_obj, "items", []):
                doc_checklist.append({
                    "name": getattr(item, "document_name", ""),
                    "required_by": getattr(item, "required_by_schemes", []),
                    "mandatory": getattr(item, "is_mandatory", True),
                })

        summary_obj = getattr(result, "summary", None)

        # --- Application sequence (with prerequisite ordering) ---
        seq_steps: list[dict] = []
        seq_obj = getattr(result, "application_sequence", None)
        if seq_obj is not None:
            for step in getattr(seq_obj, "steps", []):
                seq_steps.append({
                    "order": getattr(step, "order", 0),
                    "scheme_id": getattr(step, "scheme_id", ""),
                    "scheme_name": getattr(step, "scheme_name", ""),
                    "status": getattr(step, "status", ""),
                    "depends_on": getattr(step, "depends_on", []),
                    "confidence": getattr(step, "confidence", 0.0),
                })

        return {
            "scheme_results": all_schemes,
            "document_checklist": doc_checklist,
            "application_sequence": seq_steps,
            "profile_warnings": getattr(result, "profile_warnings", []),
            "total_evaluated": getattr(summary_obj, "total_schemes_evaluated", len(all_schemes)),
            "eligible_count": getattr(summary_obj, "eligible_count", 0),
            "near_miss_count": getattr(summary_obj, "near_miss_count", 0),
        }

    @staticmethod
    def _status_to_action(status: str) -> str:
        """Return a one-line actionable instruction for a scheme status."""
        return {
            "ELIGIBLE": "Apply now — you meet all criteria",
            "ELIGIBLE_WITH_CAVEATS": "Apply, but review ambiguous conditions first",
            "NEAR_MISS": "Address the gaps listed below to qualify",
            "REQUIRES_PREREQUISITE": "Complete prerequisite scheme first",
            "PARTIAL": "Provide more information for a complete evaluation",
            "INSUFFICIENT_DATA": "Complete your profile for a full check",
            "INELIGIBLE": "You do not currently qualify for this scheme",
        }.get(status, "")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_followup_response(
        self,
        session: ConversationSession,
        extraction: Optional[ExtractionResult],
    ) -> str:
        """Build follow-up question response, RAG-enhanced when possible."""
        from src.conversation.extraction import compute_field_priority
        from src.conversation.templates import get_field_label

        populated = session.get_populated_field_paths()
        asked = set(session.asked_fields)
        skipped = set(session.skipped_fields)

        # Try RAG-enhanced proactive questions first
        rag_questions = self._retriever.get_proactive_questions(
            session.profile_data, top_k=MAX_FOLLOWUP_QUESTIONS_PER_TURN
        )
        rag_field_paths = {fp for fp, _, _ in rag_questions}

        # Fall back to priority-ordered generic questions for any gap
        generic_priorities = compute_field_priority(populated, asked, skipped)
        # Merge: RAG-targeted first, then generic
        merged: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for fp, q_en, q_hi in rag_questions:
            if fp not in populated and fp not in asked and fp not in skipped and fp not in seen:
                merged.append((fp, q_en, q_hi))
                seen.add(fp)
        for fp, q_en, q_hi in generic_priorities:
            if fp not in seen:
                merged.append((fp, q_en, q_hi))
                seen.add(fp)

        questions_to_ask = merged[:MAX_FOLLOWUP_QUESTIONS_PER_TURN]

        if not questions_to_ask:
            # No more questions — try matching with what we have
            if session.is_minimum_viable():
                return get_template(MATCHING_STARTED, "en")
            # Not minimum viable but out of questions — give a targeted prompt
            n = len(populated)
            missing_hints: list[str] = []
            if "applicant.age" not in populated:
                missing_hints.append("your age")
            if "location.state" not in populated:
                missing_hints.append("which state you're in")
            if "household.income_annual" not in populated:
                missing_hints.append("your household income (approximate is fine)")
            if "employment.type" not in populated:
                missing_hints.append("your employment type")
            if missing_hints:
                hint = ", ".join(missing_hints[:3])
                return (
                    f"I have {n} detail{'s' if n != 1 else ''} about you so far. "
                    f"Could you also share {hint}? "
                    "That'll help me find the most relevant schemes."
                )
            return (
                "I think I have enough to check your eligibility! "
                "Say \"check\" to see your results, or keep sharing more about yourself."
            )

        # Format questions — separate document fields (informational) from profile fields
        question_lines: list[str] = []
        doc_lines: list[str] = []
        bot_questions_meta: list[dict[str, Any]] = []
        q_idx = 1
        for fp, q_en, q_hi in questions_to_ask:
            if fp.startswith("documents.") and fp not in (
                "documents.aadhaar", "documents.bank_account"
            ):
                # Document fields — inform rather than ask
                label = get_field_label(fp, "en")
                doc_lines.append(f"  • {label} (upload portal will be available later)")
                session.mark_field_asked(fp)
            else:
                question_lines.append(f"  {q_idx}. {q_en}")
                q_idx += 1
                session.mark_field_asked(fp)
                bot_questions_meta.append({
                    "field_path": fp,
                    "question": q_en,
                    "index": q_idx - 1,
                })

        # Store the questions we just asked for contextual extraction next turn
        session.last_bot_questions = bot_questions_meta

        questions_str = "\n".join(question_lines)
        docs_str = ("\n\nDocuments you'll need to apply:\n" + "\n".join(doc_lines)) if doc_lines else ""

        # If no profile questions left, just show doc note (rare)
        if not question_lines and doc_lines:
            return (
                "Great, I think I have enough info! Here are the documents you'll need:\n"
                + "\n".join(doc_lines)
                + "\n\nSay \"check\" to see your eligibility results."
            )

        # Build extracted summary if we have extractions
        if extraction and extraction.extractions:
            extracted_labels = [
                f"  • {get_field_label(e.field_path, 'en')}: {e.value}"
                for e in extraction.extractions
            ]
            summary_str = "\n".join(extracted_labels)
            base = get_template(
                GATHERING_ACK, "en",
                extracted_summary=summary_str,
                questions=questions_str,
            )
            return base + docs_str

        # Context-sensitive opening based on how many profile fields are filled
        n_populated = len(populated)
        if n_populated == 0:
            opening = "To find the right government schemes for you, I have a few quick questions:"
        elif n_populated < 3:
            opening = "Good start! A few more details will help narrow down the right schemes:"
        elif n_populated < 4:
            opening = "Getting close! Just a couple more things:"
        else:
            opening = "Almost there! One more detail:"

        return (
            f"{opening}\n{questions_str}\n\n"
            "Feel free to skip anything by saying \"skip\" or \"not sure\"."
            + docs_str
        )

    def _fallback_form_question(self, session: ConversationSession) -> str:
        """Generate a structured form-mode question when LLM is unavailable."""
        from src.conversation.extraction import compute_field_priority

        populated = session.get_populated_field_paths()
        asked = set(session.asked_fields)
        skipped = set(session.skipped_fields)

        priorities = compute_field_priority(populated, asked, skipped)
        if priorities:
            fp, q_en, _ = priorities[0]
            session.mark_field_asked(fp)
            return f"\n{q_en}"
        return "\nPlease tell me about yourself."

    def _build_turn_audit(
        self,
        session: ConversationSession,
        extraction: "ExtractionResult",
        ner_report: Any,
        contradiction_flags: list,
        user_message: str,
    ) -> dict[str, Any]:
        """Build the complete turn_audit payload for the explainability panel.

        This is the holistic traceability record for one turn. It is always
        computed and attached to every response. The web UI surfaces it only
        when the user clicks the 🔍 button.
        """
        from dataclasses import asdict as _asdict

        # --- Extraction trace ---
        extraction_trace = []
        for r in extraction.reasoning_chain:
            # Find matching NER status
            ner_status = "PASS"
            for ef in ner_report.warned_fields:
                if ef.field_path == r.field_path:
                    ner_status = "WARN"
            for ef in ner_report.rejected_fields:
                if ef.field_path == r.field_path:
                    ner_status = "REJECTED"
            extraction_trace.append({
                "source_span": r.source_span,
                "field_path": r.field_path,
                "field_label": r.field_label,
                "value": r.value,
                "confidence": r.confidence,
                "ner_status": ner_status,
                "reasoning": r.reasoning_note,
            })

        # --- NER rejections ---
        ner_rejections = [
            {
                "field_path": ef.field_path,
                "rejected_value": ef.value,
                "reason": reason,
            }
            for ef, reason in [
                (ef, issue.reason)
                for ef in ner_report.rejected_fields
                for issue in ner_report.issues
                if issue.field_path == ef.field_path and issue.status == "REJECT"
            ]
        ]

        # --- Contradiction log for this turn ---
        contradictions = [
            {
                "type": f.contradiction_type,
                "type_name": f.contradiction_type_name,
                "field": f.field_path,
                "existing_value": f.existing_value,
                "new_value": f.new_value,
                "severity": f.severity,
                "resolution": f.resolution_status,
                "message": f.message_en,
            }
            for f in contradiction_flags
        ]

        # --- RAG scheme context ---
        scheme_contexts = self._retriever.retrieve(
            user_message, session.profile_data, top_k=3
        )
        scheme_context_dicts = [
            {
                "scheme_id": sc.scheme_id,
                "scheme_name": sc.scheme_name,
                "relevance": sc.relevance,
                "why_relevant": sc.why_relevant,
                "profile_gaps": sc.profile_gaps,
                "confidence_estimate": sc.confidence_estimate,
                "ambiguity_flags": [
                    {
                        "amb_id": af.amb_id,
                        "type_code": af.type_code,
                        "type_name": af.type_name,
                        "severity": af.severity,
                        "description": af.description,
                        "impact_on_result": af.impact_on_result,
                    }
                    for af in sc.ambiguity_flags
                ],
            }
            for sc in scheme_contexts
        ]

        # --- Gap analysis ---
        gap_analysis = [
            {
                "field_path": g.field_path,
                "field_label": g.field_label,
                "affects_schemes": g.affects_schemes,
                "fix_instruction": g.fix_instruction,
                "estimated_days": g.estimated_days,
            }
            for g in self._retriever.get_gap_analysis(session.profile_data)
        ]

        # --- Profile completeness confidence ---
        populated_count = len(session.get_populated_field_paths())
        target_count = max(MIN_VIABLE_FIELDS + 5, 1)  # rough target
        completeness = min(1.0, round(populated_count / target_count, 2))

        # --- Field provenance ---
        field_provenance = {
            fp: {
                "source_turn": prov.get("source_turn", 0),
                "source_text": prov.get("source_text", ""),
                "confidence": prov.get("confidence", "MEDIUM"),
                "was_corrected": prov.get("was_corrected", False),
                "was_inferred": prov.get("source_text", "").startswith("[inferred"),
            }
            for fp, prov in session.field_provenance.items()
        }

        # --- Per-rule trace (from scheme contexts) ---
        per_rule_trace = []
        for sc in scheme_contexts:
            for rt in sc.rule_traces[:5]:  # top 5 rules per scheme
                per_rule_trace.append({
                    "scheme_id": sc.scheme_id,
                    "scheme_name": sc.scheme_name,
                    "rule_id": rt.rule_id,
                    "description": rt.description,
                    "passed": rt.passed,
                    "user_value": rt.user_value,
                    "source_ref": rt.source_ref,
                    "source_url": rt.source_url,
                    "caveat": rt.caveat,
                })

        return {
            "turn": session.turn_count,
            "extraction_trace": extraction_trace,
            "ner_rejections": ner_rejections,
            "contradictions": contradictions,
            "scheme_context": scheme_context_dicts,
            "field_provenance": field_provenance,
            "gap_analysis": gap_analysis,
            "confidence_breakdown": {
                "profile_completeness": completeness,
                "extraction_quality": round(
                    len(ner_report.passed_fields) /
                    max(len(extraction.extractions), 1), 2
                ),
                "contradiction_free": len([f for f in contradiction_flags
                                           if f.severity == "blocking"]) == 0,
            },
            "per_rule_trace": per_rule_trace,
            "ambiguity_flags": [
                amb
                for sc_dict in scheme_context_dicts
                for amb in sc_dict.get("ambiguity_flags", [])
            ],
        }
