"""Dataset validation uses fictional annotations, never production human labels."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from engineering_rag.contracts.chunks import ChunkBatch
from engineering_rag.contracts.queries import ProcessingIntent
from engineering_rag.contracts.retrieval import SearchFilters
from engineering_rag.infrastructure.evaluation.internal.dataset import (
    DATASET_FILES,
    DatasetValidationError,
    LoadedDataset,
    chunk_matches_filters,
    load_dataset,
    safe_read_json,
)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _lines(values: list[dict[str, object]]) -> str:
    return "".join(_json(value) + "\n" for value in values)


def _chunk() -> dict[str, object]:
    return {
        "chunk_id": "chunk-fictional-1",
        "logical_chunk_id": "logical-fictional-1",
        "document_id": "document-fictional",
        "content": "虚构演示设备的间距为 10 mm。",
        "embedding_text": "虚构演示设备的间距为 10 mm。",
        "token_count": 15,
        "content_type": "clause",
        "page_start": 1,
        "page_end": 1,
        "source_refs": [
            {
                "document_id": "document-fictional",
                "page_number": 1,
                "block_id": "block-fictional",
                "bbox": {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
            }
        ],
        "source_block_ids": ["block-fictional"],
        "standard": {
            "standard_name": "虚构演示标准",
            "standard_code": "DEMO 0001",
            "edition": "2026-demo",
        },
        "clause_number": "1.1.1",
        "chunking_version": "fictional-chunker-1",
    }


def _query() -> dict[str, object]:
    question = "演示设备允许间距为 10 mm 吗？"
    return {
        "query_id": "query-fictional-1",
        "query": question,
        "expected_outcome": "retrieve",
        "processing_intent": "acquisition",
        "expected_filters": {"document_ids": ["document-fictional"]},
        "annotation_status": "verified",
        "review_id": "review-query-1",
        "protected_spans": [
            {
                "start": question.index("10 mm"),
                "end": question.index("10 mm") + len("10 mm"),
                "text": "10 mm",
                "kind": "quantity",
            }
        ],
    }


def _qrel() -> dict[str, object]:
    return {
        "query_id": "query-fictional-1",
        "chunk_id": "chunk-fictional-1",
        "relevance": 3,
        "annotation_status": "verified",
        "review_id": "review-qrel-1",
    }


def _reviews() -> list[dict[str, object]]:
    common: dict[str, object] = {
        "query_id": "query-fictional-1",
        "reviewer": "fictional-test-reviewer",
        "human_verified": True,
        "reviewed_at": "2026-10-18T00:00:00Z",
        "decision": "verified",
        "rationale": "Fictional fixture attestation, not a production annotation.",
    }
    return [
        {**common, "review_id": "review-query-1"},
        {**common, "review_id": "review-qrel-1", "chunk_id": "chunk-fictional-1"},
    ]


@dataclass
class Fixture:
    directory: Path
    corpus: Path
    manifest: dict[str, object]

    def refresh(self) -> None:
        self.manifest["corpus_sha256"] = hashlib.sha256(self.corpus.read_bytes()).hexdigest()
        self.manifest["files_sha256"] = {
            name: hashlib.sha256((self.directory / name).read_bytes()).hexdigest()
            for name in DATASET_FILES
        }
        self.manifest["query_count"] = len(
            (self.directory / "queries.jsonl").read_bytes().splitlines()
        )
        self.manifest["qrels_count"] = len(
            (self.directory / "qrels.jsonl").read_bytes().splitlines()
        )
        (self.directory / "manifest.json").write_text(_json(self.manifest), encoding="utf-8")

    def rows(self, name: str, values: list[dict[str, object]]) -> None:
        (self.directory / name).write_text(_lines(values), encoding="utf-8")
        self.refresh()

    def load(self, *, formal: bool = False) -> LoadedDataset:
        return load_dataset(
            self.directory,
            corpus_path=self.corpus,
            snapshot_id="snapshot-fictional-1",
            formal=formal,
        )


@pytest.fixture
def dataset(tmp_path: Path) -> Fixture:
    directory = tmp_path / "gold"
    directory.mkdir()
    corpus = tmp_path / "corpus.json"
    batch = ChunkBatch.model_validate(
        {
            "document_id": "document-fictional",
            "chunks": [_chunk()],
            "chunking_version": "fictional-chunker-1",
            "strategy_id": "fictional-strategy",
            "source_document_artifact": {
                "artifact_id": "artifact-fictional",
                "artifact_type": "document",
                "uri": "fictional://document.json",
                "media_type": "application/json",
                "schema_version": "2.4",
                "artifact_version": "demo-1",
                "sha256": "a" * 64,
            },
        }
    )
    corpus.write_text(batch.model_dump_json(), encoding="utf-8")
    manifest: dict[str, object] = {
        "dataset_id": "fictional-dataset",
        "dataset_version": "demo-1",
        "description": "Fictional test corpus, no real standard or human gold labels.",
        "created_at": "2026-10-18T00:00:00Z",
        "corpus_snapshot_id": "snapshot-fictional-1",
        "corpus_sha256": "0" * 64,
        "chunking_version": "fictional-chunker-1",
        "document_schema_version": "2.4",
        "annotation_guidelines_version": "demo-1",
        "query_count": 1,
        "qrels_count": 1,
        "files_sha256": {},
        "is_test_fixture": True,
    }
    (directory / "queries.jsonl").write_text(_lines([_query()]), encoding="utf-8")
    (directory / "qrels.jsonl").write_text(_lines([_qrel()]), encoding="utf-8")
    (directory / "review_log.jsonl").write_text(_lines(_reviews()), encoding="utf-8")
    (directory / "annotation_guidelines.md").write_text(
        "Fictional fixture guidelines.", encoding="utf-8"
    )
    result = Fixture(directory, corpus, manifest)
    result.refresh()
    return result


def test_verified_dataset_is_bound_readonly_and_preserves_sources(dataset: Fixture) -> None:
    before = {path: path.read_bytes() for path in [dataset.corpus, *dataset.directory.iterdir()]}
    loaded = dataset.load(formal=True)
    assert loaded.formal_ready and loaded.issues == []
    assert loaded.document_ids == ["document-fictional"]
    assert loaded.batch.source_document_artifact.sha256 == "a" * 64
    assert loaded.chunks["chunk-fictional-1"].source_refs[0].bbox.y_min == 2
    assert loaded.queries[0].processing_intent is ProcessingIntent.ACQUISITION
    request = loaded.queries[0].to_request(top_k=20)
    assert request.options.top_k == 20
    assert request.filters.document_ids == []  # Never use expected filters as a model input.
    assert {path: path.read_bytes() for path in before} == before
    assert dataset.load().queries == loaded.queries


@pytest.mark.parametrize("file", ["manifest.json", *sorted(DATASET_FILES)])
def test_missing_file_has_clear_path(dataset: Fixture, file: str) -> None:
    (dataset.directory / file).unlink()
    with pytest.raises(DatasetValidationError, match=file):
        dataset.load()


def test_snapshot_mismatch_rejected_even_when_not_formal(dataset: Fixture) -> None:
    with pytest.raises(DatasetValidationError, match="corpus_snapshot_id mismatch"):
        load_dataset(dataset.directory, corpus_path=dataset.corpus, snapshot_id="wrong")


@pytest.mark.parametrize("name", ["queries.jsonl", "qrels.jsonl", "annotation_guidelines.md"])
def test_annotation_bytes_must_match_manifest(dataset: Fixture, name: str) -> None:
    with (dataset.directory / name).open("a", encoding="utf-8") as stream:
        stream.write("tampered")
    with pytest.raises(DatasetValidationError, match="SHA-256 mismatch"):
        dataset.load()


def test_corpus_bytes_must_match_manifest(dataset: Fixture) -> None:
    with dataset.corpus.open("a", encoding="utf-8") as stream:
        stream.write(" ")
    with pytest.raises(DatasetValidationError, match="corpus_sha256 mismatch"):
        dataset.load()


@pytest.mark.parametrize("field,value", [("chunking_version", "wrong"), ("schema_version", "9.0")])
def test_corpus_version_rejected(dataset: Fixture, field: str, value: str) -> None:
    raw = json.loads(dataset.corpus.read_text())
    raw[field] = value
    dataset.corpus.write_text(_json(raw), encoding="utf-8")
    dataset.refresh()
    with pytest.raises(DatasetValidationError, match="version|match"):
        dataset.load()


def test_duplicate_query_detected_with_line(dataset: Fixture) -> None:
    dataset.rows("queries.jsonl", [_query(), _query()])
    with pytest.raises(DatasetValidationError, match=r"queries.jsonl:2: duplicate query_id"):
        dataset.load()


def test_duplicate_qrel_detected(dataset: Fixture) -> None:
    dataset.rows("qrels.jsonl", [_qrel(), _qrel()])
    with pytest.raises(DatasetValidationError, match="duplicate qrel pair"):
        dataset.load()


@pytest.mark.parametrize(
    "field,value", [("query_id", "absent-query"), ("chunk_id", "absent-chunk")]
)
def test_invalid_qrel_target_fails_not_counted_as_a_miss(
    dataset: Fixture, field: str, value: str
) -> None:
    dataset.rows("qrels.jsonl", [{**_qrel(), field: value}])
    with pytest.raises(DatasetValidationError, match=f"{value}.*(unknown|absent)"):
        dataset.load()


@pytest.mark.parametrize("value", [-1, 4, True, "3", 2.0])
def test_relevance_is_strict_integer_zero_to_three(dataset: Fixture, value: object) -> None:
    dataset.rows("qrels.jsonl", [{**_qrel(), "relevance": value}])
    with pytest.raises(DatasetValidationError, match="qrels.jsonl:1.*Qrel"):
        dataset.load()


@pytest.mark.parametrize("name", ["queries.jsonl", "qrels.jsonl"])
def test_pending_annotations_never_formal(dataset: Fixture, name: str) -> None:
    row = _query() if name == "queries.jsonl" else _qrel()
    row.update(annotation_status="pending", review_id=None)
    dataset.rows(name, [row])
    loaded = dataset.load()
    assert not loaded.formal_ready
    assert any(issue.startswith("unverified_") for issue in loaded.issues)
    with pytest.raises(DatasetValidationError, match="not eligible for formal"):
        dataset.load(formal=True)


def test_empty_scaffold_inspectable_but_never_formal(dataset: Fixture) -> None:
    dataset.rows("queries.jsonl", [])
    dataset.rows("qrels.jsonl", [])
    dataset.rows("review_log.jsonl", [])
    loaded = dataset.load()
    assert loaded.issues == ["empty_dataset"] and not loaded.formal_ready
    with pytest.raises(DatasetValidationError, match="empty_dataset"):
        dataset.load(formal=True)


def test_verified_query_requires_expected_intent_and_filters(dataset: Fixture) -> None:
    row = _query()
    row.pop("processing_intent")
    dataset.rows("queries.jsonl", [row])
    with pytest.raises(DatasetValidationError, match="requires intent and expected_filters"):
        dataset.load()


def test_verified_label_requires_matching_human_review(dataset: Fixture) -> None:
    dataset.rows("review_log.jsonl", [_reviews()[0]])
    with pytest.raises(DatasetValidationError, match="missing review_id"):
        dataset.load()


@pytest.mark.parametrize(
    "field,value", [("chunk_id", "chunk-fictional-1"), ("decision", "disputed")]
)
def test_query_review_cannot_bind_to_other_subject_or_decision(
    dataset: Fixture, field: str, value: str
) -> None:
    reviews = _reviews()
    reviews[0][field] = value
    dataset.rows("review_log.jsonl", reviews)
    with pytest.raises(DatasetValidationError, match="review identity/decision"):
        dataset.load()


@pytest.mark.parametrize("value", [False, 1, "true"])
def test_review_attestation_cannot_be_machine_or_coerced(dataset: Fixture, value: object) -> None:
    reviews = _reviews()
    reviews[0]["human_verified"] = value
    dataset.rows("review_log.jsonl", reviews)
    with pytest.raises(DatasetValidationError, match="human_verified"):
        dataset.load()


def test_reject_query_not_treated_as_empty_retrieval(dataset: Fixture) -> None:
    row = _query()
    row.update(expected_outcome="reject", expected_error_code="ambiguous_scope")
    dataset.rows("queries.jsonl", [row])
    with pytest.raises(DatasetValidationError, match="reject query must not have qrels"):
        dataset.load()
    dataset.rows("qrels.jsonl", [])
    dataset.rows("review_log.jsonl", [_reviews()[0]])
    assert dataset.load(formal=True).queries[0].expected_error_code == "ambiguous_scope"


def test_retrieve_query_needs_positive_reviewed_targets(dataset: Fixture) -> None:
    dataset.rows("qrels.jsonl", [{**_qrel(), "relevance": 0}])
    assert "no_verified_relevant_targets:query-fictional-1" in dataset.load().issues
    with pytest.raises(DatasetValidationError, match="no_verified_relevant_targets"):
        dataset.load(formal=True)


@pytest.mark.parametrize("text", ['{"query_id":"a","query_id":"b"}', "[]", "{broken", "NaN"])
def test_bad_jsonl_and_duplicate_keys_have_file_line(dataset: Fixture, text: str) -> None:
    (dataset.directory / "queries.jsonl").write_text(text + "\n", encoding="utf-8")
    dataset.refresh()
    with pytest.raises(DatasetValidationError, match="queries.jsonl:1"):
        dataset.load()


def test_blank_jsonl_row_is_not_silently_ignored(dataset: Fixture) -> None:
    (dataset.directory / "queries.jsonl").write_text(_lines([_query()]) + "\n", encoding="utf-8")
    dataset.refresh()
    with pytest.raises(DatasetValidationError, match="queries.jsonl:2: blank"):
        dataset.load()


def test_hash_map_cannot_contain_path_traversal(dataset: Fixture) -> None:
    dataset.manifest["files_sha256"] = {"../secret": "a" * 64}
    (dataset.directory / "manifest.json").write_text(_json(dataset.manifest), encoding="utf-8")
    with pytest.raises(DatasetValidationError, match="must contain exactly"):
        dataset.load()


def test_file_symlink_rejected(dataset: Fixture) -> None:
    target = dataset.directory / "queries.jsonl"
    original = dataset.directory / "original-queries.jsonl"
    target.rename(original)
    target.symlink_to(original)
    with pytest.raises(DatasetValidationError, match="symbolic links"):
        dataset.load()


def test_parent_directory_symlink_rejected(dataset: Fixture) -> None:
    alias = dataset.directory.parent / "alias"
    alias.symlink_to(dataset.directory, target_is_directory=True)
    with pytest.raises(DatasetValidationError, match="symbolic links"):
        load_dataset(alias, corpus_path=dataset.corpus, snapshot_id="snapshot-fictional-1")


def test_corpus_symlink_rejected(dataset: Fixture) -> None:
    alias = dataset.corpus.parent / "alias-corpus.json"
    alias.symlink_to(dataset.corpus)
    with pytest.raises(DatasetValidationError, match="symbolic links"):
        load_dataset(dataset.directory, corpus_path=alias, snapshot_id="snapshot-fictional-1")


def test_fifo_is_rejected_without_blocking(dataset: Fixture) -> None:
    target = dataset.directory / "queries.jsonl"
    target.unlink()
    os.mkfifo(target)
    with pytest.raises(DatasetValidationError, match="regular file"):
        dataset.load()


@pytest.mark.parametrize("start,end,text", [(0, 5, "10 mm"), (0, 500, "out-of-range")])
def test_protected_span_must_match_original_coordinates(
    dataset: Fixture, start: int, end: int, text: str
) -> None:
    row = _query()
    row["protected_spans"] = [{"start": start, "end": end, "text": text, "kind": "quantity"}]
    dataset.rows("queries.jsonl", [row])
    with pytest.raises(DatasetValidationError, match="exact original query coordinates"):
        dataset.load()


def test_model_predictions_cannot_be_accepted_as_annotations(dataset: Fixture) -> None:
    dataset.rows("queries.jsonl", [{**_query(), "machine_predictions": {"intent": "acquisition"}}])
    with pytest.raises(DatasetValidationError, match="Extra inputs are not permitted"):
        dataset.load()


def test_manifest_count_cannot_hide_annotations(dataset: Fixture) -> None:
    dataset.manifest["query_count"] = 2
    (dataset.directory / "manifest.json").write_text(_json(dataset.manifest), encoding="utf-8")
    with pytest.raises(DatasetValidationError, match="query_count/qrels_count"):
        dataset.load()


@pytest.mark.parametrize("created_at", ["2026-10-18T00:00:00", "2026-10-18T08:00:00+08:00"])
def test_manifest_creation_timestamp_must_be_aware_utc(dataset: Fixture, created_at: str) -> None:
    dataset.manifest["created_at"] = created_at
    (dataset.directory / "manifest.json").write_text(_json(dataset.manifest), encoding="utf-8")
    with pytest.raises(DatasetValidationError, match="created_at"):
        dataset.load()


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("source_document_id", "another-document", "source_document_id mismatch"),
        ("source_document_sha256", "b" * 64, "source Document SHA-256 mismatch"),
    ],
)
def test_declared_source_must_match_available_corpus_provenance(
    dataset: Fixture, field: str, value: str, error: str
) -> None:
    dataset.manifest[field] = value
    dataset.refresh()
    with pytest.raises(DatasetValidationError, match=error):
        dataset.load()


def test_source_hashes_and_test_fixture_marker_preserved(dataset: Fixture) -> None:
    dataset.manifest.update(
        source_document_id="document-fictional",
        source_document_sha256="a" * 64,
        source_pdf_sha256="c" * 64,
    )
    dataset.refresh()
    loaded = dataset.load(formal=True)
    assert loaded.manifest.is_test_fixture
    assert loaded.manifest.source_pdf_sha256 == "c" * 64
    assert loaded.manifest.source_document_sha256 == loaded.batch.source_document_artifact.sha256


def test_review_ids_are_unique(dataset: Fixture) -> None:
    dataset.rows("review_log.jsonl", [*_reviews(), _reviews()[0]])
    with pytest.raises(DatasetValidationError, match="duplicate review_id"):
        dataset.load()


def test_review_cannot_target_unknown_query(dataset: Fixture) -> None:
    extra = {**_reviews()[0], "query_id": "absent", "review_id": "review-extra"}
    dataset.rows("review_log.jsonl", [*_reviews(), extra])
    with pytest.raises(DatasetValidationError, match="review_log.jsonl:3.*unknown query_id"):
        dataset.load()


def test_empty_guidelines_are_rejected(dataset: Fixture) -> None:
    (dataset.directory / "annotation_guidelines.md").write_text("  \n", encoding="utf-8")
    dataset.refresh()
    with pytest.raises(DatasetValidationError, match="empty guidelines"):
        dataset.load()


def test_invalid_utf8_has_jsonl_location(dataset: Fixture) -> None:
    (dataset.directory / "queries.jsonl").write_bytes(b"\xff")
    dataset.refresh()
    with pytest.raises(DatasetValidationError, match="queries.jsonl.*UTF-8"):
        dataset.load()


def test_manifest_does_not_auto_accept_utf16(dataset: Fixture) -> None:
    path = dataset.directory / "manifest.json"
    path.write_bytes(_json(dataset.manifest).encode("utf-16"))
    with pytest.raises(DatasetValidationError, match="manifest.json.*invalid DatasetManifest"):
        dataset.load()


@pytest.mark.parametrize("raw", ['{"id":1,"id":2}', '{"value":Infinity}', "{invalid"])
def test_safe_json_reader_rejects_ambiguous_json(tmp_path: Path, raw: str) -> None:
    path = tmp_path / "snapshot.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(DatasetValidationError, match="snapshot.json: invalid JSON"):
        safe_read_json(path)


def test_safe_json_reader_is_readonly_and_rejects_link(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.json"
    raw = '{"snapshot_id":"demo","count":2}\n'
    path.write_text(raw, encoding="utf-8")
    assert safe_read_json(path) == {"snapshot_id": "demo", "count": 2}
    assert path.read_text(encoding="utf-8") == raw
    alias = tmp_path / "alias.json"
    alias.symlink_to(path)
    with pytest.raises(DatasetValidationError, match="symbolic links"):
        safe_read_json(alias)


@pytest.mark.parametrize(
    "filters",
    [
        {"document_ids": ["different"]},
        {"standard_codes": ["OTHER 0001"]},
        {"editions": ["other"]},
        {"clause_numbers": ["2.1.1"]},
        {"content_types": ["table"]},
        {"is_explanation": True},
        {"is_mandatory": False},
        {"is_mandatory": True},
    ],
)
def test_positive_qrel_must_match_every_explicit_gold_filter(
    dataset: Fixture, filters: dict[str, object]
) -> None:
    row = _query()
    row["expected_filters"] = filters
    dataset.rows("queries.jsonl", [row])
    with pytest.raises(DatasetValidationError, match="positive qrel violates expected_filters"):
        dataset.load()


def test_grade_zero_negative_qrel_may_be_outside_scope(dataset: Fixture) -> None:
    row = _query()
    row["expected_filters"] = {"document_ids": ["other"]}
    dataset.rows("queries.jsonl", [row])
    dataset.rows("qrels.jsonl", [{**_qrel(), "relevance": 0}])
    assert not dataset.load().formal_ready


def test_grade_one_positive_qrel_cannot_be_outside_scope(dataset: Fixture) -> None:
    row = _query()
    row["expected_filters"] = {"document_ids": ["other"]}
    dataset.rows("queries.jsonl", [row])
    dataset.rows("qrels.jsonl", [{**_qrel(), "relevance": 1}])
    with pytest.raises(DatasetValidationError, match="positive qrel violates expected_filters"):
        dataset.load()


def test_duplicate_protected_span_rejected_when_loading_gold(dataset: Fixture) -> None:
    row = _query()
    row["protected_spans"] = [*row["protected_spans"], *row["protected_spans"]]
    dataset.rows("queries.jsonl", [row])
    with pytest.raises(DatasetValidationError, match="duplicate protected span"):
        dataset.load()


def test_same_protected_interval_may_have_different_kinds(dataset: Fixture) -> None:
    row = _query()
    span = row["protected_spans"][0]
    row["protected_spans"] = [span, {**span, "kind": "constraint"}]
    dataset.rows("queries.jsonl", [row])
    assert len(dataset.load().queries[0].protected_spans) == 2


def test_filter_predicate_or_within_and_across_preserves_unknown(dataset: Fixture) -> None:
    chunk = dataset.load().chunks["chunk-fictional-1"]
    filters = SearchFilters(
        document_ids=["other", "document-fictional"],
        standard_codes=["DEMO 0001"],
        editions=["2026-demo"],
        clause_numbers=["1.1.1"],
        content_types=["clause"],
        is_explanation=False,
        is_mandatory=None,
    )
    assert chunk_matches_filters(chunk, filters)
    assert chunk.is_mandatory is None
    filters.is_mandatory = False
    assert not chunk_matches_filters(chunk, filters)
    chunk.is_mandatory = False
    assert chunk_matches_filters(chunk, filters)
    filters.standard_codes = ["different"]
    assert not chunk_matches_filters(chunk, filters)
