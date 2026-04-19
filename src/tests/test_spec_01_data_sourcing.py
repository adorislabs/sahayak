"""
Tests for spec_01_data_sourcing.py

Module: src/spec_01_data_sourcing.py
Spec:   docs/part1-planning/tests/spec_01_data_sourcing.md
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.exceptions import NetworkError, PDFError, ParseError, SchemeNotFoundError, ValidationError  # type: ignore[import]
from src.data_sourcing import (  # type: ignore[import]
    classify_active_dormant,
    download_tier2_pdf,
    fetch_tier1_text,
    load_kaggle_row,
    run_ocr,
    scrape_scheme_page,
)
from src.schema import SchemeStatus  # type: ignore[import]


# ---------------------------------------------------------------------------
# Section 1: fetch_tier1_text
# ---------------------------------------------------------------------------


class TestFetchTier1Text:
    async def test__valid_scheme_id__returns_non_empty_string(self) -> None:
        """Valid scheme → non-empty eligibility text string."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><section id='eligibility'>Applicant must own land.</section></html>"

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            result = await fetch_tier1_text("PMKISAN")

        assert isinstance(result, str)
        assert len(result) > 0

    async def test__scheme_not_on_myscheme__raises_scheme_not_found_error(self) -> None:
        """HTTP 404 → SchemeNotFoundError with scheme ID in message."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(SchemeNotFoundError) as exc_info:
                await fetch_tier1_text("SCHEME-NONEXISTENT")

        assert "SCHEME-NONEXISTENT" in str(exc_info.value)

    async def test__network_timeout__raises_network_error(self) -> None:
        """HTTP timeout → NetworkError."""
        import httpx

        with patch(
            "httpx.AsyncClient.get",
            new_callable=AsyncMock,
            side_effect=httpx.TimeoutException("timeout"),
        ):
            with pytest.raises(NetworkError):
                await fetch_tier1_text("PMKISAN")

    async def test__http_500_response__raises_network_error(self) -> None:
        """HTTP 500 → NetworkError."""
        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(NetworkError):
                await fetch_tier1_text("MGNREGA")

    async def test__empty_eligibility_section__raises_parse_error(self) -> None:
        """HTTP 200 but empty eligibility section → ParseError."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><section id='eligibility'></section></html>"

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(ParseError):
                await fetch_tier1_text("PMKISAN")


# ---------------------------------------------------------------------------
# Section 2: download_tier2_pdf
# ---------------------------------------------------------------------------


class TestDownloadTier2Pdf:
    async def test__valid_url__writes_pdf_to_disk(self, tmp_path: Path) -> None:
        """Valid PDF URL → file saved as {scheme_id}.pdf in dest_dir."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/pdf"}
        mock_response.content = b"%PDF-1.4 fake pdf content"

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            path = await download_tier2_pdf(
                "https://pmkisan.gov.in/guidelines.pdf", "PMKISAN", tmp_path
            )

        assert path.exists()
        assert path.name == "PMKISAN.pdf"
        assert path.suffix == ".pdf"

    async def test__http_404__raises_pdf_error(self, tmp_path: Path) -> None:
        """404 PDF URL → PDFError."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(PDFError):
                await download_tier2_pdf("https://india.gov.in/missing.pdf", "PMKISAN", tmp_path)

    async def test__response_is_not_pdf__raises_pdf_error(self, tmp_path: Path) -> None:
        """Non-PDF Content-Type → PDFError."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.content = b"<html>not a pdf</html>"

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(PDFError):
                await download_tier2_pdf("https://india.gov.in/page.html", "PMKISAN", tmp_path)

    async def test__file_size_exceeds_50mb__raises_pdf_error(self, tmp_path: Path) -> None:
        """Simulated 51 MB Content-Length → PDFError mentioning 'size limit'."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "Content-Type": "application/pdf",
            "Content-Length": str(51 * 1024 * 1024),
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(PDFError) as exc_info:
                await download_tier2_pdf("https://example.gov.in/big.pdf", "PMKISAN", tmp_path)

        assert "size limit" in str(exc_info.value).lower()

    async def test__network_timeout__raises_network_error(self, tmp_path: Path) -> None:
        """Download timeout → NetworkError."""
        import httpx

        with patch(
            "httpx.AsyncClient.get",
            new_callable=AsyncMock,
            side_effect=httpx.TimeoutException("timeout"),
        ):
            with pytest.raises(NetworkError):
                await download_tier2_pdf("https://example.gov.in/slow.pdf", "PMKISAN", tmp_path)


# ---------------------------------------------------------------------------
# Section 3: classify_active_dormant
# ---------------------------------------------------------------------------


class TestClassifyActiveDormant:
    def test__recent_fund_releases__returns_active(self) -> None:
        """Fund release < 12 months + beneficiary_count > 0 → ACTIVE."""
        from datetime import date, timedelta

        recent = (date.today() - timedelta(days=300)).isoformat()
        fund_data = {
            "last_fund_release_date": recent,
            "beneficiary_count": 50_000_000,
            "status": "ongoing",
        }
        result = classify_active_dormant("PMKISAN", fund_data)
        assert result == SchemeStatus.ACTIVE

    def test__no_fund_releases_in_24_months__returns_dormant(self) -> None:
        """No releases in 24+ months → DORMANT."""
        from datetime import date, timedelta

        old = (date.today() - timedelta(days=760)).isoformat()
        fund_data = {
            "last_fund_release_date": old,
            "beneficiary_count": 0,
            "status": "ongoing",
        }
        result = classify_active_dormant("OLD-SCHEME", fund_data)
        assert result == SchemeStatus.DORMANT

    def test__officially_discontinued__returns_discontinued(self) -> None:
        """Officially ended scheme → DISCONTINUED."""
        fund_data = {"status": "discontinued", "discontinuation_date": "2021-03-01"}
        result = classify_active_dormant("SCHEME-X", fund_data)
        assert result == SchemeStatus.DISCONTINUED

    def test__missing_required_keys__raises_validation_error(self) -> None:
        """Empty fund_data dict → ValidationError."""
        with pytest.raises(ValidationError):
            classify_active_dormant("PMKISAN", {})

    def test__dataful_unavailable__returns_unverified(self) -> None:
        """None fund_data (Dataful.in down) → 'unverified'; no exception."""
        result = classify_active_dormant("PMKISAN", None)
        assert result == "unverified"


# ---------------------------------------------------------------------------
# Section 4: run_ocr
# ---------------------------------------------------------------------------


class TestRunOcr:
    async def test__scanned_pdf__returns_extracted_text(self, tmp_path: Path) -> None:
        """Scanned PDF → OCR extracts non-empty text."""
        fake_pdf = tmp_path / "scanned.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 image-only")

        with patch(
            "src.data_sourcing.pytesseract.image_to_string",
            return_value="Eligible farmer families owning land",
        ):
            with patch("src.data_sourcing._is_pdf", return_value=True):
                with patch("src.data_sourcing._has_text_layer", return_value=False):
                    text = await run_ocr(fake_pdf)

        assert isinstance(text, str)
        assert len(text) > 0

    async def test__ocr_yields_empty_string__raises_pdf_error(self, tmp_path: Path) -> None:
        """OCR returns empty string → PDFError."""
        fake_pdf = tmp_path / "blank.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 blank")

        with patch("src.data_sourcing.pytesseract.image_to_string", return_value=""):
            with patch("src.data_sourcing._is_pdf", return_value=True):
                with patch("src.data_sourcing._has_text_layer", return_value=False):
                    with pytest.raises(PDFError):
                        await run_ocr(fake_pdf)

    async def test__non_pdf_file__raises_pdf_error(self, tmp_path: Path) -> None:
        """Text file with .pdf extension → PDFError."""
        fake = tmp_path / "notreal.pdf"
        fake.write_text("this is not a pdf")

        with patch("src.data_sourcing._is_pdf", return_value=False):
            with pytest.raises(PDFError):
                await run_ocr(fake)

    async def test__file_does_not_exist__raises_pdf_error(self) -> None:
        """Nonexistent path → PDFError."""
        with pytest.raises(PDFError):
            await run_ocr(Path("/tmp/nonexistent_cbc_test.pdf"))


# ---------------------------------------------------------------------------
# Section 5: scrape_scheme_page
# ---------------------------------------------------------------------------


class TestScrapeScheme:
    async def test__valid_page__returns_eligibility_text(self) -> None:
        """Playwright fetch of valid page → non-empty eligibility text."""
        with patch(
            "src.data_sourcing._playwright_fetch",
            new_callable=AsyncMock,
            return_value="Unorganised Workers aged 18-40 years are eligible",
        ):
            text = await scrape_scheme_page("https://labour.gov.in/pmsym")

        assert isinstance(text, str)
        assert len(text) > 0

    async def test__page_unreachable__raises_network_error(self) -> None:
        """Page navigation fails → NetworkError."""
        with patch(
            "src.data_sourcing._playwright_fetch",
            new_callable=AsyncMock,
            side_effect=NetworkError("page unreachable"),
        ):
            with pytest.raises(NetworkError):
                await scrape_scheme_page("https://unreachable.gov.in/scheme")

    async def test__eligibility_section_not_found__raises_parse_error(self) -> None:
        """Page loads but no eligibility section found → ParseError."""
        with patch(
            "src.data_sourcing._playwright_fetch",
            new_callable=AsyncMock,
            return_value="",  # No eligibility text extracted
        ):
            with pytest.raises(ParseError):
                await scrape_scheme_page("https://some.gov.in/scheme")


# ---------------------------------------------------------------------------
# Section 6: load_kaggle_row
# ---------------------------------------------------------------------------


class TestLoadKaggleRow:
    def test__valid_row__returns_parse_input(self) -> None:
        """Valid CSV row dict → ParseInput with correct fields."""
        from src.data_sourcing import ParseInput  # type: ignore[import]

        row = {
            "scheme_name": "PM Shram Yogi Maandhan",
            "eligibility": "Unorganised sector workers aged 18-40...",
            "benefits": "₹3000/month pension after 60",
        }
        result = load_kaggle_row(row)

        assert isinstance(result, ParseInput)
        assert result.raw_text == row["eligibility"]
        assert result.input_type == "kaggle_csv"
        assert result.scheme_id is not None and len(result.scheme_id) > 0

    def test__missing_scheme_name__raises_validation_error(self) -> None:
        """Missing scheme_name → ValidationError mentioning 'scheme_name'."""
        with pytest.raises(ValidationError) as exc_info:
            load_kaggle_row({"eligibility": "some text"})
        assert "scheme_name" in str(exc_info.value)

    def test__missing_eligibility__raises_validation_error(self) -> None:
        """Missing eligibility → ValidationError mentioning 'eligibility'."""
        with pytest.raises(ValidationError) as exc_info:
            load_kaggle_row({"scheme_name": "PM-SYM"})
        assert "eligibility" in str(exc_info.value)

    def test__empty_eligibility_string__raises_validation_error(self) -> None:
        """Empty eligibility string → ValidationError."""
        with pytest.raises(ValidationError):
            load_kaggle_row({"scheme_name": "PM-SYM", "eligibility": ""})

    def test__bytes_in_eligibility__raises_validation_error(self) -> None:
        """Invalid bytes in eligibility → ValidationError indicating encoding error."""
        with pytest.raises(ValidationError) as exc_info:
            load_kaggle_row({"scheme_name": "PM-SYM", "eligibility": b"\xff\xfe"})
        assert "encoding" in str(exc_info.value).lower() or "eligibility" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Section 7: Integration — Full Sourcing Pipeline
# ---------------------------------------------------------------------------


class TestSourcingPipeline:
    async def test__pmkisan__produces_verified_parse_input(self) -> None:
        """Full pipeline for PMKISAN → valid ParseInput with ACTIVE status."""
        from src.data_sourcing import ParseInput, run_sourcing_pipeline  # type: ignore[import]

        with patch(
            "src.data_sourcing.fetch_tier1_text",
            new_callable=AsyncMock,
            return_value="All landholding farmer families are eligible",
        ):
            with patch(
                "src.data_sourcing.download_tier2_pdf",
                new_callable=AsyncMock,
                return_value=Path("/tmp/PMKISAN.pdf"),
            ):
                from datetime import date, timedelta

                recent = (date.today() - timedelta(days=30)).isoformat()
                with patch(
                    "src.data_sourcing.classify_active_dormant",
                    return_value=SchemeStatus.ACTIVE,
                ):
                    parse_input, status = await run_sourcing_pipeline("PMKISAN")

        assert isinstance(parse_input, ParseInput)
        assert len(parse_input.raw_text) > 0
        assert status == SchemeStatus.ACTIVE

    async def test__tier1_diverges_10_percent__tier1_rejected(self) -> None:
        """Tier-1/Tier-2 divergence >10% → Tier-1 rejected, Tier-2 used."""
        from src.data_sourcing import run_sourcing_pipeline  # type: ignore[import]

        with patch(
            "src.data_sourcing.fetch_tier1_text",
            new_callable=AsyncMock,
            return_value="Annual household income must be below ₹2,00,000",
        ):
            with patch(
                "src.data_sourcing._extract_pdf_text",
                new_callable=AsyncMock,
                return_value="Annual household income must be below ₹2,50,000 as per revised notification",
            ):
                with patch(
                    "src.data_sourcing.download_tier2_pdf",
                    new_callable=AsyncMock,
                    return_value=Path("/tmp/PMKISAN.pdf"),
                ):
                    with patch(
                        "src.data_sourcing.classify_active_dormant",
                        return_value=SchemeStatus.ACTIVE,
                    ):
                        parse_input, _ = await run_sourcing_pipeline("PMKISAN")

        # Tier-2 text is longer (has "revised notification"); Tier-2 must be used
        assert "2,50,000" in parse_input.raw_text or "2.5" in parse_input.raw_text

    async def test__tier1_unavailable__falls_back_to_tier2(self) -> None:
        """myScheme 503 → pipeline falls back to Tier-2; no exception propagates."""
        from src.data_sourcing import run_sourcing_pipeline  # type: ignore[import]

        with patch(
            "src.data_sourcing.fetch_tier1_text",
            new_callable=AsyncMock,
            side_effect=NetworkError("tier1_unavailable"),
        ):
            with patch(
                "src.data_sourcing.download_tier2_pdf",
                new_callable=AsyncMock,
                return_value=Path("/tmp/PMKISAN.pdf"),
            ):
                with patch(
                    "src.data_sourcing._extract_pdf_text",
                    new_callable=AsyncMock,
                    return_value="All landholding farmer families are eligible",
                ):
                    with patch(
                        "src.data_sourcing.classify_active_dormant",
                        return_value=SchemeStatus.ACTIVE,
                    ):
                        parse_input, _ = await run_sourcing_pipeline("PMKISAN")

        assert len(parse_input.raw_text) > 0

    async def test__scanned_pdf_detected__routed_to_ocr(self) -> None:
        """Scanned (image-only) PDF → run_ocr is called; ocr_used flag set."""
        from src.data_sourcing import run_sourcing_pipeline  # type: ignore[import]

        with patch(
            "src.data_sourcing.fetch_tier1_text",
            new_callable=AsyncMock,
            side_effect=NetworkError("unavailable"),
        ):
            with patch(
                "src.data_sourcing.download_tier2_pdf",
                new_callable=AsyncMock,
                return_value=Path("/tmp/PMKISAN.pdf"),
            ):
                with patch(
                    "src.data_sourcing._has_text_layer",
                    return_value=False,
                ):
                    with patch(
                        "src.data_sourcing.run_ocr",
                        new_callable=AsyncMock,
                        return_value="Farmers owning land are eligible",
                    ) as mock_ocr:
                        with patch(
                            "src.data_sourcing.classify_active_dormant",
                            return_value=SchemeStatus.ACTIVE,
                        ):
                            parse_input, _ = await run_sourcing_pipeline("PMKISAN")

        mock_ocr.assert_called_once()
        assert parse_input.ocr_used is True
