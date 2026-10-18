"""Merge public retrieval results into private, per-branch candidate evidence."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from engineering_rag.contracts.retrieval import RetrievalResult, RetrievalSource

from .errors import CandidateConflictError, CandidateResultError

Branch = Literal["keyword", "vector"]


@dataclass(slots=True)
class HybridCandidate:
    """One physical Chunk plus its observed rank and score in each branch."""

    result: RetrievalResult
    keyword_rank: int | None = None
    keyword_score: float | None = None
    vector_rank: int | None = None
    vector_score: float | None = None


def merge_candidates(
    keyword_results: list[RetrievalResult],
    vector_results: list[RetrievalResult],
) -> list[HybridCandidate]:
    """Merge on ``chunk_id`` while rejecting ambiguous or conflicting evidence."""

    candidates: dict[str, HybridCandidate] = {}
    _merge_branch(candidates, keyword_results, branch="keyword")
    _merge_branch(candidates, vector_results, branch="vector")
    return list(candidates.values())


def _merge_branch(
    candidates: dict[str, HybridCandidate],
    results: list[RetrievalResult],
    *,
    branch: Branch,
) -> None:
    expected_source = RetrievalSource.KEYWORD if branch == "keyword" else RetrievalSource.VECTOR
    seen: set[str] = set()
    for position, result in enumerate(results, start=1):
        if result.retrieval_source != expected_source:
            raise CandidateResultError(
                f"{branch} dependency returned retrieval_source={result.retrieval_source.value!r}"
            )
        if result.chunk_id in seen:
            raise CandidateResultError(
                f"{branch} dependency returned duplicate chunk_id {result.chunk_id!r}"
            )
        if not math.isfinite(result.score):
            raise CandidateResultError(
                f"{branch} dependency returned a non-finite score for {result.chunk_id!r}"
            )
        seen.add(result.chunk_id)

        candidate = candidates.get(result.chunk_id)
        if candidate is None:
            candidate = HybridCandidate(result=result)
            candidates[result.chunk_id] = candidate
        else:
            _assert_same_identity(candidate.result, result)

        if branch == "keyword":
            candidate.keyword_rank = position
            candidate.keyword_score = result.score
        else:
            candidate.vector_rank = position
            candidate.vector_score = result.score


def _assert_same_identity(left: RetrievalResult, right: RetrievalResult) -> None:
    identity_fields = (
        "logical_chunk_id",
        "document_id",
        "content",
        "standard",
        "clause_id",
        "clause_number",
        "page_start",
        "page_end",
    )
    conflicts = [name for name in identity_fields if getattr(left, name) != getattr(right, name)]
    if conflicts:
        fields = ", ".join(conflicts)
        raise CandidateConflictError(
            f"chunk_id {left.chunk_id!r} has conflicting identity fields: {fields}"
        )
