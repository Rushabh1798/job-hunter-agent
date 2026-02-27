"""Tests for adaptive pipeline discovery loop."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from job_hunter_agents.orchestrator.adaptive_pipeline import AdaptivePipeline
from job_hunter_core.models.candidate import CandidateProfile, SearchPreferences, Skill
from job_hunter_core.models.company import ATSType, CareerPage, Company, CompanyTier
from job_hunter_core.models.job import FitReport, NormalizedJob, ScoredJob
from job_hunter_core.models.run import RunConfig, RunResult
from job_hunter_core.state import PipelineState
from tests.mocks.mock_settings import make_settings


def _make_scored_job(
    company_name: str = "TestCo",
    score: int = 85,
) -> ScoredJob:
    """Create a test scored job."""
    return ScoredJob(
        job=NormalizedJob(
            raw_job_id=uuid4(),
            company_id=uuid4(),
            company_name=company_name,
            title="SWE",
            jd_text="Build things",
            apply_url="https://testco.com/apply",
            content_hash=f"hash-{company_name}-{score}-{uuid4().hex[:6]}",
        ),
        fit_report=FitReport(
            score=score,
            skill_overlap=["Python"],
            skill_gaps=[],
            seniority_match=True,
            location_match=True,
            org_type_match=True,
            summary="Good fit",
            recommendation="good_match",
            confidence=0.8,
        ),
    )


def _make_ready_state() -> PipelineState:
    """Create state with profile and preferences (post-setup)."""
    state = PipelineState(
        config=RunConfig(
            resume_path=Path("/tmp/test.pdf"),
            preferences_text="test",
        )
    )
    state.profile = CandidateProfile(
        name="Jane",
        email="jane@test.com",
        years_of_experience=5.0,
        skills=[Skill(name="Python")],
        raw_text="test",
        content_hash="abc",
    )
    state.preferences = SearchPreferences(raw_text="test")
    return state


@pytest.mark.unit
class TestAdaptivePipelineDiscoveryLoop:
    """Test the _discovery_loop method."""

    @pytest.mark.asyncio
    async def test_single_iteration_meets_target(self) -> None:
        """Loop exits after one iteration when enough unique companies found."""
        settings = make_settings(min_recommended_jobs=2, max_discovery_iterations=3)
        pipeline = AdaptivePipeline(settings)
        state = _make_ready_state()

        # Produce 2 unique companies in first iteration → meets target
        async def fake_step(
            step_name: str, agent_cls: type, state: PipelineState, start: float
        ) -> PipelineState:
            if step_name == "find_companies":
                state.companies = [
                    Company(
                        name="Acme",
                        domain="acme.com",
                        career_page=CareerPage(
                            url="https://acme.com/careers", ats_type=ATSType.UNKNOWN
                        ),
                        tier=CompanyTier.TIER_2,
                    ),
                    Company(
                        name="BetaCo",
                        domain="betaco.com",
                        career_page=CareerPage(
                            url="https://betaco.com/careers", ats_type=ATSType.UNKNOWN
                        ),
                        tier=CompanyTier.TIER_3,
                    ),
                ]
            elif step_name == "score_jobs":
                state.scored_jobs = [
                    _make_scored_job("Acme", 90),
                    _make_scored_job("BetaCo", 85),
                ]
            return state

        with patch.object(pipeline, "_run_agent_step", side_effect=fake_step):
            result = await pipeline._discovery_loop(state, 0.0)

        assert len(result.scored_jobs) >= 2
        assert result.discovery_iteration == 0
        assert "Acme" in result.attempted_company_names
        assert "BetaCo" in result.attempted_company_names

    @pytest.mark.asyncio
    async def test_multiple_iterations_accumulate(self) -> None:
        """Loop runs multiple iterations, accumulating unique companies."""
        settings = make_settings(min_recommended_jobs=3, max_discovery_iterations=3)
        pipeline = AdaptivePipeline(settings)
        state = _make_ready_state()

        call_count = 0

        async def fake_step(
            step_name: str, agent_cls: type, state: PipelineState, start: float
        ) -> PipelineState:
            nonlocal call_count
            if step_name == "find_companies":
                call_count += 1
                state.companies = [
                    Company(
                        name=f"Co{call_count}",
                        domain=f"co{call_count}.com",
                        career_page=CareerPage(
                            url=f"https://co{call_count}.com/careers",
                            ats_type=ATSType.UNKNOWN,
                        ),
                        tier=CompanyTier.TIER_3,
                    )
                ]
            elif step_name == "score_jobs":
                # 1 unique company per iteration
                state.scored_jobs = [
                    _make_scored_job(f"Co{call_count}", 85),
                ]
            return state

        with patch.object(pipeline, "_run_agent_step", side_effect=fake_step):
            result = await pipeline._discovery_loop(state, 0.0)

        # 3 iterations needed: 1 unique company per iteration, target=3
        assert len(result.scored_jobs) >= 3
        assert result.attempted_company_names == {"Co1", "Co2", "Co3"}

    @pytest.mark.asyncio
    async def test_fatal_error_preserves_previous_jobs(self) -> None:
        """Fatal error in find_companies preserves previously scored jobs."""
        settings = make_settings(min_recommended_jobs=10, max_discovery_iterations=2)
        pipeline = AdaptivePipeline(settings)
        state = _make_ready_state()

        iteration = 0

        async def fake_step(
            step_name: str, agent_cls: type, state: PipelineState, start: float
        ) -> PipelineState | RunResult:
            nonlocal iteration
            if step_name == "find_companies":
                iteration += 1
                if iteration == 2:
                    # Fatal on second (last) iteration
                    return state.build_result(status="failed", duration_seconds=1.0)
                state.companies = [
                    Company(
                        name="Co1",
                        domain="co1.com",
                        career_page=CareerPage(
                            url="https://co1.com/careers", ats_type=ATSType.UNKNOWN
                        ),
                    )
                ]
            elif step_name == "score_jobs":
                state.scored_jobs = [_make_scored_job("Co1", 85)]
            return state

        with patch.object(pipeline, "_run_agent_step", side_effect=fake_step):
            result = await pipeline._discovery_loop(state, 0.0)

        # First iteration's job should be preserved
        assert len(result.scored_jobs) == 1

    @pytest.mark.asyncio
    async def test_deduplicates_across_iterations(self) -> None:
        """Same content_hash across iterations is deduplicated."""
        settings = make_settings(min_recommended_jobs=5, max_discovery_iterations=3)
        pipeline = AdaptivePipeline(settings)
        state = _make_ready_state()

        fixed_job = _make_scored_job("Acme", 85)

        async def fake_step(
            step_name: str, agent_cls: type, state: PipelineState, start: float
        ) -> PipelineState:
            if step_name == "find_companies":
                state.companies = [
                    Company(
                        name="Acme",
                        domain="acme.com",
                        career_page=CareerPage(
                            url="https://acme.com/careers", ats_type=ATSType.UNKNOWN
                        ),
                    )
                ]
            elif step_name == "score_jobs":
                # Always return the same job
                state.scored_jobs = [fixed_job]
            return state

        with patch.object(pipeline, "_run_agent_step", side_effect=fake_step):
            result = await pipeline._discovery_loop(state, 0.0)

        # Despite 3 iterations, only 1 unique job
        assert len(result.scored_jobs) == 1

    @pytest.mark.asyncio
    async def test_max_iterations_respected(self) -> None:
        """Loop stops at max_discovery_iterations even if target not met."""
        settings = make_settings(min_recommended_jobs=100, max_discovery_iterations=2)
        pipeline = AdaptivePipeline(settings)
        state = _make_ready_state()

        async def fake_step(
            step_name: str, agent_cls: type, state: PipelineState, start: float
        ) -> PipelineState:
            if step_name == "find_companies":
                state.companies = [
                    Company(
                        name=f"Co{state.discovery_iteration}",
                        domain="co.com",
                        career_page=CareerPage(
                            url="https://co.com/careers", ats_type=ATSType.UNKNOWN
                        ),
                    )
                ]
            elif step_name == "score_jobs":
                state.scored_jobs = [_make_scored_job("Co", 85)]
            return state

        with patch.object(pipeline, "_run_agent_step", side_effect=fake_step):
            result = await pipeline._discovery_loop(state, 0.0)

        # Only ran 2 iterations
        assert result.discovery_iteration == 1  # 0-indexed, second iteration


@pytest.mark.unit
class TestCompanyExclusion:
    """Test that attempted_company_names are passed to company finder."""

    @pytest.mark.asyncio
    async def test_exclusion_merged_in_prompt(self) -> None:
        """Attempted companies are merged into excluded_companies."""
        from job_hunter_agents.agents.company_finder import (
            CompanyCandidateList,
            CompanyFinderAgent,
        )

        settings = make_settings()
        state = _make_ready_state()
        state.attempted_company_names = {"Google", "Meta"}
        assert state.preferences is not None
        state.preferences.excluded_companies = ["Amazon"]

        captured_messages: list[dict[str, str]] = []

        async def capture_llm(
            messages: list[dict[str, str]], **kwargs: object
        ) -> CompanyCandidateList:
            captured_messages.extend(messages)
            return CompanyCandidateList(companies=[])

        with patch.object(CompanyFinderAgent, "_call_llm", side_effect=capture_llm):
            agent = CompanyFinderAgent(settings)
            try:
                await agent.run(state)
            except Exception:
                pass  # FatalAgentError from empty companies is expected

        prompt = captured_messages[0]["content"]
        assert "Amazon" in prompt
        assert "Google" in prompt
        assert "Meta" in prompt


@pytest.mark.unit
class TestAdaptivePipelineRun:
    """Test the full run() method of AdaptivePipeline."""

    @pytest.mark.asyncio
    async def test_run_completes_and_returns_result(self) -> None:
        """Run completes setup + discovery + output and returns a valid RunResult."""
        settings = make_settings(min_recommended_jobs=1, max_discovery_iterations=1)
        pipeline = AdaptivePipeline(settings)

        async def fake_step(
            step_name: str, agent_cls: type, state: PipelineState, start: float
        ) -> PipelineState:
            if step_name == "find_companies":
                state.companies = [
                    Company(
                        name="Acme",
                        domain="acme.com",
                        career_page=CareerPage(
                            url="https://acme.com/careers", ats_type=ATSType.UNKNOWN
                        ),
                    )
                ]
            elif step_name == "score_jobs":
                state.scored_jobs = [_make_scored_job("Acme", 90)]
            return state

        @asynccontextmanager
        async def fake_trace(run_id: str) -> AsyncIterator[Any]:
            yield None

        # _make_ready_state() has profile + preferences set, so completed_steps
        # property will infer parse_resume and parse_prefs as done — setup skipped
        with (
            patch.object(pipeline, "_run_agent_step", side_effect=fake_step),
            patch.object(pipeline, "_load_or_create_state", return_value=_make_ready_state()),
            patch("job_hunter_agents.observability.bind_run_context"),
            patch("job_hunter_agents.observability.clear_run_context"),
            patch("job_hunter_agents.observability.trace_pipeline_run", side_effect=fake_trace),
            patch.object(pipeline, "_log_cost_summary"),
            patch.object(pipeline, "_set_root_span_attrs"),
        ):
            config = RunConfig(resume_path=Path("/tmp/test.pdf"), preferences_text="test")
            result = await pipeline.run(config)

        assert result.status in ("success", "partial")

    @pytest.mark.asyncio
    async def test_run_returns_existing_run_result(self) -> None:
        """If aggregator sets run_result, that result is returned."""
        settings = make_settings(min_recommended_jobs=1, max_discovery_iterations=1)
        pipeline = AdaptivePipeline(settings)

        async def fake_step(
            step_name: str, agent_cls: type, state: PipelineState, start: float
        ) -> PipelineState:
            if step_name == "find_companies":
                state.companies = [
                    Company(
                        name="Acme",
                        domain="acme.com",
                        career_page=CareerPage(
                            url="https://acme.com/careers", ats_type=ATSType.UNKNOWN
                        ),
                    )
                ]
            elif step_name == "score_jobs":
                state.scored_jobs = [_make_scored_job("Acme", 90)]
            elif step_name == "aggregate":
                state.run_result = state.build_result(
                    status="success",
                    duration_seconds=5.0,
                    output_files=["/tmp/results.csv"],
                )
            return state

        @asynccontextmanager
        async def fake_trace(run_id: str) -> AsyncIterator[Any]:
            yield None

        with (
            patch.object(pipeline, "_run_agent_step", side_effect=fake_step),
            patch.object(pipeline, "_load_or_create_state", return_value=_make_ready_state()),
            patch("job_hunter_agents.observability.bind_run_context"),
            patch("job_hunter_agents.observability.clear_run_context"),
            patch("job_hunter_agents.observability.trace_pipeline_run", side_effect=fake_trace),
            patch.object(pipeline, "_log_cost_summary"),
            patch.object(pipeline, "_set_root_span_attrs"),
        ):
            config = RunConfig(resume_path=Path("/tmp/test.pdf"), preferences_text="test")
            result = await pipeline.run(config)

        assert "/tmp/results.csv" in [str(f) for f in result.output_files]


@pytest.mark.unit
class TestDiscoveryLoopNonFatalError:
    """Test non-fatal error handling in discovery loop."""

    @pytest.mark.asyncio
    async def test_non_fatal_step_continues(self) -> None:
        """Non-fatal error in scraper step continues to next step."""
        settings = make_settings(min_recommended_jobs=1, max_discovery_iterations=1)
        pipeline = AdaptivePipeline(settings)
        state = _make_ready_state()

        async def fake_step(
            step_name: str, agent_cls: type, state: PipelineState, start: float
        ) -> PipelineState | RunResult:
            if step_name == "find_companies":
                state.companies = [
                    Company(
                        name="Acme",
                        domain="acme.com",
                        career_page=CareerPage(
                            url="https://acme.com/careers", ats_type=ATSType.UNKNOWN
                        ),
                    )
                ]
            elif step_name == "scrape_jobs":
                # Non-fatal: scraper timeout returns RunResult
                return state.build_result(status="failed", duration_seconds=1.0)
            elif step_name == "score_jobs":
                state.scored_jobs = [_make_scored_job("Acme", 90)]
            return state

        with patch.object(pipeline, "_run_agent_step", side_effect=fake_step):
            result = await pipeline._discovery_loop(state, 0.0)

        # Should still have scored jobs despite scraper failure
        assert len(result.scored_jobs) >= 1
