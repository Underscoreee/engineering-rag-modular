"""Read-only real Query -> Hybrid smoke. No indexing, fake runtime or answer generation.

Run from the repository with its editable installation. See docs/task-6.6-real-query-smoke.md.
Credentials are accepted ONLY through environment or an explicitly selected local env file.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Literal
from uuid import uuid4

from _query_smoke_backends import inspect_backends
from _query_smoke_runtime import (
    SmokeError,
    TraceEvents,
    assert_safe_text,
    check,
    environment,
    load_env_file,
    read_corpus,
    result_summary,
    safe_error_code,
    validate_hits,
    write_json,
)
from pydantic import BaseModel, ConfigDict

from engineering_rag.contracts.catalog import CatalogIndexScope
from engineering_rag.contracts.common import TraceContext
from engineering_rag.contracts.llm import StructuredLLMRequest
from engineering_rag.contracts.queries import QueryOptions, QueryRequest, QueryResult
from engineering_rag.contracts.retrieval import (
    KeywordSearchRequest,
    SearchFilters,
    VectorSearchRequest,
)
from engineering_rag.infrastructure.llm.api import LLMSettings, OpenAICompatibleLLMClient
from engineering_rag.modules.hybrid_retrieval.api import create_hybrid_retrieval_service
from engineering_rag.modules.keyword_retrieval.api import (
    ElasticsearchKeywordConfig,
    create_elasticsearch_client,
    create_keyword_retrieval_service,
)
from engineering_rag.modules.query.api import (
    EnhancementConfig,
    PlanningConfig,
    QueryConfig,
    RewriteConfig,
    UnderstandingConfig,
    create_query_service,
)
from engineering_rag.modules.vector_retrieval.api import (
    SentenceTransformerEmbeddingProvider,
    VectorRetrievalConfig,
    create_milvus_client,
    create_vector_retrieval_service,
)

REQUIRED_LLM_ENV = ("ERAG_LLM_PROVIDER", "ERAG_LLM_BASE_URL", "ERAG_LLM_API_KEY", "ERAG_LLM_MODEL")
CHECKS = (
    "llm_configuration",
    "llm_api",
    "corpus",
    "elasticsearch",
    "milvus",
    "embedding",
    "inventory",
    "keyword_search",
    "vector_search",
    "assembly",
    "end_to_end",
)


class SmokeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ready"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--corpus", type=Path, help="canonical ChunkBatch JSON, never modified")
    parser.add_argument("--config-only", action="store_true", help="no network or model loading")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--llm-smoke", action="store_true", help="one real structured API call")
    parser.add_argument("--question", help="explicitly authorizes real Query.execute LLM calls")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=50)
    parser.add_argument("--filters-json", default="{}", help="strict public SearchFilters JSON")
    parser.add_argument("--trace-id")
    parser.add_argument("--backend-query", default="结构设计", help="read-only backend probe text")
    parser.add_argument("--disable-expansion", action="store_true")
    parser.add_argument("--disable-hyde", action="store_true")
    parser.add_argument("--allow-model-download", action="store_true")
    parser.add_argument("--full-content", action="store_true")
    parser.add_argument("--output-dir", type=Path, help="new directory only; never overwrite runs")
    return parser


def run(args: argparse.Namespace, report: dict[str, object]) -> QueryResult | None:
    checks = report["checks"]
    assert isinstance(checks, dict)
    missing = [name for name in REQUIRED_LLM_ENV if not os.environ.get(name, "").strip()]
    settings = llm = None
    if missing:
        checks["llm_configuration"] = check(
            "BLOCKED", code="missing_configuration", details=missing
        )
    else:
        try:
            settings = LLMSettings.from_env()
            llm = OpenAICompatibleLLMClient(settings)
            checks["llm_configuration"] = check(
                "PASS",
                details={
                    "provider": settings.provider,
                    "model_id": settings.model_id,
                    "response_format": settings.response_format,
                    "timeout_seconds": settings.timeout_seconds,
                    "max_attempts": settings.max_attempts,
                    "transport_attempts_per_generate": 1,
                },
            )
        except Exception as error:
            checks["llm_configuration"] = check("FAIL", code=safe_error_code(error))
    if args.config_only:
        return None
    if args.llm_smoke:
        if llm is None or settings is None:
            checks["llm_api"] = check("BLOCKED", code="llm_configuration_required")
        else:
            started = monotonic()
            try:
                request = StructuredLLMRequest(
                    request_id=f"{report['trace_id']}-smoke",
                    stage="llm_smoke",
                    input={"instructions": 'Return JSON exactly {"status":"ready"}.'},
                    output_schema=SmokeOutput.model_json_schema(),
                    config=settings.structured_config("real-smoke-v1"),
                )
                response = llm.generate(request)
                response.validate_output(request, SmokeOutput)
                checks["llm_api"] = check(
                    "PASS",
                    details={
                        "model_id": response.model_id,
                        "usage": response.usage.model_dump(mode="json") if response.usage else None,
                        "elapsed_seconds": monotonic() - started,
                    },
                )
            except Exception as error:
                checks["llm_api"] = check("FAIL", code=safe_error_code(error))
    report["llm_calls"] = llm.calls if llm else []
    try:
        if args.corpus is None:
            raise SmokeError("corpus_argument_required")
        batch, corpus_sha = read_corpus(args.corpus)
    except Exception as error:
        checks["corpus"] = check("FAIL", code=safe_error_code(error))
        for stage in ("inventory", "assembly", "end_to_end"):
            checks[stage] = check("BLOCKED", code="valid_corpus_required")
        return None
    checks["corpus"] = check(
        "PASS",
        details={
            "document_ids": sorted({chunk.document_id for chunk in batch.chunks}),
            "chunk_count": len(batch.chunks),
            "sha256": corpus_sha,
        },
    )
    try:
        keyword_config = ElasticsearchKeywordConfig.from_env()
    except Exception as error:
        checks["elasticsearch"] = check("FAIL", code=safe_error_code(error))
        return None
    try:
        vector_config = VectorRetrievalConfig.from_env()
    except Exception as error:
        checks["milvus"] = check("FAIL", code=safe_error_code(error))
        return None
    if not args.allow_model_download:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    provider = SentenceTransformerEmbeddingProvider(vector_config)
    try:
        started = monotonic()
        vector = provider.embed_query(args.backend_query)
        if not vector or len(vector) != provider.dimension or not all(map(math.isfinite, vector)):
            raise SmokeError("invalid_embedding")
        checks["embedding"] = check(
            "PASS",
            details={
                "model_id": provider.model_id,
                "revision": provider.model_revision,
                "dimension": provider.dimension,
                "normalized": vector_config.normalize_embeddings,
                "query_instruction": vector_config.query_instruction,
                "elapsed_seconds": monotonic() - started,
            },
        )
    except Exception as error:
        checks["embedding"] = check("FAIL", code=safe_error_code(error))
    with ExitStack() as resources:
        keyword_client = vector_client = None
        try:
            keyword_client = create_elasticsearch_client(keyword_config)
            resources.callback(keyword_client.close)
            info = keyword_client.info()
            if not keyword_client.indices.exists(index=keyword_config.default_index):
                raise SmokeError("keyword_index_missing")
            count = keyword_client.count(index=keyword_config.default_index)["count"]
            checks["elasticsearch"] = check(
                "PASS",
                details={
                    "version": info["version"]["number"],
                    "index": keyword_config.default_index,
                    "chunk_count": count,
                },
            )
        except Exception as error:
            checks["elasticsearch"] = check("FAIL", code=safe_error_code(error))
        try:
            vector_client = create_milvus_client(vector_config)
            resources.callback(vector_client.close)
            if not vector_client.has_collection(collection_name=vector_config.default_collection):
                raise SmokeError("vector_collection_missing")
            stats = vector_client.get_collection_stats(
                collection_name=vector_config.default_collection
            )
            checks["milvus"] = check(
                "PASS",
                details={
                    "collection": vector_config.default_collection,
                    "row_count": stats.get("row_count"),
                },
            )
        except Exception as error:
            checks["milvus"] = check("FAIL", code=safe_error_code(error))
        snapshot = None
        if all(
            checks[name]["status"] == "PASS" for name in ("elasticsearch", "milvus", "embedding")
        ):
            try:
                snapshot = inspect_backends(
                    batch,
                    keyword_client=keyword_client,
                    vector_client=vector_client,
                    keyword_config=keyword_config,
                    vector_config=vector_config,
                    provider=provider,
                    keyword_index=keyword_config.default_index,
                    vector_collection=vector_config.default_collection,
                    corpus_sha256=corpus_sha,
                )
                checks["inventory"] = check("PASS", details=snapshot.diagnostics)
            except Exception as error:
                checks["inventory"] = check("FAIL", code=safe_error_code(error))
        else:
            checks["inventory"] = check("BLOCKED", code="backend_or_embedding_required")
        if snapshot is None:
            checks["assembly"] = check("BLOCKED", code="verified_inventory_required")
            if args.question:
                checks["end_to_end"] = check("BLOCKED", code="verified_inventory_required")
            report["llm_calls"] = llm.calls if llm else []
            return None
        keyword = create_keyword_retrieval_service(keyword_config, client=keyword_client)
        vector_service = create_vector_retrieval_service(
            vector_config,
            client=vector_client,
            embedding_provider=provider,
        )
        for stage, service, request in (
            (
                "keyword_search",
                keyword,
                KeywordSearchRequest(
                    query=args.backend_query,
                    top_k=3,
                    index_name=keyword_config.default_index,
                ),
            ),
            (
                "vector_search",
                vector_service,
                VectorSearchRequest(
                    query=args.backend_query,
                    top_k=3,
                    index_name=vector_config.default_collection,
                    embedding_model_id=provider.model_id,
                ),
            ),
        ):
            started = monotonic()
            try:
                hits = service.search(request)
                validate_hits(hits, batch, request.filters)
                checks[stage] = check(
                    "PASS" if hits else "FAIL",
                    code=None if hits else "no_probe_hits",
                    details={
                        "elapsed_seconds": monotonic() - started,
                        "hits": [hit.model_dump(mode="json", exclude={"content"}) for hit in hits],
                    },
                )
            except Exception as error:
                checks[stage] = check("FAIL", code=safe_error_code(error))
        if llm is None or settings is None:
            checks["assembly"] = check("BLOCKED", code="llm_configuration_required")
            if args.question:
                checks["end_to_end"] = check("BLOCKED", code="llm_configuration_required")
            return None
        hybrid = create_hybrid_retrieval_service(
            keyword_service=keyword, vector_service=vector_service
        )
        scope = CatalogIndexScope(
            keyword_index=keyword_config.default_index,
            vector_collection=vector_config.default_collection,
        )
        query_config = QueryConfig(
            understanding=UnderstandingConfig(
                llm=settings.structured_config("understanding-real-v1"),
                scope=scope,
                max_attempts=settings.max_attempts,
            ),
            rewrite=RewriteConfig(
                llm=settings.structured_config("rewrite-real-v1"),
                max_attempts=settings.max_attempts,
            ),
            enhancement=EnhancementConfig(
                expansion_llm=settings.structured_config("expansion-real-v1"),
                hyde_llm=settings.structured_config("hyde-real-v1"),
                enable_expansion=not args.disable_expansion,
                enable_hyde=not args.disable_hyde,
            ),
            planning=PlanningConfig(
                scope=scope,
                candidate_k=args.candidate_k,
                keyword_candidate_limit=keyword_config.max_top_k,
                vector_candidate_limit=min(vector_config.max_top_k, vector_config.search_ef),
                embedding_model_id=provider.model_id,
            ),
        )
        service = create_query_service(
            llm=llm, catalog=snapshot.catalog, hybrid_service=hybrid, config=query_config
        )
        checks["assembly"] = check("PASS", details={"catalog_snapshot_id": snapshot.snapshot_id})
        if args.preflight_only or not args.question:
            report["llm_calls"] = llm.calls
            return None
        if any(checks[stage]["status"] != "PASS" for stage in ("keyword_search", "vector_search")):
            checks["end_to_end"] = check("BLOCKED", code="backend_search_required")
            return None
        if args.llm_smoke and checks["llm_api"]["status"] != "PASS":
            checks["end_to_end"] = check("BLOCKED", code="llm_smoke_failed")
            return None
        request = QueryRequest(
            question=args.question,
            filters=SearchFilters.model_validate_json(args.filters_json),
            options=QueryOptions(top_k=args.top_k),
            trace=TraceContext(trace_id=str(report["trace_id"])),
        )
        started = monotonic()
        with TraceEvents(str(report["trace_id"])) as events:
            try:
                # One execute call. Calling plan first would duplicate paid LLM work.
                result = service.execute(request)
                validate_hits(result.evidence, batch, result.plan.hybrid_request.keyword.filters)
                checks["end_to_end"] = check(
                    "PASS" if result.evidence else "FAIL",
                    code=None if result.evidence else "no_query_hits",
                )
                report["result_summary"] = result_summary(result, full_content=args.full_content)
                return result
            except Exception as error:
                checks["end_to_end"] = check("FAIL", code=safe_error_code(error))
                return None
            finally:
                report["events"] = events.events
                report["llm_calls"] = llm.calls
                report["query_elapsed_seconds"] = monotonic() - started


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.top_k <= 0 or args.candidate_k < args.top_k:
        parser.error("require 0 < top-k <= candidate-k")
    if args.config_only and (args.question or args.llm_smoke):
        parser.error("--config-only cannot call the LLM")
    if args.preflight_only and args.question:
        parser.error("--preflight-only cannot execute --question")
    try:
        SearchFilters.model_validate_json(args.filters_json)
        if args.question is not None and not args.question.strip():
            raise ValueError("blank question")
        if not args.backend_query.strip():
            raise ValueError("blank backend query")
    except ValueError:
        parser.error("invalid question/backend-query or SearchFilters JSON (values not displayed)")
    trace_id = args.trace_id or uuid4().hex
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = args.output_dir or Path("data/eval/task6_6/runs") / f"smoke-{stamp}-{uuid4().hex[:8]}"
    report: dict[str, object] = {
        "task": "6.6",
        "trace_id": trace_id,
        "requested_question": args.question,
        "created_at": datetime.now(UTC).isoformat(),
        "checks": {name: check("NOT RUN") for name in CHECKS},
        "is_quality_evaluation": False,
    }
    values = dict(os.environ)
    secrets: list[str] = []
    result = None
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError:
        print("FAIL: output_directory_exists_or_unavailable; no historical artifacts changed")
        return 2
    try:
        if args.env_file:
            values = load_env_file(args.env_file, values)
        secrets = [
            values.get(name, "")
            for name in ("ERAG_LLM_API_KEY", "ELASTICSEARCH_API_KEY", "MILVUS_TOKEN")
        ]
        with environment(values):
            result = run(args, report)
    except Exception as error:
        report["fatal_error"] = safe_error_code(error)
    checks = report["checks"]
    report["status"] = "PASS" if checks["end_to_end"]["status"] == "PASS" else "PARTIAL"
    try:
        if result is not None:
            write_json(output / "query_result.v2.json", result.model_dump(mode="json"), secrets)
        write_json(output / "preflight.json", {"checks": checks, "trace_id": trace_id}, secrets)
        write_json(output / "diagnostics.json", report, secrets)
        rendered = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
        assert_safe_text(rendered, secrets)
        print(rendered)
    except Exception:
        print("FAIL: report_output_rejected_or_unavailable (no credentials displayed)")
        return 2
    if args.config_only:
        return 0 if checks["llm_configuration"]["status"] == "PASS" else 2
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
