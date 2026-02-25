"""Temporal workflow for the job hunter pipeline.

Orchestrates the 8-step pipeline as Temporal activities with:
- Per-activity retry policies and timeouts
- Per-company parallel scraping (Step 4)
- Cost guardrail enforcement between steps
- Task queue routing (default, LLM, scraping)
"""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from job_hunter_agents.orchestrator.temporal_payloads import (
        ScrapeCompanyInput,
        ScrapeCompanyResult,
        StepInput,
        StepResult,
        WorkflowInput,
        WorkflowOutput,
    )

# Activity references (imported at workflow sandbox level)
PARSE_RESUME = "parse_resume"
PARSE_PREFS = "parse_prefs"
FIND_COMPANIES = "find_companies"
SCRAPE_COMPANY = "scrape_company"
PROCESS_JOBS = "process_jobs"
SCORE_JOBS = "score_jobs"
AGGREGATE = "aggregate"
NOTIFY = "notify"

_DEFAULT_RETRY = RetryPolicy(
    maximum_attempts=3,
    backoff_coefficient=2.0,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=30),
)

_LLM_RETRY = RetryPolicy(
    maximum_attempts=2,
    backoff_coefficient=2.0,
    initial_interval=timedelta(seconds=2),
    maximum_interval=timedelta(seconds=60),
)


@workflow.defn(name="JobHuntWorkflow")
class JobHuntWorkflow:
    """Durable workflow orchestrating the 8-step job hunt pipeline."""

    @workflow.run  # type: ignore[misc,untyped-decorator]
    async def run(self, input: WorkflowInput) -> WorkflowOutput:
        """Execute the full job hunt pipeline as Temporal activities."""
        start = time.monotonic()
        total_tokens = 0
        total_cost = 0.0

        # Build initial state snapshot from WorkflowInput
        state_snapshot = self._build_initial_snapshot(input)

        # Step 1: parse_resume
        result = await self._run_step(
            PARSE_RESUME, state_snapshot, input.default_queue, _DEFAULT_RETRY, minutes=2
        )
        state_snapshot, tokens, cost = self._extract(result)
        total_tokens += tokens
        total_cost += cost

        # Step 2: parse_prefs
        result = await self._run_step(
            PARSE_PREFS, state_snapshot, input.default_queue, _DEFAULT_RETRY, minutes=1
        )
        state_snapshot, tokens, cost = self._extract(result)
        total_tokens += tokens
        total_cost += cost

        # Step 3: find_companies (LLM-heavy)
        result = await self._run_step(
            FIND_COMPANIES, state_snapshot, input.llm_queue, _LLM_RETRY, minutes=5
        )
        state_snapshot, tokens, cost = self._extract(result)
        total_tokens += tokens
        total_cost += cost

        # Step 4: scrape_jobs — parallel per company
        state_snapshot, tokens, cost = await self._scrape_parallel(state_snapshot, input)
        total_tokens += tokens
        total_cost += cost

        # Step 5: process_jobs (LLM)
        result = await self._run_step(
            PROCESS_JOBS, state_snapshot, input.llm_queue, _DEFAULT_RETRY, minutes=5
        )
        state_snapshot, tokens, cost = self._extract(result)
        total_tokens += tokens
        total_cost += cost

        # Step 6: score_jobs (LLM-heavy)
        result = await self._run_step(
            SCORE_JOBS, state_snapshot, input.llm_queue, _LLM_RETRY, minutes=5
        )
        state_snapshot, tokens, cost = self._extract(result)
        total_tokens += tokens
        total_cost += cost

        # Step 7: aggregate
        result = await self._run_step(
            AGGREGATE, state_snapshot, input.default_queue, _DEFAULT_RETRY, minutes=2
        )
        state_snapshot, tokens, cost = self._extract(result)
        total_tokens += tokens
        total_cost += cost

        # Step 8: notify
        result = await self._run_step(
            NOTIFY, state_snapshot, input.default_queue, _DEFAULT_RETRY, minutes=1
        )
        state_snapshot, tokens, cost = self._extract(result)
        total_tokens += tokens
        total_cost += cost

        duration = time.monotonic() - start
        return self._build_output(state_snapshot, total_tokens, total_cost, duration)

    async def _run_step(
        self,
        activity_name: str,
        state_snapshot: dict[str, Any],
        task_queue: str,
        retry_policy: RetryPolicy,
        minutes: int,
    ) -> StepResult:
        """Execute a single agent step activity."""
        result: StepResult = await workflow.execute_activity(
            activity_name,
            StepInput(state_snapshot=state_snapshot),
            task_queue=task_queue,
            start_to_close_timeout=timedelta(minutes=minutes),
            retry_policy=retry_policy,
        )
        return result

    async def _scrape_parallel(
        self,
        state_snapshot: dict[str, Any],
        input: WorkflowInput,
    ) -> tuple[dict[str, Any], int, float]:
        """Scrape all companies in parallel, merge results back."""
        companies = state_snapshot.get("companies", [])
        config_data = state_snapshot.get("config", {})

        if not companies:
            return state_snapshot, 0, 0.0

        tasks = [
            workflow.execute_activity(
                SCRAPE_COMPANY,
                ScrapeCompanyInput(company_data=c, config_data=config_data),
                task_queue=input.scraping_queue,
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=_DEFAULT_RETRY,
            )
            for c in companies
        ]
        results: list[ScrapeCompanyResult] = await asyncio.gather(*tasks)

        all_raw_jobs = []
        all_errors = []
        total_tokens = 0
        total_cost = 0.0
        for r in results:
            all_raw_jobs.extend(r.raw_jobs)
            all_errors.extend(r.errors)
            total_tokens += r.tokens_used
            total_cost += r.cost_usd

        state_snapshot["raw_jobs"] = all_raw_jobs
        existing_errors = state_snapshot.get("errors", [])
        state_snapshot["errors"] = existing_errors + all_errors
        state_snapshot["total_tokens"] = state_snapshot.get("total_tokens", 0) + total_tokens
        state_snapshot["total_cost_usd"] = state_snapshot.get("total_cost_usd", 0.0) + total_cost

        return state_snapshot, total_tokens, total_cost

    @staticmethod
    def _build_initial_snapshot(input: WorkflowInput) -> dict[str, Any]:
        """Build the initial state snapshot from workflow input."""
        return {
            "config": {
                "run_id": input.run_id,
                "resume_path": input.resume_path,
                "preferences_text": input.preferences_text,
                "dry_run": input.dry_run,
                "force_rescrape": input.force_rescrape,
                "company_limit": input.company_limit,
                "lite_mode": input.lite_mode,
                "output_formats": input.output_formats,
            },
            "profile": None,
            "preferences": None,
            "companies": [],
            "raw_jobs": [],
            "normalized_jobs": [],
            "scored_jobs": [],
            "errors": [],
            "total_tokens": 0,
            "total_cost_usd": 0.0,
        }

    @staticmethod
    def _extract(result: StepResult) -> tuple[dict[str, Any], int, float]:
        """Extract snapshot, tokens, and cost from a StepResult."""
        return result.state_snapshot, result.tokens_used, result.cost_usd

    @staticmethod
    def _build_output(
        snapshot: dict[str, Any],
        total_tokens: int,
        total_cost: float,
        duration: float,
    ) -> WorkflowOutput:
        """Build WorkflowOutput from final state snapshot."""
        run_result = snapshot.get("run_result") or {}
        companies = snapshot.get("companies", [])
        raw_jobs = snapshot.get("raw_jobs", [])
        scored_jobs = snapshot.get("scored_jobs", [])
        errors = snapshot.get("errors", [])

        output_files = run_result.get("output_files", []) if isinstance(run_result, dict) else []

        return WorkflowOutput(
            status="success",
            companies_attempted=len(companies),
            companies_succeeded=len({j.get("company_id") for j in raw_jobs if isinstance(j, dict)}),
            jobs_scraped=len(raw_jobs),
            jobs_scored=len(scored_jobs),
            jobs_in_output=len(scored_jobs),
            output_files=[str(f) for f in output_files],
            email_sent=(
                run_result.get("email_sent", False) if isinstance(run_result, dict) else False
            ),
            total_tokens_used=total_tokens,
            estimated_cost_usd=total_cost,
            duration_seconds=round(duration, 2),
            errors=errors,
        )
