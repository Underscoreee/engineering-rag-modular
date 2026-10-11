"""Safe local subprocess execution and ZIP handling for MinerU 4.x."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from time import perf_counter
from zipfile import BadZipFile, ZipFile


class MinerUUnavailableError(RuntimeError):
    """Raised when the configured local MinerU executable is unavailable."""


class MinerUExecutionError(RuntimeError):
    """Raised when local MinerU fails, times out, or emits an unsafe bundle."""


@dataclass(frozen=True, slots=True)
class RunResult:
    elapsed_seconds: float
    stdout_path: Path
    stderr_path: Path


def run_local(
    argv: list[str],
    *,
    timeout_seconds: int,
    stdout_path: Path,
    stderr_path: Path,
    mineru_home: Path,
) -> RunResult:
    """Execute local MinerU without a shell and retain bounded diagnostic logs."""

    if not argv or any(not item for item in argv):
        raise ValueError("MinerU argv contains an empty item")
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["MINERU_HOME"] = str(mineru_home)
    environment.setdefault("NO_COLOR", "1")
    started = perf_counter()
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=environment,
        )
    except FileNotFoundError as exc:
        raise MinerUUnavailableError(f"MinerU executable not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        _write_log(stdout_path, _bounded(exc.stdout))
        _write_log(stderr_path, _bounded(exc.stderr))
        raise MinerUExecutionError(
            f"MinerU timed out after {timeout_seconds} seconds; see {stderr_path}"
        ) from exc
    _write_log(stdout_path, _bounded(completed.stdout))
    _write_log(stderr_path, _bounded(completed.stderr))
    if completed.returncode != 0:
        detail = _bounded(completed.stderr).strip() or "no diagnostic output"
        raise MinerUExecutionError(
            f"MinerU exited with code {completed.returncode}: {detail[-2000:]}"
        )
    return RunResult(perf_counter() - started, stdout_path, stderr_path)


def safe_extract_zip(archive: Path, destination: Path) -> list[Path]:
    """Extract a MinerU bundle after rejecting traversal, links, and oversized output."""

    destination.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    total = 0
    try:
        with ZipFile(archive) as bundle:
            for info in bundle.infolist():
                name = PurePosixPath(info.filename)
                if name.is_absolute() or ".." in name.parts:
                    raise MinerUExecutionError(f"unsafe ZIP member: {info.filename}")
                if info.external_attr >> 28 == 0xA:
                    raise MinerUExecutionError(f"ZIP links are not allowed: {info.filename}")
                total += info.file_size
                if total > 512 * 1024 * 1024:
                    raise MinerUExecutionError("MinerU ZIP exceeds 512 MiB extraction limit")
                target = destination.joinpath(*name.parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, target.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                extracted.append(target)
    except BadZipFile as exc:
        raise MinerUExecutionError(f"invalid MinerU ZIP: {archive}") from exc
    return extracted


def _bounded(value: str | bytes | None, limit: int = 64 * 1024) -> str:
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    return text[-limit:]


def _write_log(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")
