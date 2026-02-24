"""PDF text extraction with fallback chain: docling -> pdfplumber -> pypdf."""

from __future__ import annotations

from pathlib import Path

import structlog

from job_hunter_core.exceptions import EncryptedPDFError, InvalidFileError, ScannedPDFError

logger = structlog.get_logger()

MAX_PDF_SIZE_MB = 10


class PDFParser:
    """Extract text from PDF files with multiple fallback strategies."""

    async def extract_text(self, path: Path) -> str:
        """Extract text from a PDF file.

        Tries docling first, then pdfplumber, then pypdf.

        Raises:
            InvalidFileError: If the file is not a PDF.
            EncryptedPDFError: If the PDF is password-protected.
            ScannedPDFError: If the PDF has no text layer.
        """
        self._validate_file(path)
        self._check_size(path)

        text = await self._try_pdfplumber(path)
        if text and len(text.strip()) > 50:
            return text

        text = await self._try_pypdf(path)
        if text and len(text.strip()) > 50:
            return text

        msg = f"PDF appears to be scanned/image-only with no extractable text: {path}"
        raise ScannedPDFError(msg)

    def _validate_file(self, path: Path) -> None:
        """Validate that the file exists and is a PDF."""
        if not path.exists():
            msg = f"File not found: {path}"
            raise InvalidFileError(msg)
        if path.suffix.lower() != ".pdf":
            msg = f"Expected PDF file, got: {path.suffix}"
            raise InvalidFileError(msg)

    def _check_size(self, path: Path) -> None:
        """Warn if PDF is larger than MAX_PDF_SIZE_MB."""
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > MAX_PDF_SIZE_MB:
            logger.warning("large_pdf", path=str(path), size_mb=round(size_mb, 1))

    async def _try_pdfplumber(self, path: Path) -> str | None:
        """Try extracting text with pdfplumber."""
        try:
            import asyncio

            import pdfplumber

            def _extract() -> str:
                pages_text: list[str] = []
                with pdfplumber.open(str(path)) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            pages_text.append(text)
                return "\n\n".join(pages_text)

            return await asyncio.to_thread(_extract)
        except Exception as e:
            if "password" in str(e).lower() or "encrypted" in str(e).lower():
                msg = f"PDF is password-protected: {path}"
                raise EncryptedPDFError(msg) from e
            logger.debug("pdfplumber_fallback", error=str(e))
            return None

    async def _try_pypdf(self, path: Path) -> str | None:
        """Try extracting text with pypdf (lightweight fallback)."""
        try:
            import asyncio

            from pypdf import PdfReader

            def _extract() -> str:
                reader = PdfReader(str(path))
                if reader.is_encrypted:
                    msg = f"PDF is password-protected: {path}"
                    raise EncryptedPDFError(msg)
                pages_text: list[str] = []
                for page in reader.pages:
                    text = page.extract_text()
                    if text:
                        pages_text.append(text)
                return "\n\n".join(pages_text)

            return await asyncio.to_thread(_extract)
        except EncryptedPDFError:
            raise
        except Exception as e:
            logger.debug("pypdf_fallback", error=str(e))
            return None
