"""Live E2E tests — real LLM, search, and scraping APIs.

Requires API keys in .env: JH_ANTHROPIC_API_KEY, JH_TAVILY_API_KEY.
Run with: uv run pytest -m live
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from job_hunter_agents.orchestrator.pipeline import Pipeline
from job_hunter_core.config.settings import Settings
from job_hunter_core.models.run import RunConfig

pytestmark = pytest.mark.live

FIXTURE_RESUME = Path(__file__).parent.parent / "fixtures" / "sample_resume.pdf"

_has_anthropic_key = bool(os.environ.get("JH_ANTHROPIC_API_KEY"))
_has_tavily_key = bool(os.environ.get("JH_TAVILY_API_KEY"))

skip_no_api_keys = pytest.mark.skipif(
    not (_has_anthropic_key and _has_tavily_key),
    reason="Live tests require JH_ANTHROPIC_API_KEY and JH_TAVILY_API_KEY",
)


@skip_no_api_keys
class TestFullPipelineLive:
    """Full pipeline with real APIs (requires .env with API keys)."""

    async def test_live_pipeline_completes(self, tmp_path: Path) -> None:
        """Pipeline completes with real APIs, company_limit=1."""
        settings = Settings()  # type: ignore[call-arg]
        settings.output_dir = tmp_path / "output"
        settings.checkpoint_dir = tmp_path / "checkpoints"
        settings.checkpoint_enabled = True

        config = RunConfig(
            resume_path=FIXTURE_RESUME,
            preferences_text="Python backend remote roles at AI startups",
            dry_run=False,
            company_limit=1,
        )

        pipeline = Pipeline(settings)
        result = await pipeline.run(config)

        assert result.status in ("success", "partial")
        assert result.estimated_cost_usd < 2.0, (
            f"Safety guardrail: cost ${result.estimated_cost_usd:.2f} exceeds $2.00"
        )

    async def test_live_pipeline_cost_guardrail(self, tmp_path: Path) -> None:
        """Verify cost tracking works with real API calls."""
        settings = Settings()  # type: ignore[call-arg]
        settings.output_dir = tmp_path / "output"
        settings.checkpoint_dir = tmp_path / "checkpoints"
        settings.max_cost_per_run_usd = 2.0  # Tight limit for tests

        config = RunConfig(
            resume_path=FIXTURE_RESUME,
            preferences_text="Python backend remote roles",
            dry_run=False,
            company_limit=1,
        )

        pipeline = Pipeline(settings)
        result = await pipeline.run(config)

        assert result.total_tokens_used > 0
        assert result.estimated_cost_usd > 0
        assert result.estimated_cost_usd < 2.0
