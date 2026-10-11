import pytest
from pydantic import ValidationError

from engineering_rag.contracts.chunks import Chunk
from engineering_rag.contracts.retrieval import (
    HybridSearchRequest,
    KeywordSearchRequest,
    RetrievalResult,
    SearchFilters,
    VectorSearchRequest,
)


def test_chunk_physical_and_logical_ids_must_differ() -> None:
    with pytest.raises(ValidationError):
        Chunk.model_validate(
            {
                "chunk_id": "same",
                "logical_chunk_id": "same",
                "document_id": "d",
                "content": "x",
                "content_type": "text",
                "page_start": 1,
                "page_end": 1,
                "source_refs": [{"document_id": "d", "page_number": 1}],
                "standard": {"standard_name": "n", "standard_code": "c"},
            }
        )


def test_search_constraints_and_filters() -> None:
    filters = SearchFilters(document_ids=["d"], is_explanation=False)
    with pytest.raises(ValidationError):
        KeywordSearchRequest(query="q", top_k=0, filters=filters, index_name="i")
    keyword = KeywordSearchRequest(query="q", filters=filters, index_name="i")
    vector = VectorSearchRequest(query="q", filters=filters, index_name="i")
    request = HybridSearchRequest(
        keyword=keyword,
        vector=vector,
        fusion_strategy="weighted_normalized",
        keyword_weight=0.4,
        vector_weight=0.6,
    )
    assert request.keyword.filters == filters
    with pytest.raises(ValidationError):
        HybridSearchRequest(
            keyword=keyword,
            vector=vector,
            fusion_strategy="weighted_normalized",
            keyword_weight=0.8,
            vector_weight=0.8,
        )


def test_retrieval_result_preserves_identity_and_score_semantics() -> None:
    result = RetrievalResult(
        chunk_id="p",
        logical_chunk_id="l",
        document_id="d",
        content="fiction",
        standard={"standard_name": "n", "standard_code": "c"},
        clause_id="cl",
        page_start=1,
        page_end=2,
        score=3.2,
        rank=1,
        retrieval_source="keyword",
        score_type="bm25",
        index_name="i",
    )
    assert (result.retrieval_source.value, result.score_type, result.rank) == ("keyword", "bm25", 1)
