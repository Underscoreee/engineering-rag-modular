"""Path resolution checks without generating or changing any Parser case data."""

from pathlib import Path

import pytest

from engineering_rag.modules.document_parser.tests.path_helpers import (
    case_file_path,
    repository_root,
)


@pytest.mark.parametrize(
    "filename", ["TASK_1_3_TEST_CASES.json", "TASK_1_4_TEST_CASES.json", "TASK_1_5_TEST_CASES.json"]
)
def test_case_path_is_independent_of_working_directory(
    filename: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = Path(__file__).resolve()
    expected = case_file_path(source, filename)
    monkeypatch.chdir(tmp_path)
    assert case_file_path(source, filename) == expected
    assert expected.is_absolute() and expected.is_file()
    assert all(
        (expected.parent / marker).is_file()
        for marker in ("AGENTS.md", "pyproject.toml", "src/engineering_rag/__init__.py")
    )


def test_missing_case_reports_the_required_absolute_path() -> None:
    expected = repository_root(__file__) / "missing-parser-test-case.json"
    with pytest.raises(FileNotFoundError) as error:
        case_file_path(__file__, expected.name)
    assert str(expected) in str(error.value)


def test_unrecognized_source_reports_required_repository_markers(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="AGENTS.md.*pyproject.toml"):
        repository_root(tmp_path / "outside-repository.py")
