"""Tests for brute-force cosine similarity."""

from __future__ import annotations

import pytest

from job_hunter_infra.vector.similarity import cosine_similarity, find_top_k_similar


@pytest.mark.unit
class TestCosineSimilarity:
    """Test cosine similarity computation."""

    def test_identical_vectors(self) -> None:
        """Identical vectors have similarity 1.0."""
        vec = [1.0, 2.0, 3.0]
        assert cosine_similarity(vec, vec) == pytest.approx(1.0, abs=1e-6)

    def test_orthogonal_vectors(self) -> None:
        """Orthogonal vectors have similarity 0.0."""
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0, abs=1e-6)

    def test_opposite_vectors(self) -> None:
        """Opposite vectors have similarity -1.0."""
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0, abs=1e-6)

    def test_zero_vector(self) -> None:
        """Zero vector returns 0.0 similarity."""
        assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


@pytest.mark.unit
class TestFindTopKSimilar:
    """Test top-K similar vector search."""

    def test_basic_ranking(self) -> None:
        """Returns candidates ranked by similarity."""
        query = [1.0, 0.0, 0.0]
        candidates = [
            ("a", [1.0, 0.0, 0.0]),  # identical = 1.0
            ("b", [0.0, 1.0, 0.0]),  # orthogonal = 0.0
            ("c", [0.7, 0.7, 0.0]),  # partial match
        ]
        result = find_top_k_similar(query, candidates, top_k=3)
        assert result[0][0] == "a"
        assert result[0][1] == pytest.approx(1.0, abs=1e-6)

    def test_top_k_limits(self) -> None:
        """Returns at most top_k results."""
        query = [1.0, 0.0]
        candidates = [
            ("a", [1.0, 0.0]),
            ("b", [0.9, 0.1]),
            ("c", [0.8, 0.2]),
        ]
        result = find_top_k_similar(query, candidates, top_k=2)
        assert len(result) == 2

    def test_empty_candidates(self) -> None:
        """Empty candidates returns empty list."""
        result = find_top_k_similar([1.0, 0.0], [], top_k=5)
        assert result == []

    def test_zero_query_vector(self) -> None:
        """Zero query vector returns empty list."""
        result = find_top_k_similar([0.0, 0.0], [("a", [1.0, 0.0])], top_k=5)
        assert result == []
