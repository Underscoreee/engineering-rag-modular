import pytest

from engineering_rag.contracts.retrieval import RetrievalSource
from engineering_rag.modules.hybrid_retrieval.api import (
    CandidateConflictError,
    CandidateResultError,
)
from engineering_rag.modules.hybrid_retrieval.internal.candidate_merger import merge_candidates

from .helpers import make_result


def test_duplicate_across_branches_is_one_candidate_with_actual_positions() -> None:
    keyword = [
        make_result("a", source=RetrievalSource.KEYWORD, score=12, rank=99),
        make_result("b", source=RetrievalSource.KEYWORD, score=8, rank=99),
    ]
    vector = [
        make_result("b", source=RetrievalSource.VECTOR, score=0.9, rank=42),
        make_result("c", source=RetrievalSource.VECTOR, score=0.8, rank=42),
    ]

    merged = {item.result.chunk_id: item for item in merge_candidates(keyword, vector)}

    assert set(merged) == {"a", "b", "c"}
    assert (merged["b"].keyword_rank, merged["b"].vector_rank) == (2, 1)
    assert (merged["a"].keyword_rank, merged["a"].vector_rank) == (1, None)
    assert (merged["c"].keyword_rank, merged["c"].vector_rank) == (None, 2)


def test_same_logical_chunk_does_not_merge_distinct_physical_chunks() -> None:
    keyword = [
        make_result(
            "physical-a",
            logical_chunk_id="logical-shared",
            source=RetrievalSource.KEYWORD,
            score=2,
        )
    ]
    vector = [
        make_result(
            "physical-b",
            logical_chunk_id="logical-shared",
            source=RetrievalSource.VECTOR,
            score=0.8,
        )
    ]

    assert len(merge_candidates(keyword, vector)) == 2


@pytest.mark.parametrize("field", ["content", "document_id", "logical_chunk_id", "page_start"])
def test_conflicting_identity_is_rejected(field: str) -> None:
    keyword = make_result("same", source=RetrievalSource.KEYWORD, score=3)
    changes: dict[str, object] = {field: "different"}
    if field == "page_start":
        changes[field] = 2
    vector = make_result("same", source=RetrievalSource.VECTOR, score=0.7).model_copy(
        update=changes
    )

    with pytest.raises(CandidateConflictError, match=field):
        merge_candidates([keyword], [vector])


def test_duplicate_within_one_branch_is_rejected() -> None:
    result = make_result("same", source=RetrievalSource.KEYWORD, score=3)

    with pytest.raises(CandidateResultError, match="duplicate chunk_id"):
        merge_candidates([result, result], [])


def test_wrong_branch_source_and_non_finite_score_are_rejected() -> None:
    wrong = make_result("wrong", source=RetrievalSource.VECTOR, score=0.5)
    with pytest.raises(CandidateResultError, match="retrieval_source"):
        merge_candidates([wrong], [])

    invalid = make_result("nan", source=RetrievalSource.KEYWORD, score=float("nan"))
    with pytest.raises(CandidateResultError, match="non-finite"):
        merge_candidates([invalid], [])


def test_empty_branches_produce_empty_candidates() -> None:
    assert merge_candidates([], []) == []
