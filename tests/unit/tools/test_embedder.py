"""Tests for embedder tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from job_hunter_agents.tools.embedder import CachedEmbedder, LocalEmbedder, VoyageEmbedder


@pytest.mark.unit
class TestLocalEmbedder:
    """Test LocalEmbedder lazy loading and embedding."""

    def test_model_not_loaded_on_init(self) -> None:
        """Model is not loaded until first use."""
        embedder = LocalEmbedder()
        assert embedder._model is None

    @pytest.mark.asyncio
    async def test_embed_text_returns_float_list(self) -> None:
        """embed_text returns a list of floats."""
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])

        embedder = LocalEmbedder()
        embedder._model = mock_model

        result = await embedder.embed_text("hello world")
        assert result == [0.1, 0.2, 0.3]
        mock_model.encode.assert_called_once_with("hello world")

    @pytest.mark.asyncio
    async def test_embed_batch_empty(self) -> None:
        """embed_batch returns empty list for empty input."""
        embedder = LocalEmbedder()
        result = await embedder.embed_batch([])
        assert result == []

    @pytest.mark.asyncio
    async def test_embed_batch_multiple(self) -> None:
        """embed_batch returns one vector per input text."""
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2], [0.3, 0.4]])

        embedder = LocalEmbedder()
        embedder._model = mock_model

        result = await embedder.embed_batch(["hello", "world"])
        assert len(result) == 2
        assert result[0] == [0.1, 0.2]
        assert result[1] == [0.3, 0.4]


@pytest.mark.unit
class TestVoyageEmbedder:
    """Test VoyageEmbedder API calls."""

    @pytest.mark.asyncio
    async def test_embed_batch_calls_api(self) -> None:
        """embed_batch calls Voyage API and returns embeddings."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"embedding": [0.1, 0.2]},
                {"embedding": [0.3, 0.4]},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            embedder = VoyageEmbedder(api_key="test-key")
            result = await embedder.embed_batch(["hello", "world"])

        assert result == [[0.1, 0.2], [0.3, 0.4]]

    @pytest.mark.asyncio
    async def test_embed_text_delegates_to_batch(self) -> None:
        """embed_text calls embed_batch with single element."""
        embedder = VoyageEmbedder(api_key="test-key")
        with patch.object(embedder, "embed_batch", new_callable=AsyncMock) as mock_batch:
            mock_batch.return_value = [[0.1, 0.2, 0.3]]
            result = await embedder.embed_text("hello")

        assert result == [0.1, 0.2, 0.3]
        mock_batch.assert_called_once_with(["hello"])


@pytest.mark.unit
class TestCachedEmbedder:
    """Test CachedEmbedder cache behavior."""

    @pytest.mark.asyncio
    async def test_cache_hit_skips_embedder(self) -> None:
        """Cache hit returns stored embedding without calling embedder."""
        mock_cache = AsyncMock()
        mock_cache.get.return_value = "[0.1, 0.2, 0.3]"

        mock_embedder = AsyncMock()

        cached = CachedEmbedder(embedder=mock_embedder, cache=mock_cache)
        result = await cached.embed_text("hello")

        assert result == [0.1, 0.2, 0.3]
        mock_embedder.embed_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_miss_calls_embedder_and_stores(self) -> None:
        """Cache miss calls embedder, stores result, and returns it."""
        mock_cache = AsyncMock()
        mock_cache.get.return_value = None

        mock_embedder = AsyncMock()
        mock_embedder.embed_text.return_value = [0.4, 0.5, 0.6]

        cached = CachedEmbedder(embedder=mock_embedder, cache=mock_cache)
        result = await cached.embed_text("world")

        assert result == [0.4, 0.5, 0.6]
        mock_embedder.embed_text.assert_called_once_with("world")
        mock_cache.set.assert_called_once()
