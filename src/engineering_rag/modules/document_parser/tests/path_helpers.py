"""Resolve test data from the test source location, independent of pytest's cwd."""

from pathlib import Path


def repository_root(test_file: str | Path) -> Path:
    """Find the nearest ancestor with the verified project marker files."""

    source = Path(test_file).resolve()
    markers = ("AGENTS.md", "pyproject.toml", "src/engineering_rag/__init__.py")
    for parent in source.parents:
        if all((parent / marker).is_file() for marker in markers):
            return parent
    raise FileNotFoundError(
        f"Cannot locate repository root from {source}; required markers: {', '.join(markers)}"
    )


def case_file_path(test_file: str | Path, filename: str) -> Path:
    """Use the maintainer-confirmed root location without alternate-directory fallback."""

    path = repository_root(test_file) / filename
    if not path.is_file():
        raise FileNotFoundError(f"Required Parser test case file is missing: {path}")
    return path
