from copy import deepcopy

import pytest

from engineering_rag.contracts.chunks import ChunkContentType
from engineering_rag.contracts.retrieval import (
    FusionStrategy,
    HybridSearchRequest,
    KeywordSearchRequest,
    RetrievalSource,
    SearchFilters,
    VectorSearchRequest,
)
from engineering_rag.modules.hybrid_retrieval.api import (
    DefaultHybridRetrievalService,
    create_hybrid_retrieval_service,
)

from .helpers import FakeKeywordService, FakeVectorService, make_result


def _request(
    *,
    strategy: FusionStrategy = FusionStrategy.RECIPROCAL_RANK_FUSION,
    keyword_weight: float = 0.5,
    vector_weight: float = 0.5,
    candidate_k: int = 20,
    top_k: int = 3,
) -> HybridSearchRequest:
    filters = SearchFilters(
        document_ids=["doc-1"],
        content_types=[ChunkContentType.CLAUSE],
        is_mandatory=True,
    )
    return HybridSearchRequest(
        keyword=KeywordSearchRequest(
            query="关键词查询",
            top_k=2,
            filters=filters,
            field_weights={"content": 2.0},
            index_name="keyword-index",
        ),
        vector=VectorSearchRequest(
            query="向量查询",
            top_k=4,
            filters=filters,
            embedding_model_id="test/model",
            index_name="vector-index",
        ),
        fusion_strategy=strategy,
        keyword_weight=keyword_weight,
        vector_weight=vector_weight,
        candidate_k=candidate_k,
        top_k=top_k,
    )


def test_service_passes_branch_requests_without_mutating_input() -> None:
    keyword = FakeKeywordService([make_result("shared", source=RetrievalSource.KEYWORD, score=4)])
    vector = FakeVectorService([make_result("shared", source=RetrievalSource.VECTOR, score=0.9)])
    service = create_hybrid_retrieval_service(keyword, vector)
    request = _request(candidate_k=17, top_k=1)
    before = deepcopy(request.model_dump(mode="json"))

    results = service.search(request)

    assert request.model_dump(mode="json") == before
    assert keyword.requests[0].top_k == 17
    assert vector.requests[0].top_k == 17
    assert keyword.requests[0].query == "关键词查询"
    assert vector.requests[0].query == "向量查询"
    assert keyword.requests[0].filters == request.keyword.filters
    assert vector.requests[0].filters == request.vector.filters
    assert keyword.requests[0].field_weights == {"content": 2.0}
    assert vector.requests[0].embedding_model_id == "test/model"
    assert len(results) == 1


def test_rrf_result_uses_hybrid_contract_fields_and_top_k() -> None:
    keyword = FakeKeywordService(
        [
            make_result("a", source=RetrievalSource.KEYWORD, score=10),
            make_result("b", source=RetrievalSource.KEYWORD, score=8),
        ]
    )
    vector = FakeVectorService(
        [
            make_result("b", source=RetrievalSource.VECTOR, score=0.9),
            make_result("c", source=RetrievalSource.VECTOR, score=0.8),
        ]
    )

    results = DefaultHybridRetrievalService(keyword, vector).search(_request(top_k=2))

    assert [item.chunk_id for item in results] == ["b", "a"]
    assert [item.rank for item in results] == [1, 2]
    assert all(item.retrieval_source == RetrievalSource.HYBRID for item in results)
    assert all(item.score_type == "rrf" for item in results)
    assert all(
        item.index_name == "hybrid(keyword=keyword-index;vector=vector-index)" for item in results
    )
    assert results[0].content == "content b"
    assert results[0].document_id == "doc-1"


def test_weighted_strategy_and_single_normal_empty_branches() -> None:
    keyword = FakeKeywordService([make_result("only", source=RetrievalSource.KEYWORD, score=10)])
    vector = FakeVectorService([])

    results = DefaultHybridRetrievalService(keyword, vector).search(
        _request(
            strategy=FusionStrategy.WEIGHTED_NORMALIZED,
            keyword_weight=0.6,
            vector_weight=0.4,
            top_k=2,
        )
    )

    assert len(results) == 1
    assert results[0].score == pytest.approx(0.3)
    assert results[0].score_type == "min_max_weighted_sum"

    assert (
        DefaultHybridRetrievalService(FakeKeywordService([]), FakeVectorService([])).search(
            _request(top_k=2)
        )
        == []
    )


def test_keyword_failure_stops_and_propagates_without_silent_fallback() -> None:
    keyword = FakeKeywordService([], error=TimeoutError("keyword unavailable"))
    vector = FakeVectorService([make_result("v", source=RetrievalSource.VECTOR, score=0.9)])

    with pytest.raises(TimeoutError, match="keyword unavailable"):
        DefaultHybridRetrievalService(keyword, vector).search(_request())

    assert vector.requests == []


def test_vector_failure_propagates_after_keyword_call() -> None:
    keyword = FakeKeywordService([make_result("k", source=RetrievalSource.KEYWORD, score=4)])
    vector = FakeVectorService([], error=RuntimeError("vector unavailable"))

    with pytest.raises(RuntimeError, match="vector unavailable"):
        DefaultHybridRetrievalService(keyword, vector).search(_request())

    assert len(keyword.requests) == 1
