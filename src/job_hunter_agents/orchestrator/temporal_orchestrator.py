"""Temporal orchestrator — starts workflow and waits for result.

Raises TemporalConnectionError if the server is unreachable.
The checkpoint-based Pipeline is used only when orchestrator != "temporal".
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from job_hunter_agents.orchestrator.temporal_client import create_temporal_client
from job_hunter_agents.orchestrator.temporal_payloads import WorkflowInput, WorkflowOutput
from job_hunter_agents.orchestrator.temporal_workflow import JobHuntWorkflow
from job_hunter_core.models.run import RunResult

if TYPE_CHECKING:
    from job_hunter_core.config.settings import Settings
    from job_hunter_core.models.run import RunConfig

logger = structlog.get_logger()


class TemporalOrchestrator:
    """Start a Temporal workflow and wait for the result.

    Raises ``TemporalConnectionError`` if the server is unreachable.
    JSON-checkpoint fallback only applies when the user does not
    enable Temporal (i.e. omits ``--temporal``).
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with application settings."""
        self.settings = settings

    async def run(self, config: RunConfig) -> RunResult:
        """Execute the pipeline via Temporal workflow.

        Raises TemporalConnectionError if the server is unreachable.
        """
        client = await create_temporal_client(self.settings)

        workflow_input = self._build_input(config)
        timeout = timedelta(seconds=self.settings.temporal_workflow_timeout_seconds)

        output: WorkflowOutput = await client.execute_workflow(
            JobHuntWorkflow.run,
            workflow_input,
            id=config.run_id,
            task_queue=self.settings.temporal_task_queue,
            execution_timeout=timeout,
        )

        logger.info(
            "temporal_workflow_complete",
            run_id=config.run_id,
            status=output.status,
        )
        return self._to_run_result(output, config.run_id)

    def _build_input(self, config: RunConfig) -> WorkflowInput:
        """Convert RunConfig to WorkflowInput."""
        return WorkflowInput(
            run_id=config.run_id,
            resume_path=str(config.resume_path),
            preferences_text=config.preferences_text,
            dry_run=config.dry_run,
            force_rescrape=config.force_rescrape,
            company_limit=config.company_limit,
            lite_mode=config.lite_mode,
            output_formats=config.output_formats,
            default_queue=self.settings.temporal_task_queue,
            llm_queue=self.settings.temporal_llm_task_queue,
            scraping_queue=self.settings.temporal_scraping_task_queue,
        )

    @staticmethod
    def _to_run_result(output: WorkflowOutput, run_id: str) -> RunResult:
        """Convert WorkflowOutput to RunResult."""
        from job_hunter_core.models.run import AgentError

        errors = []
        for e in output.errors:
            if isinstance(e, dict):
                errors.append(AgentError(**e))
            else:
                logger.warning("temporal_non_dict_error", raw_error=repr(e))

        return RunResult(
            run_id=run_id,
            status=output.status,
            companies_attempted=output.companies_attempted,
            companies_succeeded=output.companies_succeeded,
            jobs_scraped=output.jobs_scraped,
            jobs_scored=output.jobs_scored,
            jobs_in_output=output.jobs_in_output,
            output_files=[Path(f) for f in output.output_files],
            email_sent=output.email_sent,
            errors=errors,
            total_tokens_used=output.total_tokens_used,
            estimated_cost_usd=output.estimated_cost_usd,
            duration_seconds=output.duration_seconds,
        )
