import pytest

from engineering_rag.contracts.chunks import ChunkContentType
from engineering_rag.contracts.retrieval import KeywordSearchRequest, SearchFilters
from engineering_rag.modules.keyword_retrieval.internal.config import ElasticsearchKeywordConfig
from engineering_rag.modules.keyword_retrieval.internal.errors import (
    KeywordIndexNotFoundError,
    KeywordRequestError,
    KeywordResponseError,
    KeywordTimeoutError,
)
from engineering_rag.modules.keyword_retrieval.internal.indexer import chunk_to_index_document
from engineering_rag.modules.keyword_retrieval.internal.searcher import (
    build_search_query,
    search_chunks,
)

from .helpers import (
    ConnectionTimeoutForTest,
    FakeElasticsearchClient,
    NotFoundErrorForTest,
    make_chunk,
)


def test_build_search_query_uses_default_semantic_field_and_exact_filters() -> None:
    request = KeywordSearchRequest(
        query="承载力",
        top_k=3,
        index_name="chunks",
        filters=SearchFilters(
            document_ids=["doc-1"],
            standard_codes=["DEMO 1-2026"],
            editions=["2026版"],
            clause_numbers=["3.3.2"],
            content_types=[ChunkContentType.CLAUSE],
            is_explanation=False,
            is_mandatory=True,
        ),
    )

    query = build_search_query(request)

    assert query["bool"]["must"][0]["multi_match"]["fields"] == ["search_text"]
    assert query["bool"]["filter"] == [
        {"terms": {"document_id": ["doc-1"]}},
        {"terms": {"standard.standard_code": ["DEMO 1-2026"]}},
        {"terms": {"standard.edition": ["2026版"]}},
        {"terms": {"clause_number": ["3.3.2"]}},
        {"terms": {"content_type": ["clause"]}},
        {"term": {"is_explanation": False}},
        {"term": {"is_mandatory": True}},
    ]


def test_field_weights_are_whitelisted_sorted_and_applied() -> None:
    request = KeywordSearchRequest(
        query="混凝土",
        index_name="chunks",
        field_weights={"embedding_text": 1.0, "context_header": 2.5, "content": 3.0},
    )

    fields = build_search_query(request)["bool"]["must"][0]["multi_match"]["fields"]

    assert fields == ["content^3", "context_header^2.5", "embedding_text^1"]


@pytest.mark.parametrize(
    ("query", "weights"),
    [("   ", {}), ("有效查询", {"source_block_ids": 2.0}), ("有效查询", {"content": 0.0})],
)
def test_invalid_query_or_field_weights_are_rejected(query: str, weights: dict[str, float]) -> None:
    request = KeywordSearchRequest(query=query, index_name="chunks", field_weights=weights)

    with pytest.raises(KeywordRequestError):
        build_search_query(request)


def test_search_converts_real_source_score_rank_and_stable_sort_request() -> None:
    client = FakeElasticsearchClient()
    first = chunk_to_index_document(make_chunk("chunk-a"))
    second = chunk_to_index_document(make_chunk("chunk-b", content="另一条内容"))
    client.search_response = {
        "hits": {
            "hits": [
                {"_id": "chunk-a", "_score": 4.2, "_source": first},
                {"_id": "chunk-b", "_score": 4.2, "_source": second},
            ]
        }
    }

    results = search_chunks(
        client,
        ElasticsearchKeywordConfig(),
        KeywordSearchRequest(query="承载力", top_k=2, index_name="chunks"),
    )

    assert [(item.chunk_id, item.score, item.rank) for item in results] == [
        ("chunk-a", 4.2, 1),
        ("chunk-b", 4.2, 2),
    ]
    assert results[0].content == first["content"]
    assert results[0].standard.edition == "2026版"
    assert results[0].retrieval_source.value == "keyword"
    assert results[0].score_type == "bm25"
    assert client.search_calls[0]["sort"] == [
        {"_score": {"order": "desc"}},
        {"chunk_id": {"order": "asc"}},
    ]


def test_empty_hits_are_not_confused_with_backend_failure() -> None:
    results = search_chunks(
        FakeElasticsearchClient(),
        ElasticsearchKeywordConfig(),
        KeywordSearchRequest(query="没有命中", index_name="chunks"),
    )
    assert results == []


def test_top_k_limit_is_rejected_not_truncated() -> None:
    with pytest.raises(KeywordRequestError, match="exceeds"):
        search_chunks(
            FakeElasticsearchClient(),
            ElasticsearchKeywordConfig(max_top_k=5),
            KeywordSearchRequest(query="承载力", top_k=6, index_name="chunks"),
        )


def test_missing_index_and_timeout_are_distinct() -> None:
    client = FakeElasticsearchClient()
    request = KeywordSearchRequest(query="承载力", index_name="missing")
    client.search_exception = NotFoundErrorForTest("not found")
    with pytest.raises(KeywordIndexNotFoundError):
        search_chunks(client, ElasticsearchKeywordConfig(), request)

    client.search_exception = ConnectionTimeoutForTest("timed out")
    with pytest.raises(KeywordTimeoutError):
        search_chunks(client, ElasticsearchKeywordConfig(), request)


def test_invalid_hit_is_not_silently_discarded() -> None:
    client = FakeElasticsearchClient()
    client.search_response = {"hits": {"hits": [{"_score": 1.0, "_source": {}}]}}

    with pytest.raises(KeywordResponseError):
        search_chunks(
            client,
            ElasticsearchKeywordConfig(),
            KeywordSearchRequest(query="承载力", index_name="chunks"),
        )
