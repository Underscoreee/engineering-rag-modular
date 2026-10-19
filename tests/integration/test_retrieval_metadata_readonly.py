"""Opt-in REAL backend metadata check. No indexing, deletion or LLM calls.

Query.execute is independently covered with offline dependencies. This test wraps
real Hybrid hits in public QueryResult/GenerationRequest; it does not claim real
Query Understanding or Generation execution.
"""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import ExitStack
from pathlib import Path

import pytest
from scripts._query_smoke_backends import inspect_backends
from scripts._query_smoke_runtime import environment, load_env_file, write_json

from engineering_rag.contracts.answers import GenerationRequest
from engineering_rag.contracts.chunks import ChunkBatch
from engineering_rag.contracts.queries import QueryResult, RetrievalPlan
from engineering_rag.contracts.retrieval import (
    HybridSearchRequest,
    KeywordSearchRequest,
    SearchFilters,
    VectorSearchRequest,
)
from engineering_rag.modules.hybrid_retrieval.api import create_hybrid_retrieval_service
from engineering_rag.modules.keyword_retrieval.api import (
    ElasticsearchKeywordConfig,
    create_elasticsearch_client,
    create_keyword_retrieval_service,
)
from engineering_rag.modules.vector_retrieval.api import (
    SentenceTransformerEmbeddingProvider,
    VectorRetrievalConfig,
    create_milvus_client,
    create_vector_retrieval_service,
)

pytestmark = [
    pytest.mark.real_elasticsearch,
    pytest.mark.real_milvus,
    pytest.mark.real_embedding,
    pytest.mark.skipif(
        os.getenv("ERAG_RUN_REAL_RETRIEVAL_METADATA") != "1",
        reason="set ERAG_RUN_REAL_RETRIEVAL_METADATA=1 for real read-only backends",
    ),
]


def test_real_source_metadata_from_existing_indexes(tmp_path: Path) -> None:
    values = dict(os.environ)
    if values.get("ERAG_METADATA_ENV_FILE"):
        values = load_env_file(Path(values["ERAG_METADATA_ENV_FILE"]), values)
    if not values.get("ERAG_METADATA_CORPUS"):
        pytest.fail("ERAG_METADATA_CORPUS is required for the enabled real test")
    output = Path(values.get("ERAG_METADATA_OUTPUT", str(tmp_path / "real-metadata")))
    output.mkdir(parents=True, exist_ok=False)
    secrets = [
        values.get(name, "")
        for name in ("ELASTICSEARCH_API_KEY", "MILVUS_TOKEN", "ERAG_LLM_API_KEY")
    ]
    values.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    raw = Path(values["ERAG_METADATA_CORPUS"]).read_bytes()
    batch = ChunkBatch.model_validate_json(raw)
    by_id = {chunk.chunk_id: chunk for chunk in batch.chunks}
    query = "普通钢筋疲劳应力幅限值如何取值？"
    filters = SearchFilters(document_ids=[batch.document_id])
    with environment(values), ExitStack() as resources:
        keyword_config = ElasticsearchKeywordConfig.from_env()
        vector_config = VectorRetrievalConfig.from_env()
        assert keyword_config.url and vector_config.milvus_uri
        keyword_client = create_elasticsearch_client(keyword_config)
        resources.callback(keyword_client.close)
        vector_client = create_milvus_client(vector_config)
        resources.callback(vector_client.close)
        provider = SentenceTransformerEmbeddingProvider(vector_config)

        def inventory():
            return inspect_backends(
                batch,
                keyword_client=keyword_client,
                vector_client=vector_client,
                keyword_config=keyword_config,
                vector_config=vector_config,
                provider=provider,
                keyword_index=keyword_config.default_index,
                vector_collection=vector_config.default_collection,
                corpus_sha256=hashlib.sha256(raw).hexdigest(),
            ).diagnostics

        before = inventory()
        keyword = create_keyword_retrieval_service(keyword_config, client=keyword_client)
        vector = create_vector_retrieval_service(
            vector_config, client=vector_client, embedding_provider=provider
        )
        keyword_request = KeywordSearchRequest(
            query=query, top_k=3, filters=filters, index_name=keyword_config.default_index
        )
        vector_request = VectorSearchRequest(
            query=query, top_k=3, filters=filters, index_name=vector_config.default_collection
        )
        keyword_hits = keyword.search(keyword_request)
        vector_hits = vector.search(vector_request)
        hybrid_request = HybridSearchRequest(
            keyword=keyword_request,
            vector=vector_request,
            fusion_strategy="rrf",
            candidate_k=10,
            top_k=3,
        )
        hybrid_hits = create_hybrid_retrieval_service(keyword, vector).search(hybrid_request)
        for hits in (keyword_hits, vector_hits, hybrid_hits):
            assert hits, "real probe produced no hits"
            for hit in hits:
                chunk = by_id[hit.chunk_id]
                for name in (
                    "is_explanation",
                    "is_mandatory",
                    "content_type",
                    "document_id",
                    "logical_chunk_id",
                    "content",
                    "standard",
                    "clause_id",
                    "clause_number",
                    "page_start",
                    "page_end",
                ):
                    assert getattr(hit, name) == getattr(chunk, name), (hit.chunk_id, name)
                assert hit.schema_version == "2.0"
        assert {hit.is_explanation for hit in hybrid_hits} == {False, True}
        result = QueryResult(
            plan=RetrievalPlan(
                original_question=query,
                processing_intent="acquisition",
                retrieval_mode="hybrid",
                hybrid_request=hybrid_request,
            ),
            evidence=hybrid_hits,
        )
        restored = QueryResult.model_validate_json(result.model_dump_json())
        generation = GenerationRequest.model_validate_json(
            GenerationRequest(question=query, evidence=restored.evidence).model_dump_json()
        )
        assert generation.evidence == hybrid_hits

        baseline_status = "NOT RUN: no historical result file supplied"
        if values.get("ERAG_METADATA_BASELINE_FILE"):
            baseline = json.loads(Path(values["ERAG_METADATA_BASELINE_FILE"]).read_bytes())
            fields = ("chunk_id", "rank", "score", "clause_number", "page_start", "page_end")
            assert baseline["query"] == query
            assert [{name: getattr(hit, name) for name in fields} for hit in hybrid_hits] == [
                {name: hit[name] for name in fields} for hit in baseline["hybrid"]["hits"]
            ]
            baseline_status = "PASS: exact historical Hybrid IDs/ranks/RRF scores/pages"
        after = inventory()
        for name in (
            "keyword_inventory_sha256",
            "vector_inventory_sha256",
            "chunk_count",
            "corpus_sha256",
        ):
            assert before[name] == after[name]
        mapping = keyword_client.indices.get_mapping(index=keyword_config.default_index)
        schema = vector_client.describe_collection(collection_name=vector_config.default_collection)
        fields = (
            "chunk_id",
            "rank",
            "score",
            "clause_number",
            "page_start",
            "page_end",
            "is_explanation",
            "is_mandatory",
            "content_type",
            "schema_version",
        )
        report = {
            "status": "PASS",
            "mode": "real_readonly_backends_no_llm",
            "query_execute": "offline unit tests only; public result wrapping tested here",
            "generation_business": "NOT IMPLEMENTED",
            "before": before,
            "after": after,
            "historical_algorithm_comparison": baseline_status,
            "es_source_field_types": {
                name: mapping[keyword_config.default_index]["mappings"]["properties"][name]
                for name in ("is_explanation", "is_mandatory", "content_type")
            },
            "milvus_source_field_types": [
                item
                for item in schema["fields"]
                if item["name"] in {"is_explanation", "mandatory_state", "content_type"}
            ],
            "branches": {
                name: [{field: getattr(hit, field) for field in fields} for hit in hits]
                for name, hits in (
                    ("keyword", keyword_hits),
                    ("vector", vector_hits),
                    ("hybrid", hybrid_hits),
                )
            },
        }
        write_json(output / "report.json", report, secrets)
        write_json(output / "query_result.v2.json", result.model_dump(mode="json"), secrets)
        write_json(output / "generation_request.json", generation.model_dump(mode="json"), secrets)
        print(f"real source metadata PASS; {len(by_id)} verified chunks; {output}")
