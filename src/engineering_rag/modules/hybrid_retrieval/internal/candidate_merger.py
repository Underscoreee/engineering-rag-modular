"""Merge public retrieval results into private, per-branch candidate evidence."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from engineering_rag.contracts.chunks import ChunkContentType
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
        _validate_source_metadata(result)
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
            candidate.result = _merge_source_metadata(candidate.result, result)

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


def _validate_source_metadata(result: RetrievalResult) -> None:
    """Reject metadata corrupted through model_copy/mutable injected dependencies."""
    for name in ("is_explanation", "is_mandatory"):
        value = getattr(result, name)
        if value is not None and type(value) is not bool:
            raise CandidateResultError(f"invalid source metadata field {name}")
    if result.content_type is not None and not isinstance(result.content_type, ChunkContentType):
        raise CandidateResultError("invalid source metadata field content_type")


def _merge_source_metadata(left: RetrievalResult, right: RetrievalResult) -> RetrievalResult:
    """Only enrich unknown source properties; leave branch identity/scores untouched."""
    updates: dict[str, object] = {}
    for name in ("is_explanation", "is_mandatory", "content_type"):
        first, second = getattr(left, name), getattr(right, name)
        if first is not None and second is not None and first != second:
            raise CandidateConflictError(
                f"chunk_id {left.chunk_id!r} has conflicting source metadata field: {name}"
            )
        updates[name] = second if first is None else first
    return left.model_copy(update=updates)
