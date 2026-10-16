"""Data-driven checks for the readable Chunk V1 golden cases."""

import json
from pathlib import Path

import pytest

from engineering_rag.contracts.chunks import Chunk, ChunkingConfig
from engineering_rag.contracts.documents import Document
from engineering_rag.modules.chunking.api import create_chunking_service

from .support import append_body_block

MODULE_ROOT = Path(__file__).parents[1]
REPOSITORY_ROOT = Path(__file__).parents[5]
GOLDEN_PATH = MODULE_ROOT / "evaluation/golden_cases.v1.json"
GOLDEN = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _document(variant: str) -> Document:
    path = REPOSITORY_ROOT / GOLDEN["input_document_fixture"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if variant == "orphan_body":
        append_body_block(
            payload["pages"][2],
            block_id="orphan-body",
            text="未归入条文但需要保留的虚构正文。",
            reading_order=3,
            y_min=700,
            y_max=730,
        )
    elif variant == "header_footer":
        for index in (0, 1):
            page = payload["pages"][index]
            next_order = max(block["reading_order"] for block in page["blocks"]) + 1
            append_body_block(
                page,
                block_id=f"header-{index}",
                text="示例工程规范",
                reading_order=next_order,
                y_min=5,
                y_max=25,
            )
            append_body_block(
                page,
                block_id=f"footer-{index}",
                text=str(index + 9),
                reading_order=next_order + 1,
                y_min=760,
                y_max=780,
            )
    elif variant != "base":
        raise AssertionError(f"unknown fixture variant: {variant}")
    return Document.model_validate(payload)


def _matches(chunk: Chunk, selector: dict[str, object]) -> bool:
    for field, value in selector.items():
        if field == "forbidden_source_block_ids":
            continue
        actual = getattr(chunk, field)
        if hasattr(actual, "value"):
            actual = actual.value
        if actual != value:
            return False
    return True


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=lambda case: case["case_id"])
def test_chunk_v1_golden_case(case: dict[str, object]) -> None:
    document = _document(str(case["fixture_variant"]))
    config = ChunkingConfig.model_validate(case["config"])
    service = create_chunking_service()
    batch = service.chunk(document, config)
    assert batch.model_dump(mode="json") == service.chunk(document, config).model_dump(mode="json")

    expected = case["expected_chunk_batch"]
    assert isinstance(expected, dict)
    assert batch.document_id == expected["document_id"]
    assert batch.chunking_version == expected["chunking_version"]
    assert batch.strategy_id == expected["strategy_id"]

    selector = case["selector"]
    assert isinstance(selector, dict)
    forbidden = selector.get("forbidden_source_block_ids")
    if forbidden is not None:
        actual_ids = {block_id for chunk in batch.chunks for block_id in chunk.source_block_ids}
        assert actual_ids.isdisjoint(forbidden)
        return

    actual_chunks = [chunk for chunk in batch.chunks if _matches(chunk, selector)]
    expected_chunks = expected["chunks"]
    assert len(actual_chunks) == len(expected_chunks)
    for actual, projection in zip(actual_chunks, expected_chunks, strict=True):
        actual_payload = actual.model_dump(mode="json")
        assert {field: actual_payload[field] for field in projection} == projection
