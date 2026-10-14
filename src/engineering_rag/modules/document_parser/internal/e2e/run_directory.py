"""Immutable run-directory claiming and an atomic single-writer lease."""

from __future__ import annotations

import json
import os
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from uuid import uuid4

from .path_safety import lexical_absolute, reject_symlink_components


class RunDirectoryLease(AbstractContextManager[Path]):
    """Claim a new run or exclusively resume an existing run."""

    def __init__(self, requested: Path, *, resume: bool) -> None:
        self.run_dir = lexical_absolute(requested)
        self.lock_path = self.run_dir / ".task1_6_run.lock"
        self._lock_descriptor: int | None = None
        self._lock_inode: int | None = None
        self._claim(resume=resume)

    def _claim(self, *, resume: bool) -> None:
        reject_symlink_components(self.run_dir.parent)
        self.run_dir.parent.mkdir(parents=True, exist_ok=True)
        reject_symlink_components(self.run_dir.parent)
        if resume:
            reject_symlink_components(self.run_dir)
            if not self.run_dir.is_dir() or not (self.run_dir / "run_manifest.json").is_file():
                raise FileNotFoundError("resume requires an existing run manifest")
        else:
            try:
                self.run_dir.mkdir()
            except FileExistsError as exc:
                raise FileExistsError(
                    f"run directory already exists and is immutable; use --resume: {self.run_dir}"
                ) from exc
        reject_symlink_components(self.run_dir)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.lock_path, flags, 0o600)
        except FileExistsError as exc:
            raise RuntimeError(
                f"run directory already has an active writer: {self.run_dir}"
            ) from exc
        payload = json.dumps(
            {
                "pid": os.getpid(),
                "acquired_at": datetime.now(UTC).isoformat(),
                "token": uuid4().hex,
            }
        ).encode("utf-8")
        os.write(descriptor, payload)
        os.fsync(descriptor)
        self._lock_descriptor = descriptor
        self._lock_inode = os.fstat(descriptor).st_ino

    def __enter__(self) -> Path:
        return self.run_dir

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        descriptor = self._lock_descriptor
        if descriptor is None:
            return
        try:
            metadata = os.lstat(self.lock_path)
            if metadata.st_ino == self._lock_inode:
                self.lock_path.unlink()
        except FileNotFoundError:
            pass
        finally:
            os.close(descriptor)
            self._lock_descriptor = None
