"""Unit tests for Temporal worker setup."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


class TestRunWorker:
    """Tests for run_worker."""

    @pytest.mark.asyncio
    async def test_unknown_queue_raises_value_error(self) -> None:
        """Unknown queue name raises ValueError."""
        from job_hunter_agents.orchestrator.temporal_worker import run_worker

        mock_settings = MagicMock()
        with patch(
            "job_hunter_agents.orchestrator.temporal_worker.create_temporal_client",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ):
            with pytest.raises(ValueError, match="Unknown queue name"):
                await run_worker(mock_settings, queue_name="invalid")

    @pytest.mark.asyncio
    async def test_default_queue(self) -> None:
        """Worker starts with the default queue."""
        from job_hunter_agents.orchestrator.temporal_worker import run_worker

        mock_settings = MagicMock()
        mock_settings.temporal_task_queue = "job-hunter-default"

        mock_client = MagicMock()
        mock_worker = AsyncMock()
        mock_worker.run = AsyncMock()

        with (
            patch(
                "job_hunter_agents.orchestrator.temporal_worker.create_temporal_client",
                new_callable=AsyncMock,
                return_value=mock_client,
            ),
            patch(
                "job_hunter_agents.orchestrator.temporal_worker.Worker",
                return_value=mock_worker,
            ) as mock_worker_cls,
        ):
            await run_worker(mock_settings, queue_name="default")

        mock_worker_cls.assert_called_once()
        call_kwargs = mock_worker_cls.call_args
        assert call_kwargs[1]["task_queue"] == "job-hunter-default"
        mock_worker.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_queue(self) -> None:
        """Worker starts with the LLM queue."""
        from job_hunter_agents.orchestrator.temporal_worker import run_worker

        mock_settings = MagicMock()
        mock_settings.temporal_llm_task_queue = "job-hunter-llm"

        mock_client = MagicMock()
        mock_worker = AsyncMock()
        mock_worker.run = AsyncMock()

        with (
            patch(
                "job_hunter_agents.orchestrator.temporal_worker.create_temporal_client",
                new_callable=AsyncMock,
                return_value=mock_client,
            ),
            patch(
                "job_hunter_agents.orchestrator.temporal_worker.Worker",
                return_value=mock_worker,
            ) as mock_worker_cls,
        ):
            await run_worker(mock_settings, queue_name="llm")

        call_kwargs = mock_worker_cls.call_args
        assert call_kwargs[1]["task_queue"] == "job-hunter-llm"


class TestQueueSettingsMap:
    """Tests for QUEUE_SETTINGS_MAP constant."""

    def test_all_queues_present(self) -> None:
        """All three queue names are in the map."""
        from job_hunter_agents.orchestrator.temporal_worker import QUEUE_SETTINGS_MAP

        assert "default" in QUEUE_SETTINGS_MAP
        assert "llm" in QUEUE_SETTINGS_MAP
        assert "scraping" in QUEUE_SETTINGS_MAP
