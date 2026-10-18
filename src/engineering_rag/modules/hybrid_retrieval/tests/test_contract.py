import inspect

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.protocols import HybridRetrievalService
from engineering_rag.contracts.retrieval import (
    FusionStrategy,
    HybridSearchRequest,
    KeywordSearchRequest,
    VectorSearchRequest,
)
from engineering_rag.modules.hybrid_retrieval.api import (
    DefaultHybridRetrievalService,
    create_hybrid_retrieval_service,
)


def test_protocol_is_declaration_only() -> None:
    assert HybridRetrievalService.__name__ == "HybridRetrievalService"
    assert getattr(HybridRetrievalService, "_is_protocol", False)


def test_implementation_matches_public_search_signature() -> None:
    protocol = inspect.signature(HybridRetrievalService.search)
    implementation = inspect.signature(DefaultHybridRetrievalService.search)

    assert list(protocol.parameters) == list(implementation.parameters)
    assert implementation.return_annotation == "list[RetrievalResult]"
    assert callable(create_hybrid_retrieval_service)


def _request_payload() -> dict[str, object]:
    return {
        "keyword": KeywordSearchRequest(query="q", top_k=2, index_name="keyword"),
        "vector": VectorSearchRequest(query="q", top_k=2, index_name="vector"),
        "fusion_strategy": FusionStrategy.RECIPROCAL_RANK_FUSION,
        "candidate_k": 5,
        "top_k": 2,
    }


def test_frozen_contract_rejects_unknown_strategy_and_invalid_candidate_range() -> None:
    payload = _request_payload()
    payload["fusion_strategy"] = "weighted_sum"
    with pytest.raises(ValidationError):
        HybridSearchRequest.model_validate(payload)

    payload = _request_payload()
    payload["top_k"] = 6
    with pytest.raises(ValidationError, match="top_k must not exceed candidate_k"):
        HybridSearchRequest.model_validate(payload)


def test_frozen_contract_allows_weighted_weights_but_fixes_rrf_weights() -> None:
    weighted = _request_payload()
    weighted.update(
        fusion_strategy=FusionStrategy.WEIGHTED_NORMALIZED,
        keyword_weight=0.6,
        vector_weight=0.4,
    )
    assert HybridSearchRequest.model_validate(weighted).keyword_weight == 0.6

    rrf = _request_payload()
    rrf.update(keyword_weight=0.6, vector_weight=0.4)
    with pytest.raises(ValidationError, match="RRF does not accept numeric score weights"):
        HybridSearchRequest.model_validate(rrf)
