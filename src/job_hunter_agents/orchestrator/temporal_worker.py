"""Temporal worker setup — registers activities and starts polling."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from temporalio.worker import Worker

from job_hunter_agents.orchestrator.temporal_activities import ALL_ACTIVITIES
from job_hunter_agents.orchestrator.temporal_client import create_temporal_client
from job_hunter_agents.orchestrator.temporal_workflow import JobHuntWorkflow

if TYPE_CHECKING:
    from job_hunter_core.config.settings import Settings

logger = structlog.get_logger()

# Map short queue names to settings attribute names
QUEUE_SETTINGS_MAP = {
    "default": "temporal_task_queue",
    "llm": "temporal_llm_task_queue",
    "scraping": "temporal_scraping_task_queue",
}


async def run_worker(settings: Settings, queue_name: str = "default") -> None:
    """Start a Temporal worker that polls the specified task queue.

    Args:
        settings: Application settings (including Temporal connection).
        queue_name: Short queue name: 'default', 'llm', or 'scraping'.
    """
    client = await create_temporal_client(settings)

    attr_name = QUEUE_SETTINGS_MAP.get(queue_name)
    if attr_name is None:
        msg = f"Unknown queue name '{queue_name}'. Use: {', '.join(QUEUE_SETTINGS_MAP)}"
        raise ValueError(msg)

    task_queue: str = getattr(settings, attr_name)

    logger.info(
        "temporal_worker_starting",
        task_queue=task_queue,
        queue_name=queue_name,
        activities=len(ALL_ACTIVITIES),
    )

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[JobHuntWorkflow],
        activities=ALL_ACTIVITIES,
    )
    await worker.run()
