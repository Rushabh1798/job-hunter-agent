"""Dry-run patch activation — replaces all external I/O with fakes."""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import patch


def _build_fake_llm_client() -> object:
    """Build a FakeLLMProvider-backed LLMClient for dry-run mode."""
    from llm_gateway import (  # type: ignore[import-untyped]
        FakeLLMProvider,
        GatewayConfig,
        LLMClient,
    )

    from tests.mocks.mock_llm import fixture_response_factory

    fake_provider = FakeLLMProvider(response_factory=fixture_response_factory)
    return LLMClient(
        config=GatewayConfig(provider="fake", trace_enabled=False, log_format="console"),
        provider_instance=fake_provider,
    )


def activate_dry_run_patches() -> ExitStack:
    """Activate all dry-run patches and return an ExitStack to close them.

    Patches tool constructors at their import locations so agents
    instantiate fakes instead of real clients. The caller must call
    ``stack.close()`` (or use ``with`` statement) when done.

    Shared by both CLI ``--dry-run`` and pipeline-logic integration tests.
    """
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

    # --- Base agent: LLM client via llm-gateway ---
    fake_client = _build_fake_llm_client()
    stack.enter_context(
        patch(
            "job_hunter_agents.agents.base.BaseAgent._build_llm_client",
            return_value=fake_client,
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

    # --- Base agent: LLM client via llm-gateway ---
    fake_client = _build_fake_llm_client()
    stack.enter_context(
        patch(
            "job_hunter_agents.agents.base.BaseAgent._build_llm_client",
            return_value=fake_client,
        )
    )

    return stack
