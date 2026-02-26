"""Tests for PipelineState checkpoint serialization and state inference."""

from __future__ import annotations

from pathlib import Path

import pytest

from job_hunter_core.models.run import PipelineCheckpoint
from job_hunter_core.state import PipelineState
from tests.mocks.mock_factories import (
    make_agent_error,
    make_candidate_profile,
    make_company,
    make_normalized_job,
    make_pipeline_state,
    make_raw_job,
    make_scored_job,
    make_search_preferences,
)


@pytest.mark.unit
class TestPipelineStateCheckpoint:
    """Test to_checkpoint and from_checkpoint round-trips."""

    def test_to_checkpoint_empty_state(self) -> None:
        """Fresh state produces a checkpoint with config only."""
        state = make_pipeline_state()
        cp = state.to_checkpoint("parse_resume")

        assert cp.run_id == state.config.run_id
        assert cp.completed_step == "parse_resume"
        assert cp.state_snapshot["config"] is not None
        assert cp.state_snapshot["profile"] is None
        assert cp.state_snapshot["preferences"] is None
        assert cp.state_snapshot["companies"] == []

    def test_to_checkpoint_full_state(self) -> None:
        """All fields populated serialize into the checkpoint snapshot."""
        company = make_company()
        raw = make_raw_job(company_id=company.id)
        norm = make_normalized_job(company_id=company.id, raw_job_id=raw.id)
        scored = make_scored_job(job=norm)

        state = make_pipeline_state(
            profile=make_candidate_profile(),
            preferences=make_search_preferences(),
            companies=[company],
            raw_jobs=[raw],
            normalized_jobs=[norm],
            scored_jobs=[scored],
            errors=[make_agent_error()],
            total_tokens=1000,
            total_cost_usd=0.05,
        )
        cp = state.to_checkpoint("score_jobs")

        snap = cp.state_snapshot
        assert snap["profile"] is not None
        assert snap["preferences"] is not None
        assert len(snap["companies"]) == 1  # type: ignore[arg-type]
        assert len(snap["raw_jobs"]) == 1  # type: ignore[arg-type]
        assert len(snap["normalized_jobs"]) == 1  # type: ignore[arg-type]
        assert len(snap["scored_jobs"]) == 1  # type: ignore[arg-type]
        assert len(snap["errors"]) == 1  # type: ignore[arg-type]
        assert snap["total_tokens"] == 1000
        assert snap["total_cost_usd"] == 0.05

    def test_from_checkpoint_minimal(self) -> None:
        """Config-only checkpoint restores to a fresh state."""
        state = make_pipeline_state()
        cp = state.to_checkpoint("parse_resume")
        restored = PipelineState.from_checkpoint(cp)

        assert restored.config.run_id == state.config.run_id
        assert restored.profile is None
        assert restored.preferences is None
        assert restored.companies == []

    def test_from_checkpoint_with_profile(self) -> None:
        """Profile data round-trips through checkpoint."""
        state = make_pipeline_state(profile=make_candidate_profile())
        cp = state.to_checkpoint("parse_resume")
        restored = PipelineState.from_checkpoint(cp)

        assert restored.profile is not None
        assert restored.profile.name == "Jane Doe"
        assert restored.profile.email == "jane@example.com"

    def test_from_checkpoint_with_all_jobs(self) -> None:
        """Raw, normalized, and scored jobs all restore correctly."""
        company = make_company()
        raw = make_raw_job(company_id=company.id)
        norm = make_normalized_job(company_id=company.id, raw_job_id=raw.id)
        scored = make_scored_job(job=norm)

        state = make_pipeline_state(
            companies=[company],
            raw_jobs=[raw],
            normalized_jobs=[norm],
            scored_jobs=[scored],
        )
        cp = state.to_checkpoint("score_jobs")
        restored = PipelineState.from_checkpoint(cp)

        assert len(restored.companies) == 1
        assert restored.companies[0].name == "Acme Corp"
        assert len(restored.raw_jobs) == 1
        assert len(restored.normalized_jobs) == 1
        assert len(restored.scored_jobs) == 1
        assert restored.scored_jobs[0].fit_report.score == 85

    def test_from_checkpoint_with_errors(self) -> None:
        """Error list round-trips through checkpoint."""
        err = make_agent_error(agent_name="scraper", is_fatal=True)
        state = make_pipeline_state(errors=[err])
        cp = state.to_checkpoint("scrape_jobs")
        restored = PipelineState.from_checkpoint(cp)

        assert len(restored.errors) == 1
        assert restored.errors[0].agent_name == "scraper"
        assert restored.errors[0].is_fatal is True

    def test_from_checkpoint_cost_data(self) -> None:
        """total_tokens and total_cost_usd restore correctly."""
        state = make_pipeline_state(total_tokens=5000, total_cost_usd=1.23)
        cp = state.to_checkpoint("score_jobs")
        restored = PipelineState.from_checkpoint(cp)

        assert restored.total_tokens == 5000
        assert restored.total_cost_usd == pytest.approx(1.23)

    def test_run_result_roundtrips_through_checkpoint(self) -> None:
        """run_result with output_files survives checkpoint serialization."""
        state = make_pipeline_state(
            scored_jobs=[make_scored_job()],
            total_tokens=500,
            total_cost_usd=0.25,
        )
        state.run_result = state.build_result(
            status="success",
            duration_seconds=5.0,
            output_files=["/tmp/results.csv", "/tmp/results.xlsx"],
        )
        cp = state.to_checkpoint("aggregate")
        restored = PipelineState.from_checkpoint(cp)

        assert restored.run_result is not None
        assert restored.run_result.status == "success"
        assert len(restored.run_result.output_files) == 2
        assert restored.run_result.output_files[0] == Path("/tmp/results.csv")

    def test_run_result_none_roundtrips(self) -> None:
        """State without run_result still roundtrips cleanly."""
        state = make_pipeline_state()
        assert state.run_result is None

        cp = state.to_checkpoint("parse_resume")
        restored = PipelineState.from_checkpoint(cp)
        assert restored.run_result is None

    def test_from_checkpoint_invalid_config(self) -> None:
        """Missing config in snapshot raises ValueError."""
        cp = PipelineCheckpoint(
            run_id="test",
            completed_step="parse_resume",
            state_snapshot={"profile": None},
        )
        with pytest.raises(ValueError, match="missing config"):
            PipelineState.from_checkpoint(cp)

    def test_roundtrip_serialization(self) -> None:
        """to_checkpoint -> from_checkpoint produces equivalent state."""
        company = make_company()
        raw = make_raw_job(company_id=company.id)
        norm = make_normalized_job(company_id=company.id, raw_job_id=raw.id)
        scored = make_scored_job(job=norm)
        profile = make_candidate_profile()
        prefs = make_search_preferences()

        original = make_pipeline_state(
            profile=profile,
            preferences=prefs,
            companies=[company],
            raw_jobs=[raw],
            normalized_jobs=[norm],
            scored_jobs=[scored],
            total_tokens=2000,
            total_cost_usd=0.50,
        )
        cp = original.to_checkpoint("score_jobs")
        restored = PipelineState.from_checkpoint(cp)

        assert restored.config.run_id == original.config.run_id
        assert restored.profile is not None
        assert original.profile is not None
        assert restored.profile.name == original.profile.name
        assert restored.preferences is not None
        assert original.preferences is not None
        assert restored.preferences.raw_text == original.preferences.raw_text
        assert len(restored.companies) == len(original.companies)
        assert len(restored.raw_jobs) == len(original.raw_jobs)
        assert len(restored.normalized_jobs) == len(original.normalized_jobs)
        assert len(restored.scored_jobs) == len(original.scored_jobs)
        assert restored.total_tokens == original.total_tokens
        assert restored.total_cost_usd == pytest.approx(original.total_cost_usd)


@pytest.mark.unit
class TestCompletedSteps:
    """Test completed_steps inference from state contents."""

    def test_empty_state_no_steps(self) -> None:
        """Fresh state has no completed steps."""
        state = make_pipeline_state()
        assert state.completed_steps == []

    @pytest.mark.parametrize(
        ("field", "value", "expected_step"),
        [
            ("profile", make_candidate_profile(), "parse_resume"),
            ("preferences", make_search_preferences(), "parse_prefs"),
        ],
        ids=["profile->parse_resume", "preferences->parse_prefs"],
    )
    def test_single_field_infers_step(self, field: str, value: object, expected_step: str) -> None:
        """Setting a single field infers the corresponding completed step."""
        state = make_pipeline_state(**{field: value})
        assert expected_step in state.completed_steps

    def test_companies_infers_find_companies(self) -> None:
        """Non-empty companies list infers find_companies step."""
        state = make_pipeline_state(companies=[make_company()])
        assert "find_companies" in state.completed_steps

    def test_raw_jobs_infers_scrape_jobs(self) -> None:
        """Non-empty raw_jobs list infers scrape_jobs step."""
        state = make_pipeline_state(raw_jobs=[make_raw_job()])
        assert "scrape_jobs" in state.completed_steps

    def test_normalized_jobs_infers_process_jobs(self) -> None:
        """Non-empty normalized_jobs list infers process_jobs step."""
        state = make_pipeline_state(normalized_jobs=[make_normalized_job()])
        assert "process_jobs" in state.completed_steps

    def test_scored_jobs_infers_score_jobs(self) -> None:
        """Non-empty scored_jobs list infers score_jobs step."""
        state = make_pipeline_state(scored_jobs=[make_scored_job()])
        assert "score_jobs" in state.completed_steps


@pytest.mark.unit
class TestBuildResult:
    """Test build_result aggregation."""

    def test_build_result_success(self) -> None:
        """Correct aggregation of companies, jobs, and cost."""
        company = make_company()
        raw = make_raw_job(company_id=company.id)
        scored = make_scored_job()
        state = make_pipeline_state(
            companies=[company],
            raw_jobs=[raw],
            scored_jobs=[scored],
            total_tokens=1000,
            total_cost_usd=0.10,
        )

        result = state.build_result(status="success", duration_seconds=5.0)

        assert result.status == "success"
        assert result.companies_attempted == 1
        assert result.companies_succeeded == 1
        assert result.jobs_scraped == 1
        assert result.jobs_scored == 1
        assert result.total_tokens_used == 1000
        assert result.estimated_cost_usd == pytest.approx(0.10)
        assert result.duration_seconds == 5.0

    def test_build_result_with_errors(self) -> None:
        """Errors propagated into RunResult."""
        err = make_agent_error()
        state = make_pipeline_state(errors=[err])
        result = state.build_result(status="partial", duration_seconds=2.0)

        assert result.status == "partial"
        assert len(result.errors) == 1

    def test_build_result_output_files(self) -> None:
        """String paths wrapped as Path objects."""
        state = make_pipeline_state()
        result = state.build_result(
            status="success",
            duration_seconds=1.0,
            output_files=["/tmp/output.csv", "/tmp/output.xlsx"],
        )

        assert len(result.output_files) == 2
        assert all(isinstance(f, Path) for f in result.output_files)
