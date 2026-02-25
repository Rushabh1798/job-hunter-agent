"""Fake LLM dispatcher that routes _call_llm calls to fixture JSON files."""

from __future__ import annotations

import json
import types
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


def _make_fake_raw_response(meta: dict[str, object]) -> object:
    """Build a fake _raw_response with usage attributes.

    Creates the attribute chain _raw_response.usage.{input_tokens, output_tokens}
    that extract_token_usage() expects.
    """
    usage = types.SimpleNamespace(
        input_tokens=meta.get("input_tokens", 0),
        output_tokens=meta.get("output_tokens", 0),
    )
    return types.SimpleNamespace(usage=usage)


def build_fake_response(response_model: type[T]) -> T:  # noqa: UP047
    """Construct a Pydantic model instance from fixture data with _raw_response attached."""
    class_name = response_model.__name__
    fixture = _load_fixture(class_name)
    meta = fixture.get("_meta", {})
    data = fixture.get("data", {})

    if not isinstance(meta, dict):
        meta = {}
    if not isinstance(data, dict):
        msg = f"Fixture data for {class_name} is not a dict"
        raise ValueError(msg)

    instance = response_model(**data)
    # Attach fake _raw_response so extract_token_usage() works
    object.__setattr__(instance, "_raw_response", _make_fake_raw_response(meta))
    return instance


class FakeInstructorClient:
    """Fake instructor client that returns fixture-based responses.

    Replaces the real instructor.from_anthropic() client.
    The call chain is: self._instructor.messages.create(response_model=...) -> T
    """

    def __init__(self) -> None:
        """Initialize with a messages namespace."""
        self.messages = _FakeMessages()


class _FakeMessages:
    """Fake messages endpoint that returns fixture data."""

    async def create(
        self,
        model: str = "",
        max_tokens: int = 4096,
        messages: list[dict[str, str]] | None = None,
        response_model: type[T] | None = None,
    ) -> T:
        """Return a fixture-based response matching the response_model."""
        if response_model is None:
            msg = "response_model is required"
            raise ValueError(msg)
        return build_fake_response(response_model)
