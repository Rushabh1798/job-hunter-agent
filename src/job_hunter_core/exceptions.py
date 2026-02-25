"""Custom exception hierarchy for job-hunter-agent."""

from __future__ import annotations


class JobHunterError(Exception):
    """Base exception for all job-hunter-agent errors."""


class CostLimitExceededError(JobHunterError):
    """Raised when estimated run cost exceeds the configured limit."""


class FatalAgentError(JobHunterError):
    """Raised when an agent encounters an unrecoverable error."""


class ScannedPDFError(JobHunterError):
    """Raised when a PDF has no text layer (scanned/image-only)."""


class EncryptedPDFError(JobHunterError):
    """Raised when a PDF is password-protected."""


class InvalidFileError(JobHunterError):
    """Raised when the input file is not a valid PDF."""


class ATSDetectionError(JobHunterError):
    """Raised when ATS type cannot be determined."""


class ScrapingError(JobHunterError):
    """Raised when page scraping fails after all fallback strategies."""


class EmbeddingError(JobHunterError):
    """Raised when text embedding fails."""


class EmailDeliveryError(JobHunterError):
    """Raised when email sending fails."""


class CheckpointError(JobHunterError):
    """Raised when checkpoint save/load fails."""


class TemporalConnectionError(JobHunterError):
    """Raised when Temporal server is unreachable or connection fails."""
