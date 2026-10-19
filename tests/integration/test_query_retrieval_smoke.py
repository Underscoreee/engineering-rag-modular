"""OFFLINE CLI tests with injected doubles; these are NOT real retrieval acceptance."""

from __future__ import annotations

import importlib
import json
import logging
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from engineering_rag.contracts.catalog import CatalogIndexScope
from engineering_rag.contracts.chunks import ChunkBatch
from engineering_rag.contracts.queries import QueryResult, RetrievalPlan
from engineering_rag.contracts.retrieval import (
    HybridSearchRequest,
    KeywordSearchRequest,
    RetrievalResult,
    RetrievalSource,
    SearchFilters,
    VectorSearchRequest,
)

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "examples/query_evaluation/v1/corpus.chunk_batch.v1.json"


@pytest.fixture
def smoke(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return importlib.import_module("query_retrieval_smoke")


def configured_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith("ERAG_LLM_"):
            monkeypatch.delenv(name)
    for name, value in {
        "ERAG_LLM_PROVIDER": "deepseek",
        "ERAG_LLM_BASE_URL": "https://api.deepseek.com",
        "ERAG_LLM_API_KEY": "offline-only-not-a-real-credential",
        "ERAG_LLM_MODEL": "test-model",
    }.items():
        monkeypatch.setenv(name, value)


def test_config_only_never_connects_or_calls_llm(smoke, monkeypatch, tmp_path) -> None:
    configured_environment(monkeypatch)

    def forbidden(*args, **kwargs):
        pytest.fail("configuration-only test attempted network/model loading")

    monkeypatch.setattr(smoke, "create_elasticsearch_client", forbidden)
    monkeypatch.setattr(smoke, "create_milvus_client", forbidden)
    monkeypatch.setattr(smoke.OpenAICompatibleLLMClient, "generate", forbidden)
    output = tmp_path / "config"
    assert smoke.main(["--config-only", "--output-dir", str(output)]) == 0
    report = json.loads((output / "diagnostics.json").read_text())
    assert report["checks"]["llm_configuration"]["status"] == "PASS"
    assert report["checks"]["llm_api"]["status"] == "NOT RUN"
    assert report["checks"]["end_to_end"]["status"] == "NOT RUN"
    assert report["status"] != "PASS"
    assert "offline-only-not-a-real-credential" not in (output / "diagnostics.json").read_text()


def test_missing_configuration_names_not_values(smoke, monkeypatch, tmp_path, capsys) -> None:
    configured_environment(monkeypatch)
    monkeypatch.delenv("ERAG_LLM_API_KEY")
    assert smoke.main(["--config-only", "--output-dir", str(tmp_path / "missing")]) == 2
    text = capsys.readouterr().out
    assert "ERAG_LLM_API_KEY" in text
    assert '"BLOCKED"' in text


def test_explicit_env_loader_is_literal_and_existing_environment_wins(smoke, tmp_path) -> None:
    path = tmp_path / ".env"
    path.write_text('ERAG_LLM_MODEL="local-model"\nERAG_LLM_API_KEY=\nMILVUS_TOKEN=$(nothing)\n')
    values = smoke.load_env_file(path, {"ERAG_LLM_MODEL": "already-set"})
    assert values == {"ERAG_LLM_MODEL": "already-set", "MILVUS_TOKEN": "$(nothing)"}
    path.write_text("UNRELATED_SECRET=do-not-read\n")
    with pytest.raises(smoke.SmokeError, match="unsupported_env_variable"):
        smoke.load_env_file(path, {})
    path.write_text("ERAG_LLM_MODEL=x\nERAG_LLM_MODEL=y\n")
    with pytest.raises(smoke.SmokeError, match="duplicate"):
        smoke.load_env_file(path, {})


def test_new_artifacts_only_and_sensitive_output_rejected(smoke, tmp_path) -> None:
    path = tmp_path / "report.json"
    smoke.write_json(path, {"ok": True}, ["secret-value"])
    with pytest.raises(FileExistsError):
        smoke.write_json(path, {"ok": False}, [])
    assert json.loads(path.read_text()) == {"ok": True}
    with pytest.raises(smoke.SmokeError, match="sensitive_output"):
        smoke.write_json(tmp_path / "unsafe.json", {"value": "secret-value"}, ["secret-value"])
    assert not (tmp_path / "unsafe.json").exists()


@pytest.mark.parametrize("secret", ['secret"quoted', r"secret\backslash", "secret中文"])
def test_json_escaped_credentials_cannot_evade_output_guard(smoke, tmp_path, secret) -> None:
    with pytest.raises(smoke.SmokeError, match="sensitive_output"):
        smoke.write_json(tmp_path / "secret.json", {"value": secret}, [secret])
    assert not (tmp_path / "secret.json").exists()


def test_existing_run_directory_is_not_touched(smoke, tmp_path) -> None:
    (tmp_path / "history.json").write_text("original")
    assert smoke.main(["--config-only", "--output-dir", str(tmp_path)]) == 2
    assert sorted(path.name for path in tmp_path.iterdir()) == ["history.json"]
    assert (tmp_path / "history.json").read_text() == "original"


def test_trace_capture_filters_and_restores_logger(smoke) -> None:
    logger = logging.getLogger("engineering_rag.modules.query")
    previous = logger.level
    with smoke.TraceEvents("trace") as capture:
        logger.info("ignored", extra={"trace_id": "other", "stage": "query_planning"})
        logger.info(
            "safe",
            extra={
                "trace_id": "trace",
                "stage": "query_planning",
                "expansion_status": "completed",
                "hyde_status": "failed",
                "degraded": True,
                "elapsed_seconds": 0.5,
                "sensitive_value": "not-collected",
            },
        )
    assert logger.level == previous
    assert capture.events == [
        {
            "stage": "query_planning",
            "elapsed_seconds": 0.5,
            "expansion_status": "completed",
            "hyde_status": "failed",
            "degraded": True,
        }
    ]
    assert "not-collected" not in repr(capture.events)


def test_ignore_rules_include_local_env_but_not_example() -> None:
    assert subprocess.run(["git", "check-ignore", "--quiet", ".env"], cwd=ROOT).returncode == 0
    assert (
        subprocess.run(["git", "check-ignore", "--quiet", ".env.example"], cwd=ROOT).returncode == 1
    )


def test_canonical_query_result_and_execute_exactly_once(smoke, monkeypatch, tmp_path) -> None:
    """This uses explicit offline doubles, never a real E2E claim."""
    configured_environment(monkeypatch)
    batch = ChunkBatch.model_validate_json(CORPUS.read_text())
    chunk = batch.chunks[0]
    backend_hit = RetrievalResult(
        **{
            key: getattr(chunk, key)
            for key in (
                "chunk_id",
                "logical_chunk_id",
                "document_id",
                "content",
                "standard",
                "clause_id",
                "clause_number",
                "page_start",
                "page_end",
            )
        },
        score=0.8,
        rank=1,
        retrieval_source="keyword",
        score_type="bm25",
        index_name="test",
    )
    closed: list[str] = []
    es = SimpleNamespace(
        info=lambda: {"version": {"number": "offline"}},
        indices=SimpleNamespace(exists=lambda **kwargs: True),
        count=lambda **kwargs: {"count": len(batch.chunks)},
        close=lambda: closed.append("es"),
    )
    milvus = SimpleNamespace(
        has_collection=lambda **kwargs: True,
        get_collection_stats=lambda **kwargs: {"row_count": len(batch.chunks)},
        close=lambda: closed.append("milvus"),
    )
    provider = SimpleNamespace(
        model_id="offline",
        model_revision="offline",
        dimension=2,
        embed_query=lambda text: [1.0, 0.0],
    )
    monkeypatch.setattr(smoke, "create_elasticsearch_client", lambda config: es)
    monkeypatch.setattr(smoke, "create_milvus_client", lambda config: milvus)
    monkeypatch.setattr(smoke, "SentenceTransformerEmbeddingProvider", lambda config: provider)
    monkeypatch.setattr(
        smoke,
        "inspect_backends",
        lambda *args, **kwargs: SimpleNamespace(
            catalog=object(), snapshot_id="offline-snapshot", diagnostics={"offline": True}
        ),
    )
    backend = SimpleNamespace(search=lambda request: [backend_hit])
    monkeypatch.setattr(smoke, "create_keyword_retrieval_service", lambda *args, **kwargs: backend)
    monkeypatch.setattr(smoke, "create_vector_retrieval_service", lambda *args, **kwargs: backend)
    monkeypatch.setattr(smoke, "create_hybrid_retrieval_service", lambda **kwargs: object())
    executions: list[str] = []

    def create_query(**kwargs):
        assert kwargs["config"].understanding.allow_test_catalog is False
        scope: CatalogIndexScope = kwargs["config"].planning.scope

        def execute(request):
            executions.append(request.question)
            hybrid = HybridSearchRequest(
                keyword=KeywordSearchRequest(
                    query=request.question, index_name=scope.keyword_index
                ),
                vector=VectorSearchRequest(
                    query=request.question, index_name=scope.vector_collection
                ),
                fusion_strategy="rrf",
                top_k=request.options.top_k,
            )
            return QueryResult(
                plan=RetrievalPlan(
                    original_question=request.question,
                    rewritten_queries=[request.question],
                    processing_intent="acquisition",
                    retrieval_mode="hybrid",
                    hybrid_request=hybrid,
                ),
                evidence=[
                    backend_hit.model_copy(update={"retrieval_source": RetrievalSource.HYBRID})
                ],
            )

        return SimpleNamespace(execute=execute)

    monkeypatch.setattr(smoke, "create_query_service", create_query)
    output = tmp_path / "offline-unit-output"
    assert (
        smoke.main(
            [
                "--corpus",
                str(CORPUS),
                "--question",
                "虚构离线问题",
                "--top-k",
                "1",
                "--output-dir",
                str(output),
            ]
        )
        == 0
    )
    result = QueryResult.model_validate_json((output / "query_result.v2.json").read_text())
    assert result.evidence[0].chunk_id == chunk.chunk_id
    assert executions == ["虚构离线问题"]
    assert set(json.loads((output / "query_result.v2.json").read_text())) == {
        "schema_version",
        "plan",
        "evidence",
    }
    assert set(closed) == {"es", "milvus"}


def test_hit_validation_rejects_identity_content_and_filter_mismatch(smoke) -> None:
    batch = ChunkBatch.model_validate_json(CORPUS.read_text())
    chunk = batch.chunks[0]
    hit = RetrievalResult(
        **{
            key: getattr(chunk, key)
            for key in (
                "chunk_id",
                "logical_chunk_id",
                "document_id",
                "content",
                "standard",
                "clause_id",
                "clause_number",
                "page_start",
                "page_end",
            )
        },
        score=1,
        rank=1,
        retrieval_source="hybrid",
        score_type="rrf",
        index_name="offline",
    )
    smoke.validate_hits([hit], batch, SearchFilters())
    with pytest.raises(smoke.SmokeError, match="hit_corpus_mismatch"):
        smoke.validate_hits(
            [hit.model_copy(update={"content": "invented"})], batch, SearchFilters()
        )
    with pytest.raises(smoke.SmokeError, match="hit_filter_mismatch"):
        smoke.validate_hits([hit], batch, SearchFilters(document_ids=["not-this-document"]))
