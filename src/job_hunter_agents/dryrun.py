"""Dry-run patch activation — replaces all external I/O with fakes."""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch


def activate_dry_run_patches() -> ExitStack:
    """Activate all dry-run patches and return an ExitStack to close them.

    Patches tool constructors at their import locations so agents
    instantiate fakes instead of real clients. The caller must call
    ``stack.close()`` (or use ``with`` statement) when done.

    Shared by both CLI ``--dry-run`` and pipeline-logic integration tests.
    """
    # Lazy import to avoid circular deps and test-only deps in production
    from tests.mocks.mock_llm import FakeInstructorClient
    from tests.mocks.mock_tools import (
        FakeAshbyClient,
        FakeEmailSender,
        FakeGreenhouseClient,
        FakeLeverClient,
        FakePDFParser,
        FakeWebScraper,
        FakeWebSearchTool,
        FakeWorkdayClient,
    )

    stack = ExitStack()

    # --- Resume parser: PDFParser ---
    stack.enter_context(
        patch(
            "job_hunter_agents.agents.resume_parser.PDFParser",
            FakePDFParser,
        )
    )

    # --- Company finder: search via factory, ATS clients direct ---
    stack.enter_context(
        patch(
            "job_hunter_agents.agents.company_finder.create_search_provider",
            lambda settings: FakeWebSearchTool(),
        )
    )
    stack.enter_context(
        patch(
            "job_hunter_agents.agents.company_finder.GreenhouseClient",
            FakeGreenhouseClient,
        )
    )
    stack.enter_context(
        patch(
            "job_hunter_agents.agents.company_finder.LeverClient",
            FakeLeverClient,
        )
    )
    stack.enter_context(
        patch(
            "job_hunter_agents.agents.company_finder.AshbyClient",
            FakeAshbyClient,
        )
    )
    stack.enter_context(
        patch(
            "job_hunter_agents.agents.company_finder.WorkdayClient",
            FakeWorkdayClient,
        )
    )

    # --- Jobs scraper: ATS clients + scraper via factory ---
    stack.enter_context(
        patch(
            "job_hunter_agents.agents.jobs_scraper.GreenhouseClient",
            FakeGreenhouseClient,
        )
    )
    stack.enter_context(
        patch(
            "job_hunter_agents.agents.jobs_scraper.LeverClient",
            FakeLeverClient,
        )
    )
    stack.enter_context(
        patch(
            "job_hunter_agents.agents.jobs_scraper.AshbyClient",
            FakeAshbyClient,
        )
    )
    stack.enter_context(
        patch(
            "job_hunter_agents.agents.jobs_scraper.WorkdayClient",
            FakeWorkdayClient,
        )
    )
    stack.enter_context(
        patch(
            "job_hunter_agents.agents.jobs_scraper.create_page_scraper",
            FakeWebScraper,
        )
    )

    # --- Notifier: EmailSender ---
    stack.enter_context(
        patch(
            "job_hunter_agents.agents.notifier.EmailSender",
            FakeEmailSender,
        )
    )

    # --- Base agent: AsyncAnthropic + instructor ---
    # Prevent real API client creation
    stack.enter_context(
        patch(
            "job_hunter_agents.agents.base.AsyncAnthropic",
            MagicMock,
        )
    )

    # Make instructor.from_anthropic() return FakeInstructorClient
    fake_instructor = MagicMock()
    fake_instructor.from_anthropic.return_value = FakeInstructorClient()
    stack.enter_context(
        patch(
            "job_hunter_agents.agents.base.instructor",
            fake_instructor,
        )
    )

    return stack


def activate_integration_patches() -> ExitStack:
    """Activate minimal patches for integration tests — LLM + email + PDF only.

    Integration tests use real search (DuckDuckGo via settings), real scraping
    (crawl4ai), and real ATS clients (public APIs). Only the LLM, email, and
    PDF parser are mocked.

    The caller must call ``stack.close()`` (or use ``with`` statement).
    """
    from tests.mocks.mock_llm import FakeInstructorClient
    from tests.mocks.mock_tools import (
        FakeEmailSender,
        FakePDFParser,
    )

    stack = ExitStack()

    # --- Resume parser: PDFParser ---
    stack.enter_context(
        patch(
            "job_hunter_agents.agents.resume_parser.PDFParser",
            FakePDFParser,
        )
    )

    # --- Notifier: EmailSender ---
    stack.enter_context(
        patch(
            "job_hunter_agents.agents.notifier.EmailSender",
            FakeEmailSender,
        )
    )

    # --- Base agent: AsyncAnthropic + instructor ---
    stack.enter_context(
        patch(
            "job_hunter_agents.agents.base.AsyncAnthropic",
            MagicMock,
        )
    )

    fake_instructor = MagicMock()
    fake_instructor.from_anthropic.return_value = FakeInstructorClient()
    stack.enter_context(
        patch(
            "job_hunter_agents.agents.base.instructor",
            fake_instructor,
        )
    )

    return stack
