"""Readable synthetic Document helpers for Chunk V1 tests."""

from pathlib import Path

from engineering_rag.contracts.documents import Document

EXAMPLE = Path(__file__).parents[5] / "examples/document.example.json"


def example_document() -> Document:
    return Document.model_validate_json(EXAMPLE.read_text(encoding="utf-8"))


def document_with_updates(mutator):  # type: ignore[no-untyped-def]
    payload = example_document().model_dump(mode="json")
    mutator(payload)
    return Document.model_validate(payload)


def append_body_block(
    page: dict[str, object],
    *,
    block_id: str,
    text: str,
    reading_order: int,
    y_min: float,
    y_max: float,
) -> None:
    blocks = page["blocks"]
    assert isinstance(blocks, list)
    blocks.append(
        {
            "block_id": block_id,
            "block_type": "body",
            "bbox": {"x_min": 40, "y_min": y_min, "x_max": 550, "y_max": y_max},
            "reading_order": reading_order,
            "ocr": {"text": text},
            "recognition_status": "verified",
            "bbox_status": "detected",
        }
    )
