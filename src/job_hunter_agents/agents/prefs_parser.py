"""Preferences parser agent — extracts SearchPreferences from freeform text."""

from __future__ import annotations

import time

import structlog

from job_hunter_agents.agents.base import BaseAgent
from job_hunter_agents.prompts.prefs_parser import (
    PREFS_PARSER_USER,
)
from job_hunter_core.models.candidate import SearchPreferences
from job_hunter_core.state import PipelineState

logger = structlog.get_logger()


class PrefsParserAgent(BaseAgent):
    """Parse freeform job preferences text into structured SearchPreferences."""

    agent_name = "prefs_parser"

    async def run(self, state: PipelineState) -> PipelineState:
        """Parse preferences text into SearchPreferences."""
        self._log_start({"text_length": len(state.config.preferences_text)})
        start = time.monotonic()

        prefs = await self._call_llm(
            messages=[
                {
                    "role": "user",
                    "content": PREFS_PARSER_USER.format(
                        preferences_text=state.config.preferences_text
                    ),
                },
            ],
            model=self.settings.haiku_model,
            response_model=SearchPreferences,
            state=state,
        )

        prefs.raw_text = state.config.preferences_text

        state.preferences = prefs
        self._log_end(
            time.monotonic() - start,
            {
                "target_titles": prefs.target_titles,
                "locations": prefs.preferred_locations,
            },
        )
        return state
