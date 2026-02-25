"""Unit tests for Temporal agent registry."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class TestLazyAgentMap:
    """Tests for the lazy agent class registry."""

    def test_loads_resume_parser_agent(self) -> None:
        """Can load ResumeParserAgent lazily."""
        from job_hunter_agents.orchestrator.temporal_registry import AGENT_MAP

        cls = AGENT_MAP["ResumeParserAgent"]
        assert cls.__name__ == "ResumeParserAgent"

    def test_loads_all_registered_agents(self) -> None:
        """All 8 agents can be loaded from the registry."""
        from job_hunter_agents.orchestrator.temporal_registry import AGENT_MAP, _AGENT_PATHS

        for name in _AGENT_PATHS:
            cls = AGENT_MAP[name]
            assert cls.__name__ == name

    def test_unknown_agent_raises_key_error(self) -> None:
        """KeyError for unknown agent names."""
        from job_hunter_agents.orchestrator.temporal_registry import AGENT_MAP

        with pytest.raises(KeyError):
            AGENT_MAP["NonexistentAgent"]
