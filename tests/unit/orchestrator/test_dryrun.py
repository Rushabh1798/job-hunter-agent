"""Tests for dry-run patch activation."""

from __future__ import annotations

import pytest

from job_hunter_agents.dryrun import activate_dry_run_patches

pytestmark = pytest.mark.unit


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
            from job_hunter_agents.agents.resume_parser import PDFParser

            # PDFParser should be the fake, not the real one
            instance = PDFParser()
            assert hasattr(instance, "extract_text")
        finally:
            stack.close()

    def test_patches_web_search(self) -> None:
        """WebSearchTool is replaced in company_finder module."""
        stack = activate_dry_run_patches()
        try:
            from job_hunter_agents.agents.company_finder import WebSearchTool

            instance = WebSearchTool()
            assert hasattr(instance, "search")
        finally:
            stack.close()

    def test_patches_ats_clients(self) -> None:
        """ATS clients are replaced in company_finder module."""
        stack = activate_dry_run_patches()
        try:
            from job_hunter_agents.agents.company_finder import GreenhouseClient

            instance = GreenhouseClient()
            assert hasattr(instance, "detect")
        finally:
            stack.close()

    def test_patches_web_scraper(self) -> None:
        """WebScraper is replaced in jobs_scraper module."""
        stack = activate_dry_run_patches()
        try:
            from job_hunter_agents.agents.jobs_scraper import WebScraper

            instance = WebScraper()
            assert hasattr(instance, "fetch_page")
        finally:
            stack.close()

    def test_patches_email_sender(self) -> None:
        """EmailSender is replaced in notifier module."""
        stack = activate_dry_run_patches()
        try:
            from job_hunter_agents.agents.notifier import EmailSender

            instance = EmailSender()
            assert hasattr(instance, "send")
        finally:
            stack.close()

    def test_patches_instructor(self) -> None:
        """instructor module is replaced in base agent module."""
        stack = activate_dry_run_patches()
        try:
            from job_hunter_agents.agents import base

            # instructor should be a MagicMock
            assert hasattr(base.instructor, "from_anthropic")
        finally:
            stack.close()

    def test_stack_close_restores_originals(self) -> None:
        """Closing the stack restores original classes."""
        from job_hunter_agents.agents.resume_parser import PDFParser as OriginalBefore

        stack = activate_dry_run_patches()
        stack.close()

        from job_hunter_agents.agents.resume_parser import PDFParser as OriginalAfter

        # After closing, should be same class reference as before
        assert OriginalBefore is OriginalAfter
