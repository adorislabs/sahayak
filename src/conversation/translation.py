"""Language detection and translation for CBC Part 5.

Detects whether user input is English, Hindi (Devanagari), or Hinglish
(Hindi words in Latin script), and provides bidirectional translation
at the I/O boundary.  The conversation engine operates internally in
English; this module handles the language bridge.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from src.conversation.exceptions import TranslationError
from src.conversation.prompts import (
    LANGUAGE_DETECTION_PROMPT,
    TRANSLATE_TO_ENGLISH_PROMPT,
    TRANSLATE_RESPONSE_PROMPT,
)

logger = logging.getLogger(__name__)

# Devanagari Unicode block: U+0900 – U+097F
_DEVANAGARI_RANGE = range(0x0900, 0x0980)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class LanguageDetection:
    """Result of language detection."""

    language: str       # "en" / "hi" / "hinglish"
    confidence: float   # 0.0 – 1.0
    script: str         # "latin" / "devanagari" / "mixed"


# ---------------------------------------------------------------------------
# Character-level analysis
# ---------------------------------------------------------------------------


def _script_analysis(text: str) -> tuple[int, int, int]:
    """Count Latin, Devanagari, and other characters (excluding spaces/punct)."""
    latin = 0
    devanagari = 0
    other = 0
    for ch in text:
        if ch.isspace() or unicodedata.category(ch).startswith("P"):
            continue
        cp = ord(ch)
        if cp in _DEVANAGARI_RANGE:
            devanagari += 1
        elif ch.isascii() and ch.isalpha():
            latin += 1
        else:
            other += 1
    return latin, devanagari, other


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def detect_language(text: str) -> LanguageDetection:
    """Detect the language of user input.

    Uses fast character-level heuristics first, then falls back to
    LLM-based detection only for ambiguous Latin-script text that
    might be Hinglish.

    Returns:
        ``LanguageDetection`` with language, confidence, and script.
    """
    stripped = text.strip()
    if not stripped:
        return LanguageDetection(language="en", confidence=1.0, script="latin")

    latin, devanagari, _other = _script_analysis(stripped)
    total = latin + devanagari + max(_other, 1)

    devanagari_ratio = devanagari / total if total > 0 else 0
    latin_ratio = latin / total if total > 0 else 0

    # Pure Devanagari
    if devanagari_ratio >= 0.80:
        return LanguageDetection(language="hi", confidence=0.95, script="devanagari")

    # Mixed scripts → Hinglish
    if devanagari_ratio >= 0.20 and latin_ratio >= 0.20:
        return LanguageDetection(language="hinglish", confidence=0.85, script="mixed")

    # Pure Latin — could be English or transliterated Hindi (Hinglish)
    if latin_ratio >= 0.80:
        # Quick heuristic: check for common Hindi words in Latin script
        if _has_hinglish_markers(stripped):
            return LanguageDetection(
                language="hinglish", confidence=0.75, script="latin"
            )
        return LanguageDetection(language="en", confidence=0.90, script="latin")

    # Fallback
    return LanguageDetection(language="en", confidence=0.50, script="latin")


def _has_hinglish_markers(text: str) -> bool:
    """Quick check for common Hindi words written in Latin script."""
    markers = {
        "mera", "meri", "mere", "main", "mai", "hoon", "hun", "hai",
        "hain", "nahi", "nahin", "kya", "kaise", "kitna", "kitni",
        "kitne", "aur", "lekin", "agar", "toh", "se", "ka", "ki",
        "ke", "ko", "mein", "par", "woh", "yeh", "hum", "tum",
        "aap", "unka", "unki", "sala", "saal", "rupaye", "paisa",
        "kisan", "gaon", "shahar", "zamin", "zameen", "ghar",
        "parivar", "sarkar", "sarkari", "yojana",
        # Additional common Hinglish words
        "naam", "rehta", "rehti", "rehte", "hu", "ho", "bata",
        "tha", "thi", "the", "hua", "hui", "raha", "rahi", "rahte",
        "batao", "bataye", "chahiye", "milta", "milti", "karta",
        "karti", "karte", "khata", "khati", "bhi", "sirf", "bahut",
        "thoda", "zyada", "kam", "wala", "wali", "wale", "kamate",
        "kamata", "kamati", "rehna", "hau", "hun", "mere", "mujhe",
        "tumhe", "aapko", "hame", "hamara", "hamare", "hamari",
        "inhe", "unhe", "yahan", "wahan", "abhi", "pehle", "baad",
    }
    words = re.findall(r"[a-zA-Z]+", text.lower())
    word_set = set(words)
    overlap = word_set & markers
    # Short messages (≤6 words): 1 hit is enough; longer messages need 2
    threshold = 1 if len(words) <= 6 else 2
    return len(overlap) >= threshold


async def translate_to_english(
    text: str,
    source_language: str,
) -> str:
    """Translate Hindi or Hinglish text to English.

    Args:
        text: Input text in Hindi (Devanagari) or Hinglish (Latin).
        source_language: ``"hi"`` or ``"hinglish"``.

    Returns:
        English translation.

    Raises:
        TranslationError: If translation fails.
    """
    if source_language == "en":
        return text

    lang_name = "Hindi" if source_language == "hi" else "Hinglish"
    prompt = TRANSLATE_TO_ENGLISH_PROMPT.format(
        source_language=lang_name,
        text=text,
    )

    try:
        from src.conversation.extraction import _call_gemini
        result = await _call_gemini(
            system_prompt="You are a Hindi-English translator.",
            user_message=prompt,
        )
        translation = result.get("translation", "")
        if not translation:
            raise TranslationError(
                source_language=source_language,
                target_language="en",
                message="LLM returned empty translation",
            )
        return translation
    except Exception as exc:
        if isinstance(exc, TranslationError):
            raise
        raise TranslationError(
            source_language=source_language,
            target_language="en",
            message=str(exc),
        )


async def translate_response(text: str, lang: str) -> str:
    """Translate English text to the user's language (hi or hinglish).

    The LLM handles the nuance: Devanagari for Hindi, Latin script for Hinglish.

    Raises:
        TranslationError: If translation fails.
    """
    prompt = TRANSLATE_RESPONSE_PROMPT.format(target_language=lang, text=text)

    try:
        from src.conversation.extraction import _call_gemini
        result = await _call_gemini(
            system_prompt="You are a translator for an Indian welfare scheme assistant.",
            user_message=prompt,
        )
        translation = result.get("translation", "")
        if not translation:
            raise TranslationError(
                source_language="en",
                target_language=lang,
                message="LLM returned empty translation",
            )
        return translation
    except Exception as exc:
        if isinstance(exc, TranslationError):
            raise
        raise TranslationError(
            source_language="en",
            target_language=lang,
            message=str(exc),
        )


# Keep old names as aliases for any remaining call sites
async def translate_to_hindi(text: str) -> str:
    return await translate_response(text, "hi")


async def translate_to_hinglish(text: str) -> str:
    return await translate_response(text, "hinglish")
