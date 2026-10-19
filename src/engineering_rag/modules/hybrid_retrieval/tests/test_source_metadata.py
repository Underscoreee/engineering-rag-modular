"""Tri-state source metadata enrichment without any fusion-score changes."""

from copy import deepcopy

import pytest

from engineering_rag.contracts.chunks import ChunkContentType
from engineering_rag.contracts.retrieval import FusionStrategy, RetrievalSource
from engineering_rag.modules.hybrid_retrieval.api import (
    CandidateConflictError,
    create_hybrid_retrieval_service,
)
from engineering_rag.modules.hybrid_retrieval.internal.candidate_merger import merge_candidates

from .helpers import FakeKeywordService, FakeVectorService, make_result


def pair(left, right):
    keyword = make_result("shared", source=RetrievalSource.KEYWORD, score=8.0)
    vector = make_result("shared", source=RetrievalSource.VECTOR, score=0.9)
    return keyword.model_copy(update=left), vector.model_copy(update=right)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("is_explanation", True),
        ("is_explanation", False),
        ("is_mandatory", True),
        ("is_mandatory", False),
        ("content_type", ChunkContentType.TABLE),
    ],
)
@pytest.mark.parametrize(
    ("left_known", "right_known"), [(True, True), (True, False), (False, True), (False, False)]
)
def test_metadata_merge_preserves_known_values_without_mutating_inputs(
    field, value, left_known, right_known
) -> None:
    left, right = pair(
        {field: value if left_known else None}, {field: value if right_known else None}
    )
    before = deepcopy([left, right])
    result = merge_candidates([left], [right])[0].result
    assert getattr(result, field) == (value if left_known or right_known else None)
    assert [left, right] == before


@pytest.mark.parametrize(
    ("field", "left_value", "right_value"),
    [
        ("is_explanation", True, False),
        ("is_mandatory", False, True),
        ("content_type", ChunkContentType.FORMULA, ChunkContentType.TABLE),
    ],
)
@pytest.mark.parametrize("reverse_values", [False, True])
def test_metadata_conflict_is_not_silently_overwritten(
    field, left_value, right_value, reverse_values
) -> None:
    if reverse_values:
        left_value, right_value = right_value, left_value
    left, right = pair({field: left_value}, {field: right_value})
    with pytest.raises(CandidateConflictError, match=field):
        merge_candidates([left], [right])


@pytest.mark.parametrize("strategy", list(FusionStrategy))
def test_scores_ranks_and_all_old_fields_unchanged_by_metadata(strategy) -> None:
    from engineering_rag.contracts.retrieval import HybridSearchRequest

    left, right = pair({}, {})
    request = HybridSearchRequest(
        keyword={"query": "演示", "index_name": "fiction-keyword"},
        vector={"query": "演示", "index_name": "fiction_vectors"},
        fusion_strategy=strategy,
        candidate_k=3,
        top_k=3,
    )
    extra = make_result("other", source=RetrievalSource.KEYWORD, score=2.0, rank=2)
    baseline = create_hybrid_retrieval_service(
        FakeKeywordService([left, extra]), FakeVectorService([right])
    ).search(request)
    known_left = left.model_copy(
        update={"is_explanation": False, "content_type": ChunkContentType.CLAUSE}
    )
    known_right = right.model_copy(update={"is_mandatory": True})
    results = create_hybrid_retrieval_service(
        FakeKeywordService([known_left, extra]), FakeVectorService([known_right])
    ).search(request)
    exclude = {"is_explanation", "is_mandatory", "content_type"}
    assert [r.model_dump(exclude=exclude) for r in results] == [
        r.model_dump(exclude=exclude) for r in baseline
    ]
    shared = next(r for r in results if r.chunk_id == "shared")
    assert (shared.is_explanation, shared.is_mandatory, shared.content_type) == (
        False,
        True,
        ChunkContentType.CLAUSE,
    )
