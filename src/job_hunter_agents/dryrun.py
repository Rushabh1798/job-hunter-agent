"""Dry-run patch activation — replaces all external I/O with fakes."""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch


def activate_dry_run_patches() -> ExitStack:
    """Activate all dry-run patches and return an ExitStack to close them.

    Patches tool constructors at their import locations so agents
    instantiate fakes instead of real clients. The caller must call
    ``stack.close()`` (or use ``with`` statement) when done.

    Shared by both integration tests and CLI ``--dry-run``.
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

    # --- Company finder: WebSearchTool + ATS clients ---
    stack.enter_context(
        patch(
            "job_hunter_agents.agents.company_finder.WebSearchTool",
            FakeWebSearchTool,
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

    # --- Jobs scraper: ATS clients + WebScraper ---
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
            "job_hunter_agents.agents.jobs_scraper.WebScraper",
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
