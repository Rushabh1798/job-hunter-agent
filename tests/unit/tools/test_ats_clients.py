"""Tests for ATS client detection and slug extraction."""

from __future__ import annotations

import pytest

from job_hunter_agents.tools.ats_clients.ashby import AshbyClient
from job_hunter_agents.tools.ats_clients.greenhouse import GreenhouseClient
from job_hunter_agents.tools.ats_clients.lever import LeverClient
from job_hunter_agents.tools.ats_clients.workday import WorkdayClient


@pytest.mark.unit
class TestGreenhouseClient:
    """Test Greenhouse ATS detection."""

    @pytest.mark.asyncio
    async def test_detect_greenhouse_url(self) -> None:
        """Detects Greenhouse board URLs."""
        client = GreenhouseClient()
        assert await client.detect("https://boards.greenhouse.io/stripe") is True

    @pytest.mark.asyncio
    async def test_detect_non_greenhouse(self) -> None:
        """Does not match non-Greenhouse URLs."""
        client = GreenhouseClient()
        assert await client.detect("https://stripe.com/careers") is False

    def test_extract_slug(self) -> None:
        """Extracts slug from Greenhouse URL."""
        client = GreenhouseClient()
        assert client._extract_slug("https://boards.greenhouse.io/stripe") == "stripe"

    def test_extract_slug_no_match(self) -> None:
        """Returns None for non-Greenhouse URL."""
        client = GreenhouseClient()
        assert client._extract_slug("https://example.com") is None


@pytest.mark.unit
class TestLeverClient:
    """Test Lever ATS detection."""

    @pytest.mark.asyncio
    async def test_detect_lever_url(self) -> None:
        """Detects Lever URLs."""
        client = LeverClient()
        assert await client.detect("https://jobs.lever.co/figma") is True

    @pytest.mark.asyncio
    async def test_detect_non_lever(self) -> None:
        """Does not match non-Lever URLs."""
        client = LeverClient()
        assert await client.detect("https://figma.com/careers") is False


@pytest.mark.unit
class TestAshbyClient:
    """Test Ashby ATS detection."""

    @pytest.mark.asyncio
    async def test_detect_ashby_url(self) -> None:
        """Detects Ashby URLs."""
        client = AshbyClient()
        assert await client.detect("https://jobs.ashbyhq.com/notion") is True

    @pytest.mark.asyncio
    async def test_detect_non_ashby(self) -> None:
        """Does not match non-Ashby URLs."""
        client = AshbyClient()
        assert await client.detect("https://notion.so/careers") is False


@pytest.mark.unit
class TestWorkdayClient:
    """Test Workday ATS detection."""

    @pytest.mark.asyncio
    async def test_detect_workday_url(self) -> None:
        """Detects Workday URLs."""
        client = WorkdayClient()
        assert await client.detect("https://company.myworkdayjobs.com/en-US") is True

    @pytest.mark.asyncio
    async def test_detect_non_workday(self) -> None:
        """Does not match non-Workday URLs."""
        client = WorkdayClient()
        assert await client.detect("https://company.com/careers") is False
