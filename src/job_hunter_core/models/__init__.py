"""Domain models for job-hunter-agent."""

from job_hunter_core.models.candidate import (
    CandidateProfile,
    Education,
    SearchPreferences,
    Skill,
)
from job_hunter_core.models.company import ATSType, CareerPage, Company
from job_hunter_core.models.job import FitReport, NormalizedJob, RawJob, ScoredJob
from job_hunter_core.models.run import (
    AgentError,
    PipelineCheckpoint,
    RunConfig,
    RunResult,
)

__all__ = [
    "ATSType",
    "AgentError",
    "CandidateProfile",
    "CareerPage",
    "Company",
    "Education",
    "FitReport",
    "NormalizedJob",
    "PipelineCheckpoint",
    "RawJob",
    "RunConfig",
    "RunResult",
    "ScoredJob",
    "SearchPreferences",
    "Skill",
]
