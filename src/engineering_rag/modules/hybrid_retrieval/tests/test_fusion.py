import math

import pytest

from engineering_rag.contracts.retrieval import RetrievalSource
from engineering_rag.modules.hybrid_retrieval.api import FusionParameterError
from engineering_rag.modules.hybrid_retrieval.internal.candidate_merger import merge_candidates
from engineering_rag.modules.hybrid_retrieval.internal.fusion import (
    min_max_weighted_fusion,
    reciprocal_rank_fusion,
)

from .helpers import make_result


def _ids_and_scores(scored: object) -> list[tuple[str, float]]:
    return [(item.candidate.result.chunk_id, item.score) for item in scored]  # type: ignore[union-attr]


def test_rrf_uses_positions_not_source_scores_and_sums_both_branches() -> None:
    candidates = merge_candidates(
        [
            make_result("a", source=RetrievalSource.KEYWORD, score=1),
            make_result("shared", source=RetrievalSource.KEYWORD, score=9999),
        ],
        [
            make_result("shared", source=RetrievalSource.VECTOR, score=-100),
            make_result("v", source=RetrievalSource.VECTOR, score=100),
        ],
    )

    scored = reciprocal_rank_fusion(candidates, keyword_weight=0.5, vector_weight=0.5, rrf_k=60)
    values = dict(_ids_and_scores(scored))

    assert values["a"] == pytest.approx(0.5 / 61)
    assert values["v"] == pytest.approx(0.5 / 62)
    assert values["shared"] == pytest.approx(0.5 / 62 + 0.5 / 61)
    assert scored[0].candidate.result.chunk_id == "shared"


@pytest.mark.parametrize(
    ("keyword_weight", "vector_weight", "expected_first"),
    [(1.0, 0.0, "keyword"), (0.0, 1.0, "vector"), (0.7, 0.3, "keyword")],
)
def test_rrf_internal_weights_are_supported(
    keyword_weight: float, vector_weight: float, expected_first: str
) -> None:
    candidates = merge_candidates(
        [make_result("keyword", source=RetrievalSource.KEYWORD, score=5)],
        [make_result("vector", source=RetrievalSource.VECTOR, score=0.9)],
    )

    scored = reciprocal_rank_fusion(
        candidates,
        keyword_weight=keyword_weight,
        vector_weight=vector_weight,
        rrf_k=60,
    )

    assert scored[0].candidate.result.chunk_id == expected_first


def test_weighted_min_max_matches_task_example() -> None:
    candidates = merge_candidates(
        [
            make_result("A", source=RetrievalSource.KEYWORD, score=12),
            make_result("B", source=RetrievalSource.KEYWORD, score=8),
            make_result("C", source=RetrievalSource.KEYWORD, score=4),
        ],
        [
            make_result("B", source=RetrievalSource.VECTOR, score=0.92),
            make_result("C", source=RetrievalSource.VECTOR, score=0.80),
            make_result("D", source=RetrievalSource.VECTOR, score=0.68),
        ],
    )

    scored = min_max_weighted_fusion(candidates, keyword_weight=0.6, vector_weight=0.4)

    assert _ids_and_scores(scored) == pytest.approx(
        [("B", 0.7), ("A", 0.6), ("C", 0.2), ("D", 0.0)]
    )


def test_constant_or_single_branch_scores_normalize_to_half() -> None:
    candidates = merge_candidates(
        [
            make_result("b", source=RetrievalSource.KEYWORD, score=4),
            make_result("a", source=RetrievalSource.KEYWORD, score=4),
        ],
        [],
    )

    scored = min_max_weighted_fusion(candidates, keyword_weight=0.5, vector_weight=0.5)

    assert _ids_and_scores(scored) == [("a", 0.25), ("b", 0.25)]


def test_empty_candidates_and_missing_branch_are_supported() -> None:
    assert min_max_weighted_fusion([], keyword_weight=0.5, vector_weight=0.5) == []
    candidates = merge_candidates([], [make_result("v", source=RetrievalSource.VECTOR, score=0.8)])
    scored = min_max_weighted_fusion(candidates, keyword_weight=0.5, vector_weight=0.5)
    assert scored[0].score == 0.25


@pytest.mark.parametrize(
    ("keyword_weight", "vector_weight"),
    [(-0.1, 1.1), (0.0, 0.0), (0.2, 0.2), (math.inf, 0.0), (math.nan, 1.0)],
)
def test_invalid_weights_are_rejected(keyword_weight: float, vector_weight: float) -> None:
    with pytest.raises(FusionParameterError):
        reciprocal_rank_fusion(
            [],
            keyword_weight=keyword_weight,
            vector_weight=vector_weight,
            rrf_k=60,
        )


@pytest.mark.parametrize("rrf_k", [0, -1, True, 1.5])
def test_invalid_rrf_k_is_rejected(rrf_k: object) -> None:
    with pytest.raises(FusionParameterError, match="rrf_k"):
        reciprocal_rank_fusion(
            [],
            keyword_weight=0.5,
            vector_weight=0.5,
            rrf_k=rrf_k,  # type: ignore[arg-type]
        )
