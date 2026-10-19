"""BM25 query construction and public result conversion."""

from __future__ import annotations

import math
from collections.abc import Mapping

from engineering_rag.contracts.documents import StandardMetadata
from engineering_rag.contracts.retrieval import (
    KeywordSearchRequest,
    RetrievalResult,
    RetrievalSource,
    SearchFilters,
)

from .client import (
    ElasticsearchClient,
    exception_status,
    response_body,
    translated_backend_error,
)
from .config import ElasticsearchKeywordConfig
from .errors import (
    KeywordIndexNotFoundError,
    KeywordRequestError,
    KeywordResponseError,
    KeywordTimeoutError,
)

ALLOWED_WEIGHT_FIELDS = frozenset({"content", "context_header", "embedding_text"})


def build_search_query(request: KeywordSearchRequest) -> dict[str, object]:
    """Build a whitelist-only BM25 query with non-scoring exact filters."""

    query_text = request.query.strip()
    if not query_text:
        raise KeywordRequestError("query must not be blank")
    unknown = set(request.field_weights) - ALLOWED_WEIGHT_FIELDS
    if unknown:
        raise KeywordRequestError(f"unsupported field_weights: {', '.join(sorted(unknown))}")
    if request.field_weights and not any(weight > 0 for weight in request.field_weights.values()):
        raise KeywordRequestError("at least one field weight must be greater than zero")

    fields = (
        [
            f"{name}^{weight:g}"
            for name, weight in sorted(request.field_weights.items())
            if weight > 0
        ]
        if request.field_weights
        else ["search_text"]
    )
    bool_query: dict[str, object] = {
        "must": [{"multi_match": {"query": query_text, "fields": fields, "type": "best_fields"}}]
    }
    filters = _build_filters(request.filters)
    if filters:
        bool_query["filter"] = filters
    return {"bool": bool_query}


def search_chunks(
    client: ElasticsearchClient,
    config: ElasticsearchKeywordConfig,
    request: KeywordSearchRequest,
) -> list[RetrievalResult]:
    validated_request = KeywordSearchRequest.model_validate(request.model_dump(mode="json"))
    if validated_request.top_k > config.max_top_k:
        raise KeywordRequestError(
            f"top_k={validated_request.top_k} exceeds configured maximum {config.max_top_k}"
        )
    query = build_search_query(validated_request)
    try:
        response = client.search(
            index=validated_request.index_name,
            query=query,
            size=validated_request.top_k,
            sort=[{"_score": {"order": "desc"}}, {"chunk_id": {"order": "asc"}}],
            track_scores=True,
        )
    except Exception as exc:
        if exception_status(exc) == 404:
            raise KeywordIndexNotFoundError(
                f"Elasticsearch index {validated_request.index_name!r} does not exist"
            ) from exc
        raise translated_backend_error(
            exc, f"search failed for index {validated_request.index_name!r}"
        ) from exc
    body = response_body(response, operation="search")
    if body.get("timed_out") is True:
        raise KeywordTimeoutError(f"search timed out for index {validated_request.index_name!r}")
    shards = body.get("_shards")
    if isinstance(shards, Mapping):
        failed = shards.get("failed", 0)
        if isinstance(failed, int) and failed > 0:
            raise KeywordResponseError(f"search reported {failed} failed shard(s)")
    return _convert_hits(body, index_name=validated_request.index_name)


def _build_filters(filters: SearchFilters) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    _append_terms(result, "document_id", filters.document_ids)
    _append_terms(result, "standard.standard_code", filters.standard_codes)
    _append_terms(result, "standard.edition", filters.editions)
    _append_terms(result, "clause_number", filters.clause_numbers)
    _append_terms(result, "content_type", [value.value for value in filters.content_types])
    if filters.is_explanation is not None:
        result.append({"term": {"is_explanation": filters.is_explanation}})
    if filters.is_mandatory is not None:
        result.append({"term": {"is_mandatory": filters.is_mandatory}})
    return result


def _append_terms(target: list[dict[str, object]], field: str, values: list[object]) -> None:
    if values:
        target.append({"terms": {field: values}})


def _convert_hits(body: Mapping[str, object], *, index_name: str) -> list[RetrievalResult]:
    hits_container = body.get("hits")
    if not isinstance(hits_container, Mapping):
        raise KeywordResponseError("search response is missing hits")
    raw_hits = hits_container.get("hits")
    if not isinstance(raw_hits, list):
        raise KeywordResponseError("search response hits.hits must be a list")

    results: list[RetrievalResult] = []
    for rank, raw_hit in enumerate(raw_hits, start=1):
        if not isinstance(raw_hit, Mapping):
            raise KeywordResponseError("search hit must be an object")
        source = raw_hit.get("_source")
        score = raw_hit.get("_score")
        if (
            not isinstance(source, Mapping)
            or not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not math.isfinite(score)
        ):
            raise KeywordResponseError("search hit is missing _source or numeric _score")
        try:
            results.append(
                RetrievalResult(
                    chunk_id=_required_str(source, "chunk_id"),
                    logical_chunk_id=_required_str(source, "logical_chunk_id"),
                    document_id=_required_str(source, "document_id"),
                    content=_required_str(source, "content"),
                    standard=StandardMetadata.model_validate(source.get("standard")),
                    clause_id=_optional_str(source, "clause_id"),
                    clause_number=_optional_str(source, "clause_number"),
                    page_start=_required_int(source, "page_start"),
                    page_end=_required_int(source, "page_end"),
                    score=float(score),
                    rank=rank,
                    retrieval_source=RetrievalSource.KEYWORD,
                    score_type="bm25",
                    index_name=index_name,
                    is_explanation=source.get("is_explanation"),
                    is_mandatory=source.get("is_mandatory"),
                    content_type=source.get("content_type"),
                )
            )
        except (TypeError, ValueError) as exc:
            raise KeywordResponseError(
                f"search hit at rank {rank} cannot form RetrievalResult"
            ) from exc
    return results


def _required_str(source: Mapping[str, object], field: str) -> str:
    value = source.get(field)
    if not isinstance(value, str) or not value:
        raise KeywordResponseError(f"search hit field {field!r} must be a non-empty string")
    return value


def _optional_str(source: Mapping[str, object], field: str) -> str | None:
    value = source.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise KeywordResponseError(f"search hit field {field!r} must be a string or null")
    return value


def _required_int(source: Mapping[str, object], field: str) -> int:
    value = source.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise KeywordResponseError(f"search hit field {field!r} must be an integer")
    return value
