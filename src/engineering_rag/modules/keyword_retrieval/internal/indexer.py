"""Chunk V1 conversion and Elasticsearch Bulk indexing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from engineering_rag.contracts.chunks import Chunk, ChunkBatch
from engineering_rag.contracts.common import ContractError, ErrorCode
from engineering_rag.contracts.retrieval import IndexFailure, IndexRequest, IndexResult

from .client import ElasticsearchClient, refresh_as_bool, response_body, translated_backend_error
from .config import ElasticsearchKeywordConfig
from .errors import (
    KeywordBackendError,
    KeywordIndexCreationError,
    KeywordResponseError,
    KeywordTimeoutError,
)
from .mapping import INDEX_MAPPING_VERSION, build_index_definition, validate_existing_mapping


def chunk_to_index_document(chunk: Chunk) -> dict[str, object]:
    """Preserve Chunk V1 fields and add one private BM25 text field."""

    document = chunk.model_dump(mode="json")
    document["search_text"] = chunk.embedding_text or _combine_text(
        chunk.context_header, chunk.content
    )
    return document


def index_batch(
    client: ElasticsearchClient,
    config: ElasticsearchKeywordConfig,
    batch: ChunkBatch,
    request: IndexRequest,
) -> IndexResult:
    """Upsert a batch and optionally remove stale chunks after full success."""

    validated = ChunkBatch.model_validate(batch.model_dump(mode="json"))
    validated_request = IndexRequest.model_validate(request.model_dump(mode="json"))
    if not validated.chunks:
        return IndexResult(
            index_name=validated_request.index_name,
            operation_id=validated_request.operation_id,
            attempted=0,
            indexed=0,
            index_version=INDEX_MAPPING_VERSION,
        )

    _ensure_index(client, config, validated_request.index_name)
    operations: list[Mapping[str, object]] = []
    for chunk in validated.chunks:
        operations.append(
            {"index": {"_index": validated_request.index_name, "_id": chunk.chunk_id}}
        )
        operations.append(chunk_to_index_document(chunk))

    try:
        response = client.bulk(operations=operations, refresh=config.refresh)
    except Exception as exc:
        raise translated_backend_error(
            exc, f"bulk indexing failed for index {request.index_name!r}"
        ) from exc
    result = _parse_bulk_result(response, validated_request, validated.chunks)
    if validated_request.replace_document and not result.failures:
        _delete_stale_chunks(
            client,
            config,
            index_name=validated_request.index_name,
            document_id=validated.document_id,
            current_chunk_ids=[chunk.chunk_id for chunk in validated.chunks],
        )
    return result


def _ensure_index(
    client: ElasticsearchClient,
    config: ElasticsearchKeywordConfig,
    index_name: str,
) -> None:
    try:
        exists = bool(client.indices.exists(index=index_name))
    except Exception as exc:
        raise translated_backend_error(exc, f"failed to inspect index {index_name!r}") from exc
    if not exists:
        definition = build_index_definition(config)
        try:
            client.indices.create(
                index=index_name,
                settings=definition["settings"],  # type: ignore[arg-type]
                mappings=definition["mappings"],  # type: ignore[arg-type]
            )
        except Exception as exc:
            if not _is_already_exists(exc):
                translated = translated_backend_error(exc, f"failed to create index {index_name!r}")
                if (
                    not isinstance(translated, KeywordBackendError)
                    or type(translated) is not KeywordBackendError
                ):
                    raise translated from exc
                raise KeywordIndexCreationError(f"failed to create index {index_name!r}") from exc
    try:
        mapping = client.indices.get_mapping(index=index_name)
    except Exception as exc:
        raise translated_backend_error(
            exc, f"failed to read mapping for index {index_name!r}"
        ) from exc
    validate_existing_mapping(mapping, index_name=index_name, config=config)


def _parse_bulk_result(
    response: object,
    request: IndexRequest,
    chunks: Sequence[Chunk],
) -> IndexResult:
    body = response_body(response, operation="bulk")
    if not isinstance(body.get("errors"), bool):
        raise KeywordResponseError("bulk response is missing boolean errors status")
    raw_items = body.get("items")
    if not isinstance(raw_items, list) or len(raw_items) != len(chunks):
        raise KeywordResponseError("bulk response item count does not match attempted chunks")

    failures: list[IndexFailure] = []
    indexed = 0
    for chunk, raw_item in zip(chunks, raw_items, strict=True):
        item = _bulk_item(raw_item)
        status = item.get("status")
        error = item.get("error")
        if isinstance(status, int) and 200 <= status < 300 and error is None:
            indexed += 1
            continue
        failures.append(
            IndexFailure(
                chunk_id=chunk.chunk_id,
                error=ContractError(
                    code=ErrorCode.INTERNAL,
                    message=_bulk_error_message(status, error),
                    retryable=isinstance(status, int) and (status == 429 or status >= 500),
                ),
            )
        )
    return IndexResult(
        index_name=request.index_name,
        operation_id=request.operation_id,
        attempted=len(chunks),
        indexed=indexed,
        failures=failures,
        index_version=INDEX_MAPPING_VERSION,
    )


def _bulk_item(raw_item: object) -> Mapping[str, object]:
    if not isinstance(raw_item, Mapping):
        raise KeywordResponseError("bulk response contains a non-object item")
    operation = raw_item.get("index")
    if not isinstance(operation, Mapping):
        raise KeywordResponseError("bulk response item is missing index operation data")
    return operation


def _bulk_error_message(status: object, error: object) -> str:
    if isinstance(error, Mapping):
        reason = error.get("reason")
        error_type = error.get("type")
        if isinstance(reason, str) and reason:
            return f"bulk item failed ({status}, {error_type}): {reason}"
    return f"bulk item failed with status {status}"


def _delete_stale_chunks(
    client: ElasticsearchClient,
    config: ElasticsearchKeywordConfig,
    *,
    index_name: str,
    document_id: str,
    current_chunk_ids: list[str],
) -> None:
    query: dict[str, object] = {
        "bool": {
            "filter": [{"term": {"document_id": document_id}}],
            "must_not": [{"terms": {"chunk_id": current_chunk_ids}}],
        }
    }
    try:
        response = client.delete_by_query(
            index=index_name,
            query=query,
            refresh=refresh_as_bool(config.refresh),
            conflicts="abort",
        )
    except Exception as exc:
        raise translated_backend_error(
            exc,
            f"new chunks were indexed but stale-chunk cleanup failed for {document_id!r}",
        ) from exc
    validate_delete_by_query_response(response, operation="stale-chunk cleanup")


def validate_delete_by_query_response(response: object, *, operation: str) -> Mapping[str, object]:
    """Reject timeout or shard failures even when Elasticsearch returned HTTP success."""

    body = response_body(response, operation=operation)
    if body.get("timed_out") is True:
        raise KeywordTimeoutError(f"{operation} timed out")
    failures = body.get("failures", [])
    if not isinstance(failures, list):
        raise KeywordResponseError(f"{operation} returned invalid failures data")
    if failures:
        raise KeywordBackendError(f"{operation} reported {len(failures)} shard failure(s)")
    return body


def _is_already_exists(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    return "resource_already_exists" in text or "alreadyexists" in name


def _combine_text(context_header: str | None, content: str) -> str:
    return f"{context_header}\n\n{content}" if context_header else content
