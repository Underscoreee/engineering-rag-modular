import json
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).parents[2] / "examples"


@pytest.fixture
def document_data() -> dict[str, object]:
    return json.loads((EXAMPLES / "document.example.json").read_text(encoding="utf-8"))
