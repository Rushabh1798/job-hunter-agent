"""Tests for dry-run patch activation."""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from job_hunter_agents.dryrun import activate_dry_run_patches, activate_integration_patches

pytestmark = pytest.mark.unit


def _get_attr(module_path: str, attr_name: str) -> Any:  # noqa: ANN401
    """Import a module and return an attribute by name (bypasses mypy export checks)."""
    mod = importlib.import_module(module_path)
    return getattr(mod, attr_name)


class TestActivateDryRunPatches:
    """Test that activate_dry_run_patches replaces all external I/O."""

    def test_returns_exit_stack(self) -> None:
        """activate_dry_run_patches returns an ExitStack."""
        from contextlib import ExitStack

        stack = activate_dry_run_patches()
        assert isinstance(stack, ExitStack)
        stack.close()

    def test_patches_pdf_parser(self) -> None:
        """PDFParser is replaced in resume_parser module."""
        stack = activate_dry_run_patches()
        try:
            cls = _get_attr("job_hunter_agents.agents.resume_parser", "PDFParser")
            instance = cls()
            assert hasattr(instance, "extract_text")
        finally:
            stack.close()

    def test_patches_web_search(self) -> None:
        """create_search_provider factory is replaced in company_finder module."""
        from tests.mocks.mock_tools import FakeWebSearchTool

        stack = activate_dry_run_patches()
        try:
            factory = _get_attr("job_hunter_agents.agents.company_finder", "create_search_provider")
            # Factory was patched to a lambda that returns FakeWebSearchTool()
            instance = factory(None)
            assert isinstance(instance, FakeWebSearchTool)
        finally:
            stack.close()

    def test_patches_ats_clients(self) -> None:
        """ATS clients are replaced in company_finder module."""
        stack = activate_dry_run_patches()
        try:
            cls = _get_attr("job_hunter_agents.agents.company_finder", "GreenhouseClient")
            instance = cls()
            assert hasattr(instance, "detect")
        finally:
            stack.close()

    def test_patches_web_scraper(self) -> None:
        """create_page_scraper factory is replaced in jobs_scraper module."""
        from tests.mocks.mock_tools import FakeWebScraper

        stack = activate_dry_run_patches()
        try:
            factory = _get_attr("job_hunter_agents.agents.jobs_scraper", "create_page_scraper")
            # Factory was patched to FakeWebScraper (callable class)
            instance = factory()
            assert isinstance(instance, FakeWebScraper)
        finally:
            stack.close()

    def test_patches_email_sender(self) -> None:
        """EmailSender is replaced in notifier module."""
        stack = activate_dry_run_patches()
        try:
            cls = _get_attr("job_hunter_agents.agents.notifier", "EmailSender")
            instance = cls()
            assert hasattr(instance, "send")
        finally:
            stack.close()

    def test_patches_llm_client(self) -> None:
        """BaseAgent._build_llm_client is patched to return a fake client."""
        from llm_gateway import LLMClient  # type: ignore[import-untyped]

        stack = activate_dry_run_patches()
        try:
            from job_hunter_agents.agents.base import BaseAgent

            client = BaseAgent._build_llm_client(None)  # type: ignore[arg-type]
            assert isinstance(client, LLMClient)
        finally:
            stack.close()

    def test_stack_close_restores_originals(self) -> None:
        """Closing the stack restores original classes."""
        original_before = _get_attr("job_hunter_agents.agents.resume_parser", "PDFParser")

        stack = activate_dry_run_patches()
        stack.close()

        original_after = _get_attr("job_hunter_agents.agents.resume_parser", "PDFParser")

        assert original_before is original_after


class TestActivateIntegrationPatches:
    """Test that activate_integration_patches replaces only LLM + email + PDF."""

    def test_returns_exit_stack(self) -> None:
        """activate_integration_patches returns an ExitStack."""
        from contextlib import ExitStack

        stack = activate_integration_patches()
        assert isinstance(stack, ExitStack)
        stack.close()

    def test_patches_llm_client(self) -> None:
        """BaseAgent._build_llm_client is patched to return a fake client."""
        from llm_gateway import LLMClient  # type: ignore[import-untyped]

        stack = activate_integration_patches()
        try:
            from job_hunter_agents.agents.base import BaseAgent

            client = BaseAgent._build_llm_client(None)  # type: ignore[arg-type]
            assert isinstance(client, LLMClient)
        finally:
            stack.close()

    def test_patches_pdf_parser(self) -> None:
        """PDFParser is replaced in resume_parser module."""
        stack = activate_integration_patches()
        try:
            cls = _get_attr("job_hunter_agents.agents.resume_parser", "PDFParser")
            instance = cls()
            assert hasattr(instance, "extract_text")
        finally:
            stack.close()

    def test_patches_email_sender(self) -> None:
        """EmailSender is replaced in notifier module."""
        stack = activate_integration_patches()
        try:
            cls = _get_attr("job_hunter_agents.agents.notifier", "EmailSender")
            instance = cls()
            assert hasattr(instance, "send")
        finally:
            stack.close()
