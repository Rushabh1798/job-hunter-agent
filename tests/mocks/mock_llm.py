"""Fixture-based response factory for FakeLLMProvider in dry-run and tests."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "llm_responses"

T = TypeVar("T", bound=BaseModel)

# Maps response_model class name to fixture filename
_FIXTURE_MAP: dict[str, str] = {
    "CandidateProfile": "candidate_profile.json",
    "SearchPreferences": "search_preferences.json",
    "CompanyCandidateList": "company_candidates.json",
    "ExtractedJob": "extracted_job.json",
    "BatchScoreResult": "batch_score.json",
}


def _load_fixture(class_name: str) -> dict[str, object]:
    """Load fixture JSON by response_model class name."""
    filename = _FIXTURE_MAP.get(class_name)
    if not filename:
        msg = f"No fixture for response_model={class_name}"
        raise ValueError(msg)
    path = FIXTURES_DIR / filename
    return json.loads(path.read_text())  # type: ignore[no-any-return]


def build_fake_response(response_model: type[T]) -> T:  # noqa: UP047
    """Construct a Pydantic model instance from fixture data."""
    class_name = response_model.__name__
    fixture = _load_fixture(class_name)
    data = fixture.get("data", {})

    if not isinstance(data, dict):
        msg = f"Fixture data for {class_name} is not a dict"
        raise ValueError(msg)

    return response_model(**data)


def fixture_response_factory(  # noqa: UP047
    response_model: type[T],
    messages: Sequence[dict[str, str]],
) -> T:
    """Response factory for FakeLLMProvider — dispatches to fixture JSON files.

    This matches the signature expected by FakeLLMProvider(response_factory=...).
    """
    return build_fake_response(response_model)
