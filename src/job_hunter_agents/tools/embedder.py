"""Text embedding implementations: local (sentence-transformers) and Voyage API."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from job_hunter_infra.cache.disk_cache import DiskCacheClient

logger = structlog.get_logger()


class LocalEmbedder:
    """sentence-transformers based embedder. Free, fast, no API key."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        """Initialize with a model name (lazy-loaded)."""
        self._model_name = model_name
        self._model: Any = None

    def _get_model(self) -> Any:  # noqa: ANN401
        """Lazy-load the sentence transformer model."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return self._model

    async def embed_text(self, text: str) -> list[float]:
        """Embed a single text string into a vector."""
        model = self._get_model()
        embedding = await asyncio.to_thread(model.encode, text)
        return list(embedding.tolist())

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts into vectors."""
        if not texts:
            return []
        model = self._get_model()
        embeddings = await asyncio.to_thread(model.encode, texts)
        return [list(e.tolist()) for e in embeddings]


class VoyageEmbedder:
    """Voyage AI embeddings via API."""

    def __init__(self, api_key: str, model: str = "voyage-2") -> None:
        """Initialize with Voyage API key."""
        self._api_key = api_key
        self._model = model

    async def embed_text(self, text: str) -> list[float]:
        """Embed a single text string via Voyage API."""
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts via Voyage API."""
        import httpx

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.voyageai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={"input": texts, "model": self._model},
            )
            response.raise_for_status()
            data = response.json()
            return [item["embedding"] for item in data["data"]]


class CachedEmbedder:
    """Wrapper that caches embeddings by text content hash."""

    def __init__(
        self,
        embedder: LocalEmbedder | VoyageEmbedder,
        cache: DiskCacheClient,
    ) -> None:
        """Initialize with an embedder and cache client."""
        self._embedder = embedder
        self._cache = cache

    def _cache_key(self, text: str) -> str:
        """Generate cache key from text hash."""
        return f"emb:{hashlib.sha256(text.encode()).hexdigest()}"

    async def embed_text(self, text: str) -> list[float]:
        """Embed with cache lookup."""
        key = self._cache_key(text)
        cached = await self._cache.get(key)
        if cached:
            return json.loads(cached)  # type: ignore[no-any-return]

        embedding = await self._embedder.embed_text(text)
        await self._cache.set(key, json.dumps(embedding), ttl_seconds=86400 * 30)
        return embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed batch with per-text caching."""
        results: list[list[float]] = []
        for text in texts:
            results.append(await self.embed_text(text))
        return results
