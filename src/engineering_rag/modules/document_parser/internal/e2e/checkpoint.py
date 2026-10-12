"""Atomic, hash-verified Task 1.6 checkpoints."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .models import RunState


class CheckpointMismatchError(RuntimeError):
    """Raised when resume inputs differ or a saved artifact is corrupt."""


class CheckpointStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir.resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.run_dir / "run_manifest.json"

    def save(self, state: RunState) -> None:
        payload = state.model_dump_json(indent=2).encode("utf-8") + b"\n"
        temporary = self.run_dir / ".run_manifest.json.tmp"
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def load(
        self,
        *,
        expected_source_sha256: str,
        expected_config_sha256: str,
        expected_model_signature: str,
    ) -> RunState:
        if self.path.is_symlink() or not self.path.is_file():
            raise CheckpointMismatchError("checkpoint is missing or unsafe")
        state = RunState.model_validate_json(self.path.read_text(encoding="utf-8"))
        mismatches = []
        if state.source.sha256 != expected_source_sha256:
            mismatches.append("source_sha256")
        if state.config_sha256 != expected_config_sha256:
            mismatches.append("config_sha256")
        if state.model_signature != expected_model_signature:
            mismatches.append("model_signature")
        if mismatches:
            raise CheckpointMismatchError("resume identity mismatch: " + ", ".join(mismatches))
        for batch in state.batches:
            if batch.status.value != "succeeded":
                continue
            if batch.document_path is None or batch.document_sha256 is None:
                raise CheckpointMismatchError(f"{batch.batch_id} has incomplete success metadata")
            if not batch.artifact_sha256:
                raise CheckpointMismatchError(
                    f"{batch.batch_id} has no batch artifact integrity manifest"
                )
            path = self._resolve_artifact(batch.document_path)
            if _sha256(path) != batch.document_sha256:
                raise CheckpointMismatchError(f"{batch.batch_id} output hash mismatch")
            for relative, expected_sha256 in batch.artifact_sha256.items():
                artifact = self._resolve_artifact(relative)
                if _sha256(artifact) != expected_sha256:
                    raise CheckpointMismatchError(
                        f"{batch.batch_id} artifact hash mismatch: {relative}"
                    )
        return state

    def _resolve_artifact(self, relative: str) -> Path:
        path = (self.run_dir / relative).resolve()
        if self.run_dir not in path.parents:
            raise CheckpointMismatchError("checkpoint artifact escapes run directory")
        if path.is_symlink() or not path.is_file():
            raise CheckpointMismatchError(f"checkpoint artifact is missing or unsafe: {relative}")
        return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
