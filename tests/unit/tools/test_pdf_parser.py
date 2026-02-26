"""Tests for PDF parser tool."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from job_hunter_agents.tools.pdf_parser import PDFParser
from job_hunter_core.exceptions import EncryptedPDFError, InvalidFileError, ScannedPDFError


@pytest.mark.unit
class TestPDFParser:
    """Test PDFParser validation and fallback chain."""

    @pytest.mark.asyncio
    async def test_nonexistent_file_raises(self) -> None:
        """Non-existent file raises InvalidFileError."""
        parser = PDFParser()
        with pytest.raises(InvalidFileError, match="File not found"):
            await parser.extract_text(Path("/nonexistent/resume.pdf"))

    @pytest.mark.asyncio
    async def test_non_pdf_extension_raises(self) -> None:
        """Non-PDF file extension raises InvalidFileError."""
        parser = PDFParser()
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            f.write(b"not a pdf")
            path = Path(f.name)
        try:
            with pytest.raises(InvalidFileError, match="Expected PDF"):
                await parser.extract_text(path)
        finally:
            os.unlink(str(path))

    def test_validate_file_exists(self) -> None:
        """Validation passes for existing PDF file."""
        parser = PDFParser()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 test content")
            path = Path(f.name)
        try:
            parser._validate_file(path)
        finally:
            os.unlink(str(path))

    def test_check_size_warns_for_large_file(self, tmp_path: Path) -> None:
        """_check_size warns if PDF > MAX_PDF_SIZE_MB."""
        parser = PDFParser()
        large_pdf = tmp_path / "large.pdf"
        large_pdf.write_bytes(b"0" * (11 * 1024 * 1024))
        with patch("job_hunter_agents.tools.pdf_parser.logger") as mock_logger:
            parser._check_size(large_pdf)
            mock_logger.warning.assert_called_once()

    def test_check_size_no_warning_for_small_file(self, tmp_path: Path) -> None:
        """_check_size does not warn for small PDF."""
        parser = PDFParser()
        small_pdf = tmp_path / "small.pdf"
        small_pdf.write_bytes(b"0" * 100)
        with patch("job_hunter_agents.tools.pdf_parser.logger") as mock_logger:
            parser._check_size(small_pdf)
            mock_logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_pdfplumber_success(self, tmp_path: Path) -> None:
        """extract_text returns pdfplumber result when text > 50 chars."""
        parser = PDFParser()
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        long_text = "A" * 60
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = long_text
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("pdfplumber.open", return_value=mock_pdf):
            result = await parser.extract_text(pdf_path)

        assert result == long_text

    @pytest.mark.asyncio
    async def test_pdfplumber_short_text_falls_to_pypdf(self, tmp_path: Path) -> None:
        """extract_text falls to pypdf when pdfplumber returns short text."""
        parser = PDFParser()
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        long_text = "B" * 60

        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "short"
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_reader = MagicMock()
        mock_reader.is_encrypted = False
        mock_pypdf_page = MagicMock()
        mock_pypdf_page.extract_text.return_value = long_text
        mock_reader.pages = [mock_pypdf_page]

        with (
            patch("pdfplumber.open", return_value=mock_pdf),
            patch("pypdf.PdfReader", return_value=mock_reader),
        ):
            result = await parser.extract_text(pdf_path)

        assert result == long_text

    @pytest.mark.asyncio
    async def test_pdfplumber_encrypted_raises(self, tmp_path: Path) -> None:
        """Encrypted PDF in pdfplumber raises EncryptedPDFError."""
        parser = PDFParser()
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        with patch("pdfplumber.open", side_effect=Exception("password required")):
            with pytest.raises(EncryptedPDFError, match="password-protected"):
                await parser._try_pdfplumber(pdf_path)

    @pytest.mark.asyncio
    async def test_pdfplumber_generic_error_returns_none(self, tmp_path: Path) -> None:
        """Non-password pdfplumber error returns None for fallback."""
        parser = PDFParser()
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        with patch("pdfplumber.open", side_effect=RuntimeError("corrupted")):
            result = await parser._try_pdfplumber(pdf_path)

        assert result is None

    @pytest.mark.asyncio
    async def test_pypdf_encrypted_raises(self, tmp_path: Path) -> None:
        """Encrypted PDF in pypdf raises EncryptedPDFError."""
        parser = PDFParser()
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        mock_reader = MagicMock()
        mock_reader.is_encrypted = True

        with patch("pypdf.PdfReader", return_value=mock_reader):
            with pytest.raises(EncryptedPDFError, match="password-protected"):
                await parser._try_pypdf(pdf_path)

    @pytest.mark.asyncio
    async def test_pypdf_generic_error_returns_none(self, tmp_path: Path) -> None:
        """Non-password pypdf error returns None."""
        parser = PDFParser()
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        with patch("pypdf.PdfReader", side_effect=RuntimeError("bad")):
            result = await parser._try_pypdf(pdf_path)

        assert result is None

    @pytest.mark.asyncio
    async def test_pypdf_multi_page_extraction(self, tmp_path: Path) -> None:
        """pypdf extracts text from multiple pages joined by newlines."""
        parser = PDFParser()
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        mock_reader = MagicMock()
        mock_reader.is_encrypted = False
        page1 = MagicMock()
        page1.extract_text.return_value = "A" * 30
        page2 = MagicMock()
        page2.extract_text.return_value = "B" * 30
        mock_reader.pages = [page1, page2]

        with patch("pypdf.PdfReader", return_value=mock_reader):
            result = await parser._try_pypdf(pdf_path)

        assert result == ("A" * 30) + "\n\n" + ("B" * 30)

    @pytest.mark.asyncio
    async def test_both_extractors_fail_raises_scanned(self, tmp_path: Path) -> None:
        """ScannedPDFError raised when both extractors return empty text."""
        parser = PDFParser()
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        with (
            patch.object(parser, "_try_pdfplumber", new_callable=AsyncMock, return_value=None),
            patch.object(parser, "_try_pypdf", new_callable=AsyncMock, return_value=None),
        ):
            with pytest.raises(ScannedPDFError):
                await parser.extract_text(pdf_path)

    @pytest.mark.asyncio
    async def test_pdfplumber_page_with_none_text(self, tmp_path: Path) -> None:
        """pdfplumber pages that return None text are skipped."""
        parser = PDFParser()
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        mock_pdf = MagicMock()
        page1 = MagicMock()
        page1.extract_text.return_value = None
        page2 = MagicMock()
        page2.extract_text.return_value = "C" * 60
        mock_pdf.pages = [page1, page2]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("pdfplumber.open", return_value=mock_pdf):
            result = await parser._try_pdfplumber(pdf_path)

        assert result == "C" * 60
