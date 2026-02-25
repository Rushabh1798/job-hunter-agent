"""Agent class registry for Temporal activity dispatch."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from job_hunter_agents.agents.base import BaseAgent

# Lazy import map to avoid heavy module loading at import time.
# Each key maps to the agent class used by _run_agent_step().
_AGENT_PATHS: dict[str, tuple[str, str]] = {
    "ResumeParserAgent": ("job_hunter_agents.agents.resume_parser", "ResumeParserAgent"),
    "PrefsParserAgent": ("job_hunter_agents.agents.prefs_parser", "PrefsParserAgent"),
    "CompanyFinderAgent": ("job_hunter_agents.agents.company_finder", "CompanyFinderAgent"),
    "JobsScraperAgent": ("job_hunter_agents.agents.jobs_scraper", "JobsScraperAgent"),
    "JobProcessorAgent": ("job_hunter_agents.agents.job_processor", "JobProcessorAgent"),
    "JobsScorerAgent": ("job_hunter_agents.agents.jobs_scorer", "JobsScorerAgent"),
    "AggregatorAgent": ("job_hunter_agents.agents.aggregator", "AggregatorAgent"),
    "NotifierAgent": ("job_hunter_agents.agents.notifier", "NotifierAgent"),
}


class _LazyAgentMap:
    """Lazily import agent classes on first access."""

    def __getitem__(self, key: str) -> type[BaseAgent]:
        """Import and return the agent class by name."""
        import importlib

        module_path, class_name = _AGENT_PATHS[key]
        module = importlib.import_module(module_path)
        return getattr(module, class_name)  # type: ignore[no-any-return]


AGENT_MAP = _LazyAgentMap()
