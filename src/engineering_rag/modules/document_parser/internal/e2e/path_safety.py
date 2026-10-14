"""No-follow path helpers for private Task 1.6 artifacts."""

from __future__ import annotations

import os
import stat
from pathlib import Path


class UnsafeArtifactPathError(ValueError):
    """Raised when an artifact path is symbolic, escaping, or not a file."""


def lexical_absolute(path: Path) -> Path:
    """Return an absolute lexical path without resolving symbolic links."""
    return Path(os.path.abspath(os.fspath(path)))


def reject_symlink_components(path: Path) -> Path:
    """Reject any existing symbolic component, including the leaf."""
    absolute = lexical_absolute(path)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise UnsafeArtifactPathError(f"symbolic link is unsafe: {current}")
    return absolute


def contained_artifact(root: Path, relative: str) -> Path:
    """Resolve a checkpoint-relative file lexically and reject traversal/links."""
    root_absolute = reject_symlink_components(root)
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise UnsafeArtifactPathError("artifact path escapes its trusted root")
    candidate = lexical_absolute(root_absolute / relative_path)
    if os.path.commonpath((root_absolute, candidate)) != os.fspath(root_absolute):
        raise UnsafeArtifactPathError("artifact path escapes its trusted root")
    return reject_symlink_components(candidate)


def trusted_artifact(root: Path, path: Path) -> Path:
    """Require an input path to stay below a no-symlink trusted root."""
    root_absolute = reject_symlink_components(root)
    candidate = reject_symlink_components(path)
    if os.path.commonpath((root_absolute, candidate)) != os.fspath(root_absolute):
        raise UnsafeArtifactPathError(f"artifact is outside its trusted root: {candidate}")
    return candidate


def read_regular_file(path: Path, *, max_bytes: int | None = None) -> bytes:
    """Read a regular file without following the final symbolic link."""
    safe_path = reject_symlink_components(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(safe_path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise UnsafeArtifactPathError(f"artifact is not a regular file: {safe_path}")
        if max_bytes is not None and metadata.st_size > max_bytes:
            raise UnsafeArtifactPathError(f"artifact exceeds the size limit: {safe_path}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise UnsafeArtifactPathError(f"artifact exceeds the size limit: {safe_path}")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)
