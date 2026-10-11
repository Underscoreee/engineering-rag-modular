import ast
from pathlib import Path

SRC = Path(__file__).parents[2] / "src" / "engineering_rag"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_contracts_do_not_reverse_depend() -> None:
    for path in (SRC / "contracts").glob("*.py"):
        for imported in _imports(path):
            assert not imported.startswith("engineering_rag.modules")
            assert not imported.startswith("engineering_rag.infrastructure")


def test_business_modules_do_not_import_other_business_internals() -> None:
    modules_root = SRC / "modules"
    for path in modules_root.rglob("*.py"):
        owner = path.relative_to(modules_root).parts[0]
        for imported in _imports(path):
            prefix = "engineering_rag.modules."
            if imported.startswith(prefix) and ".internal" in imported:
                target = imported.removeprefix(prefix).split(".", 1)[0]
                assert target == owner, f"{path} illegally imports {imported}"


def test_scanner_detects_forbidden_shape() -> None:
    source = "from engineering_rag.modules.chunking.internal import Hidden"
    tree = ast.parse(source)
    node = tree.body[0]
    assert isinstance(node, ast.ImportFrom)
    assert node.module and node.module.endswith(".internal")
