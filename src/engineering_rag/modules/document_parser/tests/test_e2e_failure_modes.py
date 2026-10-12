"""Failure injection for Task 1.6 atomicity and local engine execution."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from engineering_rag.modules.document_parser.internal.e2e import (
    BatchState,
    CheckpointStore,
    RunMode,
    RunState,
    SourceIdentity,
)
from engineering_rag.modules.document_parser.internal.e2e.models import RunStatus
from engineering_rag.modules.document_parser.internal.mineru.runner import (
    MinerUExecutionError,
    run_local,
    safe_extract_zip,
)


def test_mineru_nonzero_and_timeout_are_explicit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def nonzero(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        return subprocess.CompletedProcess(["mineru"], 7, "partial", "model failure")

    monkeypatch.setattr(subprocess, "run", nonzero)
    with pytest.raises(MinerUExecutionError, match="code 7"):
        run_local(
            ["mineru", "parse"],
            timeout_seconds=1,
            stdout_path=tmp_path / "nonzero.out",
            stderr_path=tmp_path / "nonzero.err",
            mineru_home=tmp_path,
        )
    assert (tmp_path / "nonzero.err").read_text() == "model failure"

    def timeout(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        raise subprocess.TimeoutExpired(["mineru"], 1, output="partial", stderr="slow")

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(MinerUExecutionError, match="timed out"):
        run_local(
            ["mineru", "parse"],
            timeout_seconds=1,
            stdout_path=tmp_path / "timeout.out",
            stderr_path=tmp_path / "timeout.err",
            mineru_home=tmp_path,
        )
    assert (tmp_path / "timeout.err").read_text() == "slow"


def test_corrupt_zip_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "corrupt.zip"
    archive.write_bytes(b"not-a-zip")
    with pytest.raises(MinerUExecutionError, match="invalid MinerU ZIP"):
        safe_extract_zip(archive, tmp_path / "output")


def test_checkpoint_replace_failure_keeps_last_committed_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = CheckpointStore(tmp_path)
    state = _state(RunStatus.PLANNED)
    store.save(state)
    original = store.path.read_bytes()

    def fail_replace(source: Path, destination: Path) -> None:
        del source, destination
        raise OSError("injected disk commit failure")

    monkeypatch.setattr(
        "engineering_rag.modules.document_parser.internal.e2e.checkpoint.os.replace", fail_replace
    )
    with pytest.raises(OSError, match="disk commit failure"):
        store.save(_state(RunStatus.RUNNING))
    assert store.path.read_bytes() == original


def _state(status: RunStatus) -> RunState:
    now = datetime.now(UTC)
    return RunState(
        run_id="failure-injection",
        mode=RunMode.SYNTHETIC,
        status=status,
        created_at=now,
        updated_at=now,
        source=SourceIdentity(
            document_id="doc-1",
            file_id="file-1",
            sha256="a" * 64,
            size_bytes=1,
            page_count=1,
            standard_code="GB TEST",
        ),
        config_sha256="b" * 64,
        model_signature="c" * 64,
        batches=[BatchState(batch_id="batch-001", pages=[1])],
    )
