"""Integration tests with real search (DuckDuckGo), scraping (crawl4ai), and ATS APIs.

Only LLM and email are mocked. Requires:
- Postgres + Redis containers (``make dev``)
- Network access (DuckDuckGo, Greenhouse/Lever/Ashby public APIs)
- Playwright Chromium (``uv run playwright install chromium``)
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path

import pytest

from job_hunter_agents.orchestrator.pipeline import Pipeline
from job_hunter_core.config.settings import Settings
from job_hunter_core.models.run import RunConfig

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.network,
    pytest.mark.asyncio(loop_scope="session"),
]

FIXTURE_RESUME = Path(__file__).parent.parent / "fixtures" / "sample_resume.pdf"


class TestPipelineRealScraping:
    """Pipeline with real search (DuckDuckGo), real scraping (crawl4ai), real ATS, mocked LLM."""

    async def test_real_ats_scraping(
        self,
        integration_patches: ExitStack,
        pipeline_tracing: object,
        real_settings: Settings,
    ) -> None:
        """Pipeline discovers career page via DuckDuckGo, scrapes real page via crawl4ai."""
        config = RunConfig(
            resume_path=FIXTURE_RESUME,
            preferences_text="Python remote roles at startups",
            dry_run=True,
            company_limit=1,
        )
        pipeline = Pipeline(real_settings)
        result = await pipeline.run(config)

        assert result.status in ("success", "partial")
        assert result.companies_attempted >= 1
        assert result.jobs_scraped >= 1
        assert result.jobs_scored >= 1

        # Verify output files are saved to disk with real paths
        assert len(result.output_files) >= 1, f"Expected output files, got: {result.output_files}"
        for fpath in result.output_files:
            p = Path(fpath)
            assert p.exists(), f"Output file missing: {fpath}"  # noqa: ASYNC240
            assert p.stat().st_size > 0, f"Output file empty: {fpath}"  # noqa: ASYNC240

    async def test_real_scraping_error_resilience(
        self,
        integration_patches: ExitStack,
        pipeline_tracing: object,
        real_settings: Settings,
    ) -> None:
        """Pipeline completes even when some scraping fails."""
        config = RunConfig(
            resume_path=FIXTURE_RESUME,
            preferences_text="Python remote roles",
            dry_run=True,
            company_limit=2,
        )
        pipeline = Pipeline(real_settings)
        result = await pipeline.run(config)

        assert result.status in ("success", "partial")
        assert isinstance(result.errors, list)
        assert result.jobs_scraped >= 1

        # Output files exist and are non-empty
        for fpath in result.output_files:
            p = Path(fpath)
            assert p.exists(), f"Output file missing: {fpath}"  # noqa: ASYNC240
            assert p.stat().st_size > 0, f"Output file empty: {fpath}"  # noqa: ASYNC240
