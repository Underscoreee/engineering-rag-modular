"""Explicit local replay assertions; skipped in ordinary offline pytest runs."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from engineering_rag.contracts.documents import BlockType, Document, LogicalTableStatus

pytestmark = [
    pytest.mark.real_mineru,
    pytest.mark.skipif(
        os.environ.get("ENGINEERING_RAG_RUN_REAL_MINERU") != "1",
        reason="set ENGINEERING_RAG_RUN_REAL_MINERU=1 after generating Task 1.3 artifacts",
    ),
]

ROOT = Path("data/eval/task1_3_tables/runs/final")


@pytest.mark.parametrize(
    ("case_id", "table_number"),
    [("GB-T352", "3.5.2"), ("GB-T4222", "4.2.2-2"), ("GB-T912", "9.1.2")],
)
def test_real_cross_page_table_is_traceable_and_unverified(case_id: str, table_number: str) -> None:
    path = ROOT / case_id / "paired_contiguous" / "document.partial.json"
    document = Document.model_validate_json(path.read_text(encoding="utf-8"))
    table = next(item for item in document.tables if item.table_number == table_number)
    assert len(table.fragments) == 2
    assert table.extraction_status == LogicalTableStatus.UNVERIFIED
    assert table.raw_grid is not None
    assert all(
        block.table_id == table.table_id
        for page in document.pages
        for block in page.blocks
        if block.block_id in table.source_block_ids
    )
    assert Document.model_validate_json(document.model_dump_json()) == document


def test_real_page_127_following_text_is_not_absorbed_into_table() -> None:
    path = ROOT / "GB-T912" / "paired_contiguous" / "document.partial.json"
    document = Document.model_validate_json(path.read_text(encoding="utf-8"))
    page = next(item for item in document.pages if item.page_number == 127)
    following = [
        block
        for block in page.blocks
        if block.block_type == BlockType.BODY
        and block.ocr is not None
        and (block.ocr.text or "").startswith("9.1.3")
    ]
    assert len(following) == 1
    assert following[0].table_id is None
