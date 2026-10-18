"""Pure, deterministic RRF and Min-Max weighted score fusion."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .candidate_merger import HybridCandidate
from .errors import FusionParameterError


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    candidate: HybridCandidate
    score: float


def reciprocal_rank_fusion(
    candidates: list[HybridCandidate],
    *,
    keyword_weight: float,
    vector_weight: float,
    rrf_k: int,
) -> list[ScoredCandidate]:
    """Fuse branch positions without consulting incomparable source scores."""

    _validate_weights(keyword_weight, vector_weight)
    if not isinstance(rrf_k, int) or isinstance(rrf_k, bool) or rrf_k <= 0:
        raise FusionParameterError("rrf_k must be a positive integer")
    scored: list[ScoredCandidate] = []
    for candidate in candidates:
        score = 0.0
        if candidate.keyword_rank is not None:
            score += keyword_weight / (rrf_k + candidate.keyword_rank)
        if candidate.vector_rank is not None:
            score += vector_weight / (rrf_k + candidate.vector_rank)
        _require_finite(score, "RRF score")
        scored.append(ScoredCandidate(candidate=candidate, score=score))
    return _sort(scored)


def min_max_weighted_fusion(
    candidates: list[HybridCandidate],
    *,
    keyword_weight: float,
    vector_weight: float,
) -> list[ScoredCandidate]:
    """Normalize each branch independently, then compute a weighted sum."""

    _validate_weights(keyword_weight, vector_weight)
    keyword_scores = {
        item.result.chunk_id: item.keyword_score
        for item in candidates
        if item.keyword_score is not None
    }
    vector_scores = {
        item.result.chunk_id: item.vector_score
        for item in candidates
        if item.vector_score is not None
    }
    normalized_keyword = _min_max(keyword_scores, branch="keyword")
    normalized_vector = _min_max(vector_scores, branch="vector")

    scored = []
    for candidate in candidates:
        chunk_id = candidate.result.chunk_id
        score = keyword_weight * normalized_keyword.get(
            chunk_id, 0.0
        ) + vector_weight * normalized_vector.get(chunk_id, 0.0)
        _require_finite(score, "weighted fusion score")
        scored.append(ScoredCandidate(candidate=candidate, score=score))
    return _sort(scored)


def _min_max(scores: dict[str, float], *, branch: str) -> dict[str, float]:
    if not scores:
        return {}
    for score in scores.values():
        _require_finite(score, f"{branch} source score")
    minimum = min(scores.values())
    maximum = max(scores.values())
    if maximum == minimum:
        return {chunk_id: 0.5 for chunk_id in scores}
    scale = maximum - minimum
    return {chunk_id: (score - minimum) / scale for chunk_id, score in scores.items()}


def _validate_weights(keyword_weight: float, vector_weight: float) -> None:
    for name, weight in (
        ("keyword_weight", keyword_weight),
        ("vector_weight", vector_weight),
    ):
        if isinstance(weight, bool) or not math.isfinite(weight) or weight < 0:
            raise FusionParameterError(f"{name} must be a finite non-negative number")
    if keyword_weight == 0 and vector_weight == 0:
        raise FusionParameterError("keyword_weight and vector_weight cannot both be zero")
    if not math.isclose(keyword_weight + vector_weight, 1.0, abs_tol=1e-9):
        raise FusionParameterError("keyword_weight and vector_weight must sum to 1")


def _require_finite(value: float, label: str) -> None:
    if not math.isfinite(value):
        raise FusionParameterError(f"{label} must be finite")


def _sort(scored: list[ScoredCandidate]) -> list[ScoredCandidate]:
    return sorted(scored, key=lambda item: (-item.score, item.candidate.result.chunk_id))
