"""Resume parser agent — extracts CandidateProfile from PDF."""

from __future__ import annotations

import hashlib
import time

import structlog

from job_hunter_agents.agents.base import BaseAgent
from job_hunter_agents.prompts.resume_parser import (
    RESUME_PARSER_USER,
)
from job_hunter_agents.tools.pdf_parser import PDFParser
from job_hunter_core.models.candidate import CandidateProfile
from job_hunter_core.state import PipelineState

logger = structlog.get_logger()


class ResumeParserAgent(BaseAgent):
    """Parse a resume PDF into a structured CandidateProfile."""

    agent_name = "resume_parser"

    async def run(self, state: PipelineState) -> PipelineState:
        """Extract candidate profile from resume PDF."""
        self._log_start({"resume_path": str(state.config.resume_path)})
        start = time.monotonic()

        pdf_parser = PDFParser()
        raw_text = await pdf_parser.extract_text(state.config.resume_path)
        content_hash = hashlib.sha256(raw_text.encode()).hexdigest()

        profile = await self._call_llm(
            messages=[
                {"role": "user", "content": RESUME_PARSER_USER.format(resume_text=raw_text)},
            ],
            model=self.settings.haiku_model,
            response_model=CandidateProfile,
            state=state,
            max_retries=3,
        )

        profile.raw_text = raw_text
        profile.content_hash = content_hash

        state.profile = profile
        self._log_end(
            time.monotonic() - start,
            {
                "name": profile.name,
                "email": str(profile.email),
                "skills_count": len(profile.skills),
            },
        )
        return state
