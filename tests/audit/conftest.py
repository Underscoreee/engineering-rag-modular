"""Make repository scripts importable for audits launched outside the repository."""

import sys

import pytest

from engineering_rag.modules.document_parser.tests.path_helpers import repository_root


def pytest_configure(config: pytest.Config) -> None:
    root = str(repository_root(__file__))
    if root not in sys.path:
        sys.path.insert(0, root)
        config.add_cleanup(lambda: sys.path.remove(root))
