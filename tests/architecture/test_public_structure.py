import importlib
from pathlib import Path

MODULES = (
    "document_parser",
    "chunking",
    "keyword_retrieval",
    "vector_retrieval",
    "hybrid_retrieval",
    "query",
    "generation",
)
ROOT = Path(__file__).parents[2]


def test_business_public_apis_import_without_external_services() -> None:
    for module in MODULES:
        imported = importlib.import_module(f"engineering_rag.modules.{module}.api")
        assert imported.__doc__


def test_each_business_module_has_interface_and_independent_test() -> None:
    base = ROOT / "src" / "engineering_rag" / "modules"
    for module in MODULES:
        assert (base / module / "INTERFACE.md").is_file()
        assert (base / module / "tests" / "test_contract.py").is_file()


def test_required_top_level_documents_exist() -> None:
    for name in (
        "architecture.md",
        "data-contracts.md",
        "dependency-rules.md",
        "development-guide.md",
        "architecture-decisions.md",
        "id-policy.md",
        "artifact-policy.md",
        "schema-changelog.md",
        "schema-freeze-checklist.md",
    ):
        assert (ROOT / "docs" / name).is_file()
