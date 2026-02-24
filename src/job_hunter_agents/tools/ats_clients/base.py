"""Base ATS client abstract class."""

from __future__ import annotations

from abc import ABC, abstractmethod

from job_hunter_core.models.company import Company


class BaseATSClient(ABC):
    """Abstract base class for Applicant Tracking System clients."""

    @abstractmethod
    async def detect(self, career_url: str) -> bool:
        """Return True if this ATS type is detected at the given URL."""
        ...

    @abstractmethod
    async def fetch_jobs(self, company: Company) -> list[dict]:  # type: ignore[type-arg]
        """Return raw job dicts from the ATS API."""
        ...
