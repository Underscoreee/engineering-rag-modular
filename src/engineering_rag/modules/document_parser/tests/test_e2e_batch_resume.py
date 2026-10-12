"""Task 1.6 private batch, merge, and checkpoint contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from engineering_rag.contracts.documents import Document
from engineering_rag.modules.document_parser.internal.e2e import (
    BatchState,
    CheckpointMismatchError,
    CheckpointStore,
    DocumentMergeError,
    RunMode,
    RunState,
    SourceIdentity,
    ensure_full_document_authorized,
    merge_documents,
    plan_batches,
)
from engineering_rag.modules.document_parser.internal.e2e.models import RunStatus


def test_batch_plan_preserves_cross_page_groups_and_limit() -> None:
    pages = [
        1,
        2,
        3,
        9,
        12,
        16,
        24,
        28,
        29,
        37,
        38,
        50,
        126,
        127,
        275,
        276,
        277,
        278,
        279,
        282,
        301,
    ]
    batches = plan_batches(pages)
    assert [len(batch.pages) for batch in batches] == [20, 1]
    for protected in ((28, 29), (37, 38), (126, 127)):
        assert any(set(protected) <= set(batch.pages) for batch in batches)


def test_unapproved_full_document_plan_is_rejected() -> None:
    with pytest.raises(PermissionError, match="explicit maintainer approval"):
        ensure_full_document_authorized(
            selected_page_count=441,
            page_count=441,
            explicitly_approved=False,
        )


def test_merge_rejects_source_and_formula_identity_conflicts() -> None:
    document = Document.model_validate_json(
        Path("examples/document.partial.example.json").read_text()
    )
    document = document.model_copy(
        update={"source_file": document.source_file.model_copy(update={"sha256": "a" * 64})}
    )
    changed = document.model_copy(
        update={"source_file": document.source_file.model_copy(update={"sha256": "f" * 64})}
    )
    with pytest.raises(DocumentMergeError, match="sha256"):
        merge_documents([document, changed])
    with pytest.raises(DocumentMergeError, match="page_number"):
        merge_documents([document, document])


def test_resume_rejects_stale_configuration_and_tampered_output(tmp_path: Path) -> None:
    artifact = tmp_path / "batches" / "batch-001" / "document.partial.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}", encoding="utf-8")
    artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
    source = SourceIdentity(
        document_id="doc-1",
        file_id="file-1",
        sha256="a" * 64,
        size_bytes=1,
        page_count=1,
        standard_code="GB TEST",
    )
    now = datetime.now(UTC)
    state = RunState(
        run_id="run-1",
        mode=RunMode.REPLAY_SAVED_RAW,
        status=RunStatus.SUCCEEDED,
        created_at=now,
        updated_at=now,
        source=source,
        config_sha256="b" * 64,
        model_signature="c" * 64,
        batches=[
            BatchState(
                batch_id="batch-001",
                pages=[1],
                status=RunStatus.SUCCEEDED,
                document_path="batches/batch-001/document.partial.json",
                document_sha256=artifact_hash,
                artifact_sha256={
                    "batches/batch-001/document.partial.json": artifact_hash,
                },
            )
        ],
    )
    store = CheckpointStore(tmp_path)
    store.save(state)
    with pytest.raises(CheckpointMismatchError, match="config_sha256"):
        store.load(
            expected_source_sha256="a" * 64,
            expected_config_sha256="d" * 64,
            expected_model_signature="c" * 64,
        )
    with pytest.raises(CheckpointMismatchError, match="model_signature"):
        store.load(
            expected_source_sha256="a" * 64,
            expected_config_sha256="b" * 64,
            expected_model_signature="e" * 64,
        )
    artifact.write_text(json.dumps({"tampered": True}), encoding="utf-8")
    with pytest.raises(CheckpointMismatchError, match="output hash mismatch"):
        store.load(
            expected_source_sha256="a" * 64,
            expected_config_sha256="b" * 64,
            expected_model_signature="c" * 64,
        )
