"""ChunkBatch vectorization and transactional-order Milvus upsert."""

from __future__ import annotations

from collections.abc import Sequence

from engineering_rag.contracts.chunks import Chunk, ChunkBatch
from engineering_rag.contracts.retrieval import IndexRequest, IndexResult

from .collection_schema import COLLECTION_SCHEMA_VERSION, ensure_collection
from .config import VectorRetrievalConfig
from .embeddings import EmbeddingProvider, validate_vectors
from .errors import VectorResponseError
from .milvus_client import MilvusClientProtocol, translated_milvus_error


def index_batch(
    client: MilvusClientProtocol,
    provider: EmbeddingProvider,
    config: VectorRetrievalConfig,
    batch: ChunkBatch,
    request: IndexRequest,
) -> IndexResult:
    validated = ChunkBatch.model_validate(batch.model_dump(mode="json"))
    validated_request = IndexRequest.model_validate(request.model_dump(mode="json"))
    if not validated.chunks:
        return IndexResult(
            index_name=validated_request.index_name,
            operation_id=validated_request.operation_id,
            attempted=0,
            indexed=0,
            index_version=COLLECTION_SCHEMA_VERSION,
        )

    ensure_collection(client, config, provider, validated_request.index_name)
    all_ids = [chunk.chunk_id for chunk in validated.chunks]
    indexed = 0
    for start in range(0, len(validated.chunks), config.write_batch_size):
        chunks = validated.chunks[start : start + config.write_batch_size]
        texts = [chunk.embedding_text for chunk in chunks]
        vectors = validate_vectors(
            provider.embed_documents(texts),
            expected_count=len(chunks),
            dimension=provider.dimension,
        )
        rows = [chunk_to_row(chunk, vector) for chunk, vector in zip(chunks, vectors, strict=True)]
        try:
            response = client.upsert(collection_name=request.index_name, data=rows)
        except Exception as exc:
            raise translated_milvus_error(
                exc, f"Milvus upsert failed after {indexed} of {len(validated.chunks)} chunks"
            ) from exc
        count = _mutation_count(response, "upsert_count")
        if count != len(rows):
            raise VectorResponseError(f"Milvus reported {count} upserts for a batch of {len(rows)}")
        indexed += count

    # Snapshot cleanup happens only after every new row has been acknowledged.
    if validated_request.replace_document:
        _delete_stale_chunks(
            client,
            collection_name=validated_request.index_name,
            document_id=validated.document_id,
            current_chunk_ids=all_ids,
        )
    return IndexResult(
        index_name=validated_request.index_name,
        operation_id=validated_request.operation_id,
        attempted=len(validated.chunks),
        indexed=indexed,
        index_version=COLLECTION_SCHEMA_VERSION,
    )


def chunk_to_row(chunk: Chunk, vector: list[float]) -> dict[str, object]:
    standard = chunk.standard
    return {
        "chunk_id": chunk.chunk_id,
        "embedding": vector,
        "logical_chunk_id": chunk.logical_chunk_id,
        "document_id": chunk.document_id,
        "content": chunk.content,
        "content_type": chunk.content_type.value,
        "standard_name": standard.standard_name,
        "standard_code": standard.standard_code,
        "edition": standard.edition or "",
        "standard_revision": standard.revision or "",
        "standard_language": standard.language or "",
        "clause_id": chunk.clause_id or "",
        "clause_number": chunk.clause_number or "",
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "is_explanation": chunk.is_explanation,
        "mandatory_state": -1 if chunk.is_mandatory is None else int(chunk.is_mandatory),
        "source_refs": [ref.model_dump(mode="json") for ref in chunk.source_refs],
        "source_block_ids": chunk.source_block_ids,
        "section_path": chunk.section_path,
        "provenance": {
            "schema_version": chunk.schema_version,
            "section_id": chunk.section_id,
            "parent_chunk_id": chunk.parent_chunk_id,
            "table_id": chunk.table_id,
            "figure_id": chunk.figure_id,
            "formula_ids": chunk.formula_ids,
            "related_asset_ids": chunk.related_asset_ids,
            "chunking_version": chunk.chunking_version,
        },
    }


def _delete_stale_chunks(
    client: MilvusClientProtocol,
    *,
    collection_name: str,
    document_id: str,
    current_chunk_ids: Sequence[str],
) -> None:
    existing = client.query(
        collection_name=collection_name,
        filter=f"document_id == {quote(document_id)}",
        output_fields=["chunk_id"],
        limit=max(len(current_chunk_ids) + 10000, 16384),
        consistency_level="Strong",
    )
    stale = [
        str(row["chunk_id"])
        for row in existing
        if isinstance(row.get("chunk_id"), str) and row["chunk_id"] not in current_chunk_ids
    ]
    if stale:
        client.delete(
            collection_name=collection_name,
            filter=f"chunk_id in {json_string_list(stale)}",
        )


def quote(value: str) -> str:
    """Escape a user value as a Milvus expression string literal."""

    import json

    return json.dumps(value, ensure_ascii=False)


def json_string_list(values: Sequence[str]) -> str:
    import json

    return json.dumps(list(values), ensure_ascii=False)


def _mutation_count(response: object, key: str) -> int:
    body = getattr(response, "body", response)
    if not isinstance(body, dict):
        raise VectorResponseError("Milvus mutation returned a non-object response")
    count = body.get(key)
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise VectorResponseError(f"Milvus mutation response is missing {key}")
    return count
