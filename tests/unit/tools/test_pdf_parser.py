"""Tests for PDF parser tool."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from job_hunter_agents.tools.pdf_parser import PDFParser
from job_hunter_core.exceptions import InvalidFileError


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
