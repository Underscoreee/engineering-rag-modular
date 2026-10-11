from pathlib import Path

from engineering_rag.contracts.documents import Document

EXAMPLES = Path(__file__).parents[2] / "examples"


def test_incomplete_ocr_and_unavailable_raw_grid_are_explicit() -> None:
    document = Document.model_validate_json(
        (EXAMPLES / "document.partial.example.json").read_text(encoding="utf-8")
    )
    assert document.processing.partial is True
    assert document.pages[0].blocks == []
    assert document.pages[0].content_extraction_status.value == "not_processed"
    assert document.tables[0].raw_grid is None
    equation = document.pages[1].blocks[1].ocr.formula_group.equations[0]
    assert equation.latex is None
    assert equation.equation_number_status.value == "unknown"
