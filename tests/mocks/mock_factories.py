"""Factory functions returning valid domain model instances."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from job_hunter_core.models.candidate import (
    CandidateProfile,
    SearchPreferences,
    Skill,
)
from job_hunter_core.models.company import CareerPage, Company
from job_hunter_core.models.job import (
    FitReport,
    NormalizedJob,
    RawJob,
    ScoredJob,
)
from job_hunter_core.models.run import AgentError, RunConfig
from job_hunter_core.state import PipelineState


def make_run_config(**overrides: object) -> RunConfig:
    """Create a valid RunConfig."""
    defaults: dict[str, object] = {
        "run_id": "test-run-001",
        "resume_path": Path("/tmp/test_resume.pdf"),
        "preferences_text": "Remote Python roles at startups",
    }
    defaults.update(overrides)
    return RunConfig(**defaults)  # type: ignore[arg-type]


def make_pipeline_state(**overrides: object) -> PipelineState:
    """Create a PipelineState with a default RunConfig."""
    config = overrides.pop("config", None) or make_run_config()
    state = PipelineState(config=config, **overrides)  # type: ignore[arg-type]
    return state


def make_candidate_profile(**overrides: object) -> CandidateProfile:
    """Create a minimal valid CandidateProfile."""
    defaults: dict[str, object] = {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "years_of_experience": 5.0,
        "skills": [Skill(name="Python"), Skill(name="SQL")],
        "raw_text": "Experienced software engineer with Python expertise.",
        "content_hash": "a" * 64,
    }
    defaults.update(overrides)
    return CandidateProfile(**defaults)  # type: ignore[arg-type]


def make_search_preferences(**overrides: object) -> SearchPreferences:
    """Create a minimal valid SearchPreferences."""
    defaults: dict[str, object] = {
        "raw_text": "Remote Python roles at startups",
        "preferred_locations": ["Remote"],
        "remote_preference": "remote",
        "target_titles": ["Software Engineer"],
    }
    defaults.update(overrides)
    return SearchPreferences(**defaults)  # type: ignore[arg-type]


def make_company(**overrides: object) -> Company:
    """Create a valid Company with a CareerPage."""
    company_id = overrides.pop("id", uuid4())
    career_page = overrides.pop(
        "career_page",
        CareerPage(url="https://example.com/careers"),
    )
    defaults: dict[str, object] = {
        "id": company_id,
        "name": "Acme Corp",
        "domain": "acme.com",
        "career_page": career_page,
    }
    defaults.update(overrides)
    return Company(**defaults)  # type: ignore[arg-type]


def make_raw_job(
    company_id: UUID | None = None, **overrides: object
) -> RawJob:
    """Create a valid RawJob."""
    cid = company_id or uuid4()
    defaults: dict[str, object] = {
        "company_id": cid,
        "company_name": "Acme Corp",
        "source_url": "https://acme.com/jobs/1",
        "scrape_strategy": "crawl4ai",
        "source_confidence": 0.9,
    }
    defaults.update(overrides)
    return RawJob(**defaults)  # type: ignore[arg-type]


def make_normalized_job(
    company_id: UUID | None = None,
    raw_job_id: UUID | None = None,
    **overrides: object,
) -> NormalizedJob:
    """Create a valid NormalizedJob."""
    defaults: dict[str, object] = {
        "company_id": company_id or uuid4(),
        "raw_job_id": raw_job_id or uuid4(),
        "company_name": "Acme Corp",
        "title": "Software Engineer",
        "jd_text": "Build and maintain web applications.",
        "apply_url": "https://acme.com/apply/1",
        "content_hash": "b" * 64,
    }
    defaults.update(overrides)
    return NormalizedJob(**defaults)  # type: ignore[arg-type]


def make_scored_job(
    job: NormalizedJob | None = None, **overrides: object
) -> ScoredJob:
    """Create a valid ScoredJob with a default FitReport."""
    if job is None:
        job = make_normalized_job()
    fit_report = overrides.pop(
        "fit_report",
        FitReport(
            score=85,
            skill_overlap=["Python"],
            skill_gaps=["Go"],
            seniority_match=True,
            location_match=True,
            org_type_match=True,
            summary="Good fit for the role.",
            recommendation="good_match",
            confidence=0.9,
        ),
    )
    defaults: dict[str, object] = {
        "job": job,
        "fit_report": fit_report,
    }
    defaults.update(overrides)
    return ScoredJob(**defaults)  # type: ignore[arg-type]


def make_agent_error(**overrides: object) -> AgentError:
    """Create a valid AgentError."""
    defaults: dict[str, object] = {
        "agent_name": "test_agent",
        "error_type": "ValueError",
        "error_message": "something went wrong",
        "timestamp": datetime.now(UTC),
    }
    defaults.update(overrides)
    return AgentError(**defaults)  # type: ignore[arg-type]
