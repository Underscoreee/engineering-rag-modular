"""Offline actual Query + Hybrid + Generation; fake LLM/backends, NOT real E2E."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts._query_smoke_runtime import SmokeError
from scripts._rag_validation import (
    ObservedLLM,
    SmokeCase,
    run_case,
    structural_metrics,
    verify_answer,
)
from scripts.rag_e2e_smoke import main, validate_isolated_targets

from engineering_rag.contracts.catalog import (
    CatalogIndexScope,
    StandardMetadataMatch,
    StandardMetadataRecord,
)
from engineering_rag.contracts.chunks import ChunkBatch
from engineering_rag.contracts.llm import (
    StructuredLLMConfig,
    StructuredLLMRequest,
    StructuredLLMResponse,
)
from engineering_rag.contracts.queries import QueryRequest
from engineering_rag.contracts.retrieval import RetrievalResult
from engineering_rag.modules.generation.api import GenerationSettings, create_generation_service
from engineering_rag.modules.hybrid_retrieval.api import create_hybrid_retrieval_service
from engineering_rag.modules.query.api import (
    EnhancementConfig,
    PlanningConfig,
    QueryConfig,
    RewriteConfig,
    UnderstandingConfig,
    create_query_service,
)

ROOT = Path(__file__).resolve().parents[2]
SCOPE = CatalogIndexScope(keyword_index="fixture_keyword", vector_collection="fixture_vector")


class Catalog:
    def __init__(self, batch):
        self.batch = batch

    def lookup(self, request):
        return StandardMetadataMatch(
            request_id=request.request_id,
            catalog_id="offline-task73",
            snapshot_id="fictional",
            is_test_fixture=True,
            status="unique",
            candidates=[
                StandardMetadataRecord(
                    record_id="demo",
                    document_id=self.batch.document_id,
                    standard=self.batch.chunks[0].standard,
                    indexed_scopes=[SCOPE],
                )
            ],
        )


class Model:
    def __init__(self, failure=None, unknown_id=False):
        self.failure, self.unknown_id = failure, unknown_id

    def generate(self, request: StructuredLLMRequest) -> StructuredLLMResponse:
        if request.stage == "query_understanding":
            data = dict(
                processing_intent="acquisition",
                context_sufficient=True,
                standards=[],
                clause_numbers=[],
                content_types=[],
                is_explanation=None,
                is_mandatory=None,
            )
        elif request.stage == "query_rewrite":
            data = dict(rewritten_query=request.input["question"], keyword_synonyms=[])
        elif request.stage == "generation":
            if self.failure:
                raise self.failure
            rows = request.input["evidence"]
            data = dict(
                answer=rows[0]["content"],
                evidence_ids=["OTHER" if self.unknown_id else rows[0]["evidence_id"]],
                grounding_status="grounded",
                limitations=[],
                quotes=[dict(evidence_id=rows[0]["evidence_id"], quoted_text=rows[0]["content"])],
            )
        else:
            raise AssertionError(f"Unexpected offline stage: {request.stage}")
        return StructuredLLMResponse(
            request_id=request.request_id, model_id=request.config.model_id, data=data
        )


class Backend:
    def __init__(self, chunks, source, error=None):
        self.chunks, self.source, self.error = chunks, source, error
        self.calls = []

    def search(self, request):
        self.calls.append(request)
        if self.error:
            raise self.error
        fields = (
            "chunk_id",
            "logical_chunk_id",
            "document_id",
            "content",
            "standard",
            "clause_id",
            "clause_number",
            "page_start",
            "page_end",
            "is_explanation",
            "is_mandatory",
            "content_type",
        )
        return [
            RetrievalResult(
                **{name: getattr(chunk, name) for name in fields},
                score=1 / rank,
                rank=rank,
                retrieval_source=self.source,
                score_type="fictional-score",
                index_name=request.index_name,
            )
            for rank, chunk in enumerate(self.chunks, 1)
        ]


def pipeline(*, kind=None, empty=False, failure=None, unknown_id=False, backend_error=None):
    batch = ChunkBatch.model_validate_json(
        (ROOT / "examples/query_evaluation/v1/corpus.chunk_batch.v1.json").read_bytes()
    )
    chunks = [
        item
        for item in batch.chunks
        if kind is None
        or item.content_type == kind
        or kind == "explanation"
        and item.is_explanation
    ]
    assert chunks
    chunks = [] if empty else chunks[:1]
    llm_config = StructuredLLMConfig(
        config_id="offline-task73", model_id="fake", timeout_seconds=1, max_output_tokens=512
    )
    observed = ObservedLLM(Model(failure, unknown_id))
    kr, vr = Backend(chunks, "keyword", backend_error), Backend(chunks, "vector", backend_error)
    query = create_query_service(
        llm=observed,
        catalog=Catalog(batch),
        hybrid_service=create_hybrid_retrieval_service(kr, vr),
        config=QueryConfig(
            understanding=UnderstandingConfig(llm=llm_config, scope=SCOPE, allow_test_catalog=True),
            rewrite=RewriteConfig(llm=llm_config),
            enhancement=EnhancementConfig(expansion_llm=llm_config, hyde_llm=llm_config),
            planning=PlanningConfig(scope=SCOPE),
        ),
    )
    generation = create_generation_service(
        llm=observed, settings=GenerationSettings(llm=llm_config, provider="fake", max_attempts=1)
    )
    case = SmokeCase(
        "offline", "fictional-only", QueryRequest(question="演示设备要求是什么？"), empty
    )
    row, answer = run_case(
        case, query=query, generation=generation, observed_llm=observed, batch=batch
    )
    return row, answer, observed, kr, vr


@pytest.mark.parametrize("kind", ["clause", "formula", "table", "explanation"])
def test_public_pipeline_actual_context_and_citations(kind):
    row, answer, observed, kr, vr = pipeline(kind=kind)
    assert row["status"] == "PASS", row
    assert answer.grounding_status == "grounded"
    assert row["retrieved_chunk_ids"] == row["included_chunk_ids"]
    assert row["valid_citations"] == row["identity_matches"] == row["raw_quotes"] == 1
    assert [request.stage for request in observed.requests] == [
        "query_understanding",
        "query_rewrite",
        "generation",
    ]
    assert len(kr.calls) == len(vr.calls) == 1


def test_empty_actual_retrieval_does_not_call_generation_model():
    row, answer, observed, kr, vr = pipeline(empty=True)
    assert row["status"] == "PASS", row
    assert answer.grounding_status == "insufficient_evidence"
    assert not answer.citations
    assert "generation" not in [request.stage for request in observed.requests]
    assert len(kr.calls) == len(vr.calls) == 1


@pytest.mark.parametrize(
    "options,stage",
    [
        ({"failure": TimeoutError()}, "generation"),
        ({"unknown_id": True}, "generation"),
        ({"backend_error": ConnectionError()}, "query"),
    ],
)
def test_failed_stage_is_not_reported_as_success(options, stage):
    row, answer, *_ = pipeline(**options)
    assert row["status"] == "FAIL" and row["failure_stage"] == stage
    assert answer is None
    assert structural_metrics([row])["citation_authorization"]["value"] is None


@pytest.mark.parametrize(
    "field,value",
    [("is_explanation", True), ("is_explanation", 0), ("is_mandatory", False)],
)
def test_observed_prompt_not_reconstructed_from_retrieval(field, value):
    row, answer, observed, *_ = pipeline()
    calls = [request for request in observed.requests if request.stage == "generation"]
    original = RetrievalResult(
        **{
            name: calls[0].input["evidence"][0][name]
            for name in (
                "chunk_id",
                "logical_chunk_id",
                "document_id",
                "content",
                "standard",
                "clause_id",
                "clause_number",
                "page_start",
                "page_end",
                "content_type",
                "is_explanation",
                "is_mandatory",
            )
        },
        score=1,
        rank=1,
        retrieval_source="hybrid",
        score_type="rrf",
        index_name="fixture",
    )
    calls[0].input["evidence"][0][field] = value
    with pytest.raises(SmokeError, match="generation_source_metadata_mismatch"):
        verify_answer(answer, [original], calls)


@pytest.mark.parametrize(
    "name", ["engineering_rag_chunks_v1", "test_task73_*", "test_task73_x", "test_task73_a,b"]
)
def test_existing_or_unsafe_target_names_are_rejected(name):
    with pytest.raises(SmokeError):
        validate_isolated_targets(name, name)


def test_existing_output_is_never_written_even_on_failure(tmp_path):
    target = tmp_path / "historical"
    target.mkdir()
    status = main(
        [
            "--env-file",
            str(tmp_path / "missing"),
            "--corpus",
            "unused",
            "--keyword-index",
            "test_task73_abcdefgh",
            "--vector-collection",
            "test_task73_abcdefgh",
            "--output-dir",
            str(target),
            "--create-isolated",
        ]
    )
    assert status == 1 and list(target.iterdir()) == []


def test_structural_metrics_are_not_gold_metrics():
    assert structural_metrics([])["claim_coverage"] is None
    assert structural_metrics([])["explanation_classification_accuracy"] is None
    assert json.dumps(structural_metrics([]))


@pytest.mark.parametrize("reuse", [False, True])
def test_existing_targets_and_reuse_inventory_gate_never_write(monkeypatch, tmp_path, reuse):
    import scripts.rag_e2e_smoke as entry

    checked = []
    es = SimpleNamespace(
        indices=SimpleNamespace(exists=lambda **kwargs: checked.append("keyword") or True),
        close=lambda: None,
    )
    mv = SimpleNamespace(
        has_collection=lambda **kwargs: checked.append("vector") or True,
        close=lambda: None,
    )
    monkeypatch.setattr(entry.LLMSettings, "from_env", lambda: object())
    monkeypatch.setattr(entry, "create_elasticsearch_client", lambda config: es)
    monkeypatch.setattr(entry, "create_milvus_client", lambda config: mv)

    class NoWrites:
        def index(self, *args, **kwargs):
            pytest.fail("Existing targets must never be indexed by either tested path")

    monkeypatch.setattr(entry, "create_keyword_retrieval_service", lambda *a, **k: NoWrites())
    monkeypatch.setattr(entry, "create_vector_retrieval_service", lambda *a, **k: NoWrites())

    def reject_inventory(*args, **kwargs):
        raise SmokeError("checked_inventory_rejection")

    monkeypatch.setattr(entry, "inspect_backends", reject_inventory)
    args = SimpleNamespace(
        corpus=ROOT / "examples/query_evaluation/v1/corpus.chunk_batch.v1.json",
        keyword_index="test_task73_abcdefgh",
        vector_collection="test_task73_abcdefgh",
        output_dir=tmp_path,
        create_isolated=not reuse,
        reuse_isolated=reuse,
    )
    code = "checked_inventory_rejection" if reuse else "isolated_target_already_exists"
    with pytest.raises(SmokeError, match=code):
        entry.execute(args, {}, [])
    assert checked == ["keyword", "vector"]
