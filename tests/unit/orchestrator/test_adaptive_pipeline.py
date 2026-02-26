"""Tests for adaptive pipeline discovery loop."""

from __future__ import annotations

from pathlib import Path
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
        """Loop exits after one iteration when target is met."""
        settings = make_settings(min_recommended_jobs=2, max_discovery_iterations=3)
        pipeline = AdaptivePipeline(settings)
        state = _make_ready_state()

        # Simulate discovery steps producing 3 scored jobs
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
                    )
                ]
            elif step_name == "score_jobs":
                state.scored_jobs = [
                    _make_scored_job("Acme", 90),
                    _make_scored_job("Acme", 85),
                    _make_scored_job("Acme", 80),
                ]
            return state

        with patch.object(pipeline, "_run_agent_step", side_effect=fake_step):
            result = await pipeline._discovery_loop(state, 0.0)

        assert len(result.scored_jobs) >= 2
        assert result.discovery_iteration == 0
        assert "Acme" in result.attempted_company_names

    @pytest.mark.asyncio
    async def test_multiple_iterations_accumulate(self) -> None:
        """Loop runs multiple iterations, accumulating scored jobs."""
        settings = make_settings(min_recommended_jobs=4, max_discovery_iterations=3)
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
                state.scored_jobs = [
                    _make_scored_job(f"Co{call_count}", 85),
                    _make_scored_job(f"Co{call_count}", 80),
                ]
            return state

        with patch.object(pipeline, "_run_agent_step", side_effect=fake_step):
            result = await pipeline._discovery_loop(state, 0.0)

        # Should have accumulated jobs from 2 iterations (2+2 = 4 >= target 4)
        assert len(result.scored_jobs) >= 4
        assert result.attempted_company_names == {"Co1", "Co2"}

    @pytest.mark.asyncio
    async def test_fatal_error_preserves_previous_jobs(self) -> None:
        """Fatal error during discovery preserves previously scored jobs."""
        settings = make_settings(min_recommended_jobs=10, max_discovery_iterations=3)
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
                    # Fatal on second iteration
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
