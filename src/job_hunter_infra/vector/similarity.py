"""Brute-force cosine similarity for SQLite mode (no pgvector)."""

from __future__ import annotations

import numpy as np


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a = np.array(vec_a, dtype=np.float32)
    b = np.array(vec_b, dtype=np.float32)
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def find_top_k_similar(
    query: list[float],
    candidates: list[tuple[str, list[float]]],
    top_k: int = 50,
) -> list[tuple[str, float]]:
    """Find top-K most similar vectors by cosine similarity.

    Args:
        query: The query embedding vector.
        candidates: List of (id, embedding) tuples.
        top_k: Number of top results to return.

    Returns:
        List of (id, similarity_score) tuples, sorted by score descending.
    """
    if not candidates:
        return []

    query_vec = np.array(query, dtype=np.float32)
    query_norm = np.linalg.norm(query_vec)
    if query_norm == 0.0:
        return []

    scores: list[tuple[str, float]] = []
    for candidate_id, embedding in candidates:
        cand_vec = np.array(embedding, dtype=np.float32)
        cand_norm = np.linalg.norm(cand_vec)
        if cand_norm == 0.0:
            continue
        sim = float(np.dot(query_vec, cand_vec) / (query_norm * cand_norm))
        scores.append((candidate_id, sim))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top_k]
