"""Abstract embedder interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbedderBase(Protocol):
    """Abstract interface for text embedding providers."""

    async def embed_text(self, text: str) -> list[float]:
        """Embed a single text string into a vector."""
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts into vectors."""
        ...
