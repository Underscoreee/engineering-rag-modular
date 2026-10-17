"""Deterministic Elasticsearch test doubles and Chunk V1 fixtures."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy

from engineering_rag.contracts.chunks import Chunk, ChunkBatch, ChunkContentType
from engineering_rag.contracts.common import SourceRef
from engineering_rag.contracts.documents import StandardMetadata
from engineering_rag.modules.keyword_retrieval.internal.config import RefreshPolicy


def make_chunk(
    chunk_id: str = "chunk-1",
    *,
    document_id: str = "doc-1",
    content: str = "混凝土构件应满足承载力要求。",
    is_explanation: bool = False,
) -> Chunk:
    block_id = f"block-{chunk_id}"
    context = "《虚构工程规范》（DEMO 1-2026）\n3.3.2"
    return Chunk(
        chunk_id=chunk_id,
        logical_chunk_id=f"logical-{chunk_id}",
        document_id=document_id,
        content=content,
        context_header=context,
        embedding_text=f"{context}\n\n{content}",
        token_count=20,
        content_type=ChunkContentType.CLAUSE,
        page_start=2,
        page_end=2,
        source_refs=[SourceRef(document_id=document_id, page_number=2, block_id=block_id)],
        source_block_ids=[block_id],
        standard=StandardMetadata(
            standard_name="虚构工程规范",
            standard_code="DEMO 1-2026",
            edition="2026版",
            revision="第一次修订",
            language="zh-CN",
        ),
        section_path=["3 承载能力"],
        section_id="section-3",
        clause_id=f"clause-{chunk_id}",
        clause_number="3.3.2",
        is_explanation=is_explanation,
        is_mandatory=None,
        formula_ids=[],
        related_asset_ids=[],
        chunking_version="clause-first-1.0.0",
    )


def make_batch(*chunks: Chunk) -> ChunkBatch:
    selected = list(chunks) or [make_chunk()]
    return ChunkBatch(
        document_id=selected[0].document_id,
        chunks=selected,
        chunking_version="clause-first-1.0.0",
        strategy_id="clause-first-v1",
    )


class FakeIndices:
    def __init__(self) -> None:
        self.mappings: dict[str, dict[str, object]] = {}
        self.create_calls: list[dict[str, object]] = []
        self.exists_exception: Exception | None = None

    def exists(self, *, index: str) -> object:
        if self.exists_exception is not None:
            raise self.exists_exception
        return index in self.mappings

    def create(
        self,
        *,
        index: str,
        settings: Mapping[str, object],
        mappings: Mapping[str, object],
    ) -> object:
        self.create_calls.append(
            {"index": index, "settings": deepcopy(settings), "mappings": deepcopy(mappings)}
        )
        self.mappings[index] = deepcopy(dict(mappings))
        return {"acknowledged": True}

    def get_mapping(self, *, index: str) -> object:
        return {index: {"mappings": deepcopy(self.mappings[index])}}

    def delete(self, *, index: str) -> object:
        self.mappings.pop(index, None)
        return {"acknowledged": True}


class FakeElasticsearchClient:
    def __init__(self) -> None:
        self.indices = FakeIndices()
        self.documents: dict[str, dict[str, dict[str, object]]] = {}
        self.bulk_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []
        self.search_calls: list[dict[str, object]] = []
        self.bulk_response: object | None = None
        self.bulk_exception: Exception | None = None
        self.search_response: object = {"hits": {"hits": []}}
        self.search_exception: Exception | None = None
        self.delete_exception: Exception | None = None
        self.delete_response: object | None = None
        self.closed = False

    def bulk(
        self,
        *,
        operations: Sequence[Mapping[str, object]],
        refresh: RefreshPolicy,
    ) -> object:
        if self.bulk_exception is not None:
            raise self.bulk_exception
        self.bulk_calls.append({"operations": deepcopy(operations), "refresh": refresh})
        items: list[dict[str, object]] = []
        for offset in range(0, len(operations), 2):
            action = operations[offset]["index"]
            assert isinstance(action, Mapping)
            index = str(action["_index"])
            chunk_id = str(action["_id"])
            self.documents.setdefault(index, {})[chunk_id] = deepcopy(dict(operations[offset + 1]))
            items.append({"index": {"_id": chunk_id, "status": 201}})
        return (
            self.bulk_response
            if self.bulk_response is not None
            else {"errors": False, "items": items}
        )

    def search(
        self,
        *,
        index: str,
        query: Mapping[str, object],
        size: int,
        sort: Sequence[Mapping[str, object]],
        track_scores: bool,
    ) -> object:
        if self.search_exception is not None:
            raise self.search_exception
        self.search_calls.append(
            {
                "index": index,
                "query": deepcopy(query),
                "size": size,
                "sort": deepcopy(sort),
                "track_scores": track_scores,
            }
        )
        return self.search_response

    def delete_by_query(
        self,
        *,
        index: str,
        query: Mapping[str, object],
        refresh: bool,
        conflicts: str,
    ) -> object:
        if self.delete_exception is not None:
            raise self.delete_exception
        self.delete_calls.append(
            {
                "index": index,
                "query": deepcopy(query),
                "refresh": refresh,
                "conflicts": conflicts,
            }
        )
        if self.delete_response is not None:
            return self.delete_response
        documents = self.documents.setdefault(index, {})
        deleted = 0
        if "term" in query:
            document_id = query["term"]["document_id"]  # type: ignore[index]
            stale_ids = [
                chunk_id
                for chunk_id, source in documents.items()
                if source.get("document_id") == document_id
            ]
        else:
            bool_query = query["bool"]  # type: ignore[index]
            document_id = bool_query["filter"][0]["term"]["document_id"]  # type: ignore[index]
            current = set(bool_query["must_not"][0]["terms"]["chunk_id"])  # type: ignore[index]
            stale_ids = [
                chunk_id
                for chunk_id, source in documents.items()
                if source.get("document_id") == document_id and chunk_id not in current
            ]
        for chunk_id in stale_ids:
            del documents[chunk_id]
            deleted += 1
        return {"deleted": deleted}

    def close(self) -> object:
        self.closed = True
        return None


class NotFoundErrorForTest(RuntimeError):
    status_code = 404


class ConnectionErrorForTest(RuntimeError):
    pass


class ConnectionTimeoutForTest(RuntimeError):
    pass
