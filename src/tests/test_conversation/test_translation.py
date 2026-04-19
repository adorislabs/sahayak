"""Tests for src.conversation.translation — language detection."""

from __future__ import annotations

import pytest

from src.conversation.translation import (
    LanguageDetection,
    _has_hinglish_markers,
    _script_analysis,
    detect_language,
)


class TestScriptAnalysis:
    """Test character-level script analysis."""

    def test_pure_english(self) -> None:
        latin, devanagari, other = _script_analysis("Hello world")
        assert latin == 10
        assert devanagari == 0

    def test_pure_hindi(self) -> None:
        latin, devanagari, other = _script_analysis("नमस्ते दुनिया")
        assert devanagari > 0
        assert latin == 0

    def test_mixed_scripts(self) -> None:
        latin, devanagari, other = _script_analysis("Hello नमस्ते")
        assert latin > 0
        assert devanagari > 0

    def test_empty_string(self) -> None:
        latin, devanagari, other = _script_analysis("")
        assert latin == 0
        assert devanagari == 0

    def test_numbers_and_punctuation(self) -> None:
        latin, devanagari, other = _script_analysis("123, 456!")
        # Numbers are not Latin alpha, punctuation is skipped
        assert latin == 0


class TestHinglishMarkers:
    """Test Hinglish word detection."""

    def test_clear_hinglish(self) -> None:
        assert _has_hinglish_markers("main ek kisan hoon UP se")

    def test_more_hinglish(self) -> None:
        assert _has_hinglish_markers("mera ghar gaon mein hai")

    def test_pure_english(self) -> None:
        assert not _has_hinglish_markers("I am a farmer from UP")

    def test_single_marker_not_enough(self) -> None:
        # Need ≥2 markers
        assert not _has_hinglish_markers("hello mera name John")

    def test_scheme_related_hinglish(self) -> None:
        assert _has_hinglish_markers("kya yojana hai mere liye")


class TestDetectLanguage:
    """Test async language detection."""

    @pytest.mark.asyncio
    async def test_english(self) -> None:
        result = await detect_language("I am 35 years old from UP")
        assert result.language == "en"
        assert result.script == "latin"
        assert result.confidence > 0.5

    @pytest.mark.asyncio
    async def test_hindi(self) -> None:
        result = await detect_language("मैं 35 साल का हूँ उत्तर प्रदेश से")
        assert result.language == "hi"
        assert result.script == "devanagari"
        assert result.confidence > 0.5

    @pytest.mark.asyncio
    async def test_hinglish(self) -> None:
        result = await detect_language("main ek kisan hoon UP se meri umar 35 hai")
        assert result.language == "hinglish"
        assert result.confidence > 0.5

    @pytest.mark.asyncio
    async def test_empty_string(self) -> None:
        result = await detect_language("")
        assert result.language == "en"
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_mixed_script(self) -> None:
        result = await detect_language("Hello मेरा नाम Ram है")
        # Should detect as hinglish or mixed
        assert result.language in ("hi", "hinglish")
        assert result.script in ("devanagari", "mixed")
