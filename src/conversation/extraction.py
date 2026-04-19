"""LLM-powered structured field extraction for CBC Part 5.

Accepts natural-language user messages and extracts structured profile
fields using Gemini 2.0 Flash (or fallback).  Includes the
query → process → field explainability chain so users can see exactly
how their text was interpreted.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from src.conversation.config import (
    EXTRACTION_TIMEOUT_SECONDS,
    GEMINI_API_KEY_ENV,
    LLM_MAX_RETRIES,
    LLM_MODEL,
    LLM_TIMEOUT_SECONDS,
    MINIMUM_VIABLE_FIELDS,
    OPENROUTER_API_KEY_ENV,
    RECOMMENDED_FIELDS,
)
from src.conversation.exceptions import ExtractionError, LLMUnavailableError
from src.conversation.prompts import EXTRACTION_SYSTEM_PROMPT
from src.conversation.templates import (
    FIELD_QUESTIONS,
    get_field_label,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ExtractionReasoning:
    """One step in the query → process → field explainability chain."""

    source_span: str        # exact text that was matched
    field_path: str         # canonical dot-path
    field_label: str        # human-readable name (from templates)
    value: Any              # normalised value
    raw_value: str          # original text form of the value
    confidence: str         # HIGH / MEDIUM / LOW
    reasoning_note: str     # LLM's one-line explanation


@dataclass
class ExtractedField:
    """A single field extracted from user text."""

    field_path: str
    value: Any
    raw_value: str
    confidence: str
    source_span: str
    reasoning: str = ""
    clarification_needed: Optional[str] = None


@dataclass
class ExtractionResult:
    """Complete extraction result from one user message."""

    extractions: list[ExtractedField] = field(default_factory=list)
    detected_language: str = "en"
    unprocessed_text: str = ""
    reasoning_chain: list[ExtractionReasoning] = field(default_factory=list)
    suggested_followups: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# State name aliases for normalisation
# ---------------------------------------------------------------------------

STATE_ALIASES: dict[str, str] = {
    # English full names
    "andhra pradesh": "AP", "arunachal pradesh": "AR", "assam": "AS",
    "bihar": "BR", "chhattisgarh": "CG", "goa": "GA", "gujarat": "GJ",
    "haryana": "HR", "himachal pradesh": "HP", "jharkhand": "JH",
    "karnataka": "KA", "kerala": "KL", "madhya pradesh": "MP",
    "maharashtra": "MH", "manipur": "MN", "meghalaya": "ML",
    "mizoram": "MZ", "nagaland": "NL", "odisha": "OD", "punjab": "PB",
    "rajasthan": "RJ", "sikkim": "SK", "tamil nadu": "TN",
    "telangana": "TS", "tripura": "TR", "uttar pradesh": "UP",
    "uttarakhand": "UK", "west bengal": "WB",
    # UTs
    "delhi": "DL", "jammu and kashmir": "JK", "jammu kashmir": "JK",
    "ladakh": "LA", "chandigarh": "CH", "puducherry": "PY",
    "pondicherry": "PY",
    "andaman and nicobar": "AN", "andaman nicobar": "AN",
    "dadra and nagar haveli": "DD", "daman and diu": "DD",
    "lakshadweep": "LD",
    # Common abbreviations (lower)
    "up": "UP", "mp": "MP", "ap": "AP", "hp": "HP", "wb": "WB",
    "tn": "TN", "mh": "MH", "gj": "GJ", "rj": "RJ", "br": "BR",
    "jh": "JH", "cg": "CG", "ka": "KA", "kl": "KL", "ts": "TS",
    "od": "OD", "pb": "PB", "hr": "HR", "uk": "UK", "sk": "SK",
    "ga": "GA", "mn": "MN", "ml": "ML", "mz": "MZ", "nl": "NL",
    "tr": "TR", "ar": "AR", "as": "AS", "dl": "DL", "jk": "JK",
    "la": "LA", "ch": "CH", "py": "PY", "an": "AN", "dd": "DD",
    "ld": "LD",
    # Hindi names
    "उत्तर प्रदेश": "UP", "मध्य प्रदेश": "MP", "बिहार": "BR",
    "राजस्थान": "RJ", "महाराष्ट्र": "MH", "गुजरात": "GJ",
    "कर्नाटक": "KA", "तमिलनाडु": "TN", "पश्चिम बंगाल": "WB",
    "आंध्र प्रदेश": "AP", "तेलंगाना": "TS", "केरल": "KL",
    "ओडिशा": "OD", "असम": "AS", "पंजाब": "PB", "हरियाणा": "HR",
    "छत्तीसगढ़": "CG", "झारखंड": "JH", "उत्तराखंड": "UK",
    "हिमाचल प्रदेश": "HP", "त्रिपुरा": "TR", "मेघालय": "ML",
    "मणिपुर": "MN", "नागालैंड": "NL", "मिज़ोरम": "MZ",
    "अरुणाचल प्रदेश": "AR", "सिक्किम": "SK", "गोवा": "GA",
    "दिल्ली": "DL", "जम्मू-कश्मीर": "JK", "जम्मू कश्मीर": "JK",
    "लद्दाख": "LA", "चंडीगढ़": "CH", "पुदुचेरी": "PY",
    # Common Hindi abbreviations
    "यूपी": "UP", "एमपी": "MP",
}

# Caste aliases
CASTE_ALIASES: dict[str, str] = {
    "dalit": "SC", "scheduled caste": "SC", "sc": "SC",
    "adivasi": "ST", "tribal": "ST", "scheduled tribe": "ST", "st": "ST",
    "backward class": "OBC", "other backward class": "OBC", "obc": "OBC",
    "general": "GENERAL", "unreserved": "GENERAL", "gen": "GENERAL",
    "ews": "EWS", "economically weaker": "EWS",
    # Hindi
    "अनुसूचित जाति": "SC", "दलित": "SC",
    "अनुसूचित जनजाति": "ST", "आदिवासी": "ST",
    "अन्य पिछड़ा वर्ग": "OBC", "ओबीसी": "OBC",
    "सामान्य": "GENERAL",
}


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def normalize_value(field_path: str, raw_value: Any) -> Any:
    """Normalise an extracted value to its canonical form.

    Handles:
    - State name/abbreviation → 2-letter code
    - Caste aliases → canonical code (SC/ST/OBC/GENERAL/EWS)
    - Lakh/thousand → numeric conversion
    - Birth year → age
    - Land units (bigha, hectare) → acres

    Raises:
        ValueError: If the value cannot be normalised for the given field.
    """
    if raw_value is None:
        return None

    if field_path == "location.state":
        if isinstance(raw_value, str):
            lookup = raw_value.strip().lower()
            code = STATE_ALIASES.get(lookup)
            if code:
                return code
            # Already a valid 2-letter code?
            if len(raw_value) == 2 and raw_value.upper() in STATE_ALIASES.values():
                return raw_value.upper()
        return raw_value

    if field_path == "applicant.caste_category":
        if isinstance(raw_value, str):
            lookup = raw_value.strip().lower()
            code = CASTE_ALIASES.get(lookup)
            if code:
                return code
            # Already canonical?
            upper = raw_value.strip().upper()
            if upper in {"SC", "ST", "OBC", "GENERAL", "EWS"}:
                return upper
        return raw_value

    if field_path in ("household.income_annual", "household.income_monthly"):
        return _normalize_currency(raw_value)

    if field_path == "applicant.age" and isinstance(raw_value, str):
        # Handle "born in YYYY" → age
        match = re.search(r"\b(19|20)\d{2}\b", raw_value)
        if match:
            birth_year = int(match.group())
            return datetime.now(tz=timezone.utc).year - birth_year
        return _safe_int(raw_value)

    if field_path == "household.land_acres":
        return _normalize_land(raw_value)

    if field_path == "household.size":
        return _safe_int(raw_value)

    if field_path == "applicant.disability_percentage":
        return _safe_int(raw_value)

    return raw_value


def _normalize_currency(value: Any) -> int:
    """Convert Indian currency expressions to integer INR."""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        text = value.lower().replace(",", "").replace("₹", "").strip()
        # Handle "X lakh" / "X.Y lakh"
        match = re.search(r"([\d.]+)\s*(lakh|lac|लाख)", text)
        if match:
            return int(float(match.group(1)) * 100_000)
        # Handle "X crore"
        match = re.search(r"([\d.]+)\s*(crore|करोड़)", text)
        if match:
            return int(float(match.group(1)) * 10_000_000)
        # Handle "X thousand" / "X hazar"
        match = re.search(r"([\d.]+)\s*(thousand|hazar|हज़ार|हजार)", text)
        if match:
            return int(float(match.group(1)) * 1_000)
        # Plain number
        match = re.search(r"[\d.]+", text)
        if match:
            return int(float(match.group()))
    return int(value) if value else 0


def _normalize_land(value: Any) -> float:
    """Convert land area to acres."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.lower().strip()
        # Bigha (default Bihar/UP conversion: 1 bigha ≈ 0.62 acres)
        match = re.search(r"([\d.]+)\s*(bigha|बीघा)", text)
        if match:
            return round(float(match.group(1)) * 0.62, 2)
        # Hectare
        match = re.search(r"([\d.]+)\s*(hectare|हेक्टेयर)", text)
        if match:
            return round(float(match.group(1)) * 2.47, 2)
        # Acres (or plain number)
        match = re.search(r"[\d.]+", text)
        if match:
            return float(match.group())
    return float(value) if value else 0.0


def _safe_int(value: Any) -> int:
    """Extract an integer from a value that may contain non-numeric text."""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        match = re.search(r"\d+", value)
        if match:
            return int(match.group())
    return 0


# ---------------------------------------------------------------------------
# Follow-up question generation
# ---------------------------------------------------------------------------


def compute_field_priority(
    populated_fields: set[str],
    asked_fields: set[str],
    skipped_fields: set[str],
) -> list[tuple[str, str, str]]:
    """Compute the next fields to ask about, ordered by scheme impact.

    Returns:
        List of ``(field_path, question_en, question_hi)`` tuples.
        Excludes already-populated, already-asked, and skipped fields.
    """
    exclude = populated_fields | asked_fields | skipped_fields
    result: list[tuple[str, str, str]] = []
    for q in FIELD_QUESTIONS:
        fp = q["field"]
        if fp not in exclude:
            result.append((fp, q["en"], q["hi"]))
    return result


# ---------------------------------------------------------------------------
# Helper: safe field label (used by web.py resume audit builder)
# ---------------------------------------------------------------------------

def _get_field_label_safe(field_path: str) -> str:
    """Return a human-readable label for a field_path, falling back to the path itself."""
    try:
        label = get_field_label(field_path, "en")
        return label if label else field_path.replace(".", " ").replace("_", " ").title()
    except Exception:
        return field_path.replace(".", " ").replace("_", " ").title()


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


async def _call_gemini(
    system_prompt: str,
    user_message: str,
) -> dict[str, Any]:
    """Call Gemini API with automatic OpenRouter fallback on 429.

    Attempts:
      1. Gemini 2.0 Flash (primary)
      2. OpenRouter/Gemma-3 27B (fallback when Gemini is rate-limited)

    Raises:
        LLMUnavailableError: After all retries on both providers exhausted.
        ExtractionError: If response cannot be parsed as JSON.
    """
    api_key = os.environ.get(GEMINI_API_KEY_ENV)
    if not api_key:
        raise LLMUnavailableError(
            provider="gemini",
            attempts=0,
            last_error=f"{GEMINI_API_KEY_ENV} environment variable not set",
        )

    try:
        from google import genai
    except ImportError:
        raise LLMUnavailableError(
            provider="gemini",
            attempts=0,
            last_error="google-genai package not installed",
        )

    client = genai.Client(api_key=api_key)
    last_error = ""
    rate_limited = False

    # ── Primary: Gemini ────────────────────────────────────────────────────
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=LLM_MODEL,
                contents=[
                    {"role": "user", "parts": [{"text": user_message}]},
                ],
                config={
                    "system_instruction": system_prompt,
                    "temperature": 0.1,
                    "response_mime_type": "application/json",
                },
            )

            raw_text = response.text.strip() if response.text else ""
            if not raw_text:
                raise ExtractionError("LLM returned empty response", raw_response="")

            if raw_text.startswith("```"):
                raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
                raw_text = re.sub(r"\s*```$", "", raw_text)

            return json.loads(raw_text)  # type: ignore[no-any-return]

        except json.JSONDecodeError as exc:
            raise ExtractionError(
                f"LLM returned invalid JSON: {exc}",
                raw_response=raw_text if "raw_text" in dir() else None,  # type: ignore[possibly-undefined]
            )
        except ExtractionError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            # Detect 429 / quota exhausted — skip remaining Gemini retries
            if "429" in last_error or "RESOURCE_EXHAUSTED" in last_error or "quota" in last_error.lower():
                rate_limited = True
                logger.warning("Gemini rate-limited (429) — switching to OpenRouter fallback")
                break
            logger.warning(
                "Gemini API attempt %d/%d failed: %s",
                attempt, LLM_MAX_RETRIES, last_error,
            )
            if attempt == LLM_MAX_RETRIES:
                break

    # ── Fallback: OpenRouter ───────────────────────────────────────────────
    or_key = os.environ.get(OPENROUTER_API_KEY_ENV) or os.environ.get("OPEN_KEY")
    if or_key:
        try:
            result = await _call_openrouter(
                system_prompt=system_prompt,
                user_message=user_message,
                api_key=or_key,
            )
            return result
        except Exception as exc:  # noqa: BLE001
            last_error = f"OpenRouter fallback also failed: {exc}"
            logger.warning(last_error)

    raise LLMUnavailableError(
        provider="gemini+openrouter",
        attempts=LLM_MAX_RETRIES,
        last_error=last_error,
    )


async def _call_openrouter(
    system_prompt: str,
    user_message: str,
    api_key: str,
    model: str = "google/gemma-3-27b-it:free",
) -> dict[str, Any]:
    """Call OpenRouter API for LLM inference.

    Uses httpx (already in project dependencies) for async HTTP.
    Falls back to synchronous httpx if async import fails.

    Raises:
        ExtractionError: On JSON parse failure.
        Exception: On HTTP / network error (caller catches and logs).
    """
    import httpx

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/cbc-project",
        "X-Title": "CBC Scheme Eligibility Checker",
    }

    # Try async client first, fall back to sync
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        # Sync fallback (blocks event loop but works)
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

    content = data["choices"][0]["message"]["content"]
    raw_text = content.strip()

    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ExtractionError(
            f"OpenRouter returned invalid JSON: {exc}",
            raw_response=raw_text[:500],
        )



# ---------------------------------------------------------------------------
# Conversation context helper
# ---------------------------------------------------------------------------


def _extract_last_questions(conversation_history: list[dict[str, Any]]) -> str:
    """Extract the numbered questions from the last system response.

    Looks for the last_bot_questions field first (structured data),
    then falls back to parsing numbered lines from system_response.
    """
    if not conversation_history:
        return ""

    # conversation_history is a list of turn dicts (most recent last)
    # Check the last turn for last_bot_questions metadata
    last_turn = conversation_history[-1]

    # If structured question data is available (set by engine)
    bot_questions = last_turn.get("last_bot_questions", [])
    if bot_questions:
        lines = []
        for q in bot_questions:
            idx = q.get("index", 0)
            question = q.get("question", "")
            field_path = q.get("field_path", "")
            lines.append(f"  {idx}. {question} (field: {field_path})")
        return "\n".join(lines)

    # Fallback: parse numbered lines from the system response text
    response_text = last_turn.get("system_response_en", "") or last_turn.get("system_response", "")
    if not response_text:
        return ""

    import re
    numbered = re.findall(r"^\s*(\d+)\.\s+(.+)$", response_text, re.MULTILINE)
    if numbered:
        return "\n".join(f"  {n}. {q}" for n, q in numbered)

    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def extract_fields(
    message: str,
    existing_profile: dict[str, Any],
    conversation_history: list[dict[str, Any]],
    language: str = "en",
) -> ExtractionResult:
    """Extract structured profile fields from a user message.

    Uses LLM structured output (Gemini with OpenRouter fallback).

    Args:
        message: Raw user message (any language).
        existing_profile: Current profile as dict (provides context).
        conversation_history: Recent turns for contextual extraction.
        language: Detected language of the message.

    Returns:
        ``ExtractionResult`` with extracted fields, reasoning chain,
        and follow-up suggestions.

    Raises:
        ExtractionError: If LLM returns unparseable response.
    """
    # Pre-process: normalise Hinglish number words so BOTH the LLM and the
    # regex fallback receive a more parseable version.  This converts e.g.
    # "baara saal ka hu" → "12 saal ka hu" before the LLM ever sees the text.
    _HINGLISH_NUM_WORDS: dict[str, int] = {
        "ek": 1, "do": 2, "teen": 3, "chaar": 4, "char": 4,
        "paanch": 5, "panch": 5, "chhah": 6, "chheh": 6,
        "saat": 7, "sat": 7, "aath": 8, "ath": 8, "nau": 9, "naw": 9,
        "das": 10, "gyarah": 11, "barah": 12, "baara": 12, "bara": 12,
        "terah": 13, "chaudah": 14, "pandrah": 15, "solah": 16,
        "satrah": 17, "atharah": 18, "unnees": 19, "bees": 20,
        "ikees": 21, "battees": 32, "chalees": 40, "pachaas": 50,
        "saath": 60, "sattar": 70, "assi": 80, "nabbe": 90,
    }
    _HINGLISH_UNITS = r"(saal|sal|years?|mahine|members?|hazar|hazaar|lakh|lac)\b"

    def _norm_hinglish(m: re.Match) -> str:
        word = m.group(1).lower()
        unit = m.group(2).lower()
        num = _HINGLISH_NUM_WORDS.get(word)
        if num is None:
            return m.group(0)
        if unit in ("hazar", "hazaar"):
            return str(num * 1_000)
        if unit in ("lakh", "lac"):
            return str(num * 100_000)
        return f"{num} {unit}"

    _hinglish_pat = re.compile(
        r"\b(" + "|".join(re.escape(k) for k in _HINGLISH_NUM_WORDS) + r")\s+" + _HINGLISH_UNITS,
        re.IGNORECASE,
    )
    normalised_message = _hinglish_pat.sub(_norm_hinglish, message)

    # Build context addendum for the LLM
    context_lines: list[str] = []
    if existing_profile:
        context_lines.append(
            f"Already known about this person: {json.dumps(existing_profile, default=str)}"
        )
        context_lines.append("Only extract NEW information not already captured above.")

    # Include conversation context so the LLM can map answers to questions
    if conversation_history:
        # Extract the last bot questions from the most recent turn
        last_questions = _extract_last_questions(conversation_history)
        if last_questions:
            context_lines.append(
                "The system just asked these questions (numbered). "
                "The user's reply may answer them by position or keyword:\n"
                + last_questions
            )

    full_message = normalised_message
    if context_lines:
        full_message = "\n".join(context_lines) + "\n\nUser message: " + normalised_message

    # ── LLM extraction (no regex fallback) ────────────────────────────────
    raw: dict[str, Any] = {}
    try:
        raw = await _call_gemini(EXTRACTION_SYSTEM_PROMPT, full_message)
    except LLMUnavailableError as exc:
        logger.warning("LLM unavailable (%s) — returning empty extraction", exc)
        return ExtractionResult(detected_language=language)

    # Parse LLM response into ExtractedField objects
    extractions: list[ExtractedField] = []
    reasoning_chain: list[ExtractionReasoning] = []

    for item in raw.get("extractions", []):
        fp = item.get("field_path", "")
        raw_val = item.get("raw_value", "")
        value = item.get("value")
        confidence = item.get("confidence", "MEDIUM")
        reasoning = item.get("reasoning", "")
        clarification = item.get("clarification_needed")

        # Normalise the extracted value
        try:
            normalised = normalize_value(fp, value)
        except (ValueError, TypeError):
            normalised = value

        ef = ExtractedField(
            field_path=fp,
            value=normalised,
            raw_value=str(raw_val),
            confidence=confidence,
            source_span=str(raw_val),
            reasoning=reasoning,
            clarification_needed=clarification,
        )
        extractions.append(ef)

        # Build explainability chain entry
        reasoning_chain.append(
            ExtractionReasoning(
                source_span=str(raw_val),
                field_path=fp,
                field_label=get_field_label(fp, language),
                value=normalised,
                raw_value=str(raw_val),
                confidence=confidence,
                reasoning_note=reasoning,
            )
        )

    # Compute next follow-up questions
    populated = set(existing_profile.keys())
    new_fields = {e.field_path for e in extractions}
    all_populated = populated | new_fields
    followups = compute_field_priority(all_populated, set(), set())
    suggested = [q[1] for q in followups[:3]]  # top 3 EN questions

    detected_lang = raw.get("detected_language", language)

    return ExtractionResult(
        extractions=extractions,
        detected_language=detected_lang,
        unprocessed_text=raw.get("unprocessed_text", ""),
        reasoning_chain=reasoning_chain,
        suggested_followups=suggested,
    )


def format_extraction_summary(
    reasoning_chain: list[ExtractionReasoning],
    language: str = "en",
) -> str:
    """Format the extraction reasoning chain as a user-facing summary.

    This is the query → process → field transparency feature the user
    sees after their first message.

    Args:
        reasoning_chain: From ``ExtractionResult.reasoning_chain``.
        language: ``"en"`` or ``"hi"``.

    Returns:
        Formatted multi-line string.
    """
    if not reasoning_chain:
        if language in ("hi", "hinglish"):
            return "कोई जानकारी नहीं निकाली जा सकी।"
        return "No information could be extracted."

    if language in ("hi", "hinglish"):
        header = "आपके संदेश से निकाली गई जानकारी:"
        conf_map = {"HIGH": "उच्च", "MEDIUM": "मध्यम", "LOW": "कम"}
    else:
        header = "I extracted the following from your message:"
        conf_map = {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}

    lines = [header]
    for r in reasoning_chain:
        conf = conf_map.get(r.confidence, r.confidence)
        lines.append(
            f'  • "{r.source_span}"  →  {r.field_label} = {r.value}  [{conf}]'
        )
    return "\n".join(lines)
