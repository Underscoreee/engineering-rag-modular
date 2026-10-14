"""Saved-real regression for the Task 1.6 manual-review repair."""

import os
from pathlib import Path

import pytest

from engineering_rag.contracts.common import FileRef
from engineering_rag.contracts.documents import BlockType, Document, StandardMetadata
from engineering_rag.modules.document_parser.internal.e2e import merge_documents
from engineering_rag.modules.document_parser.internal.mineru.models import MinerUParseResult
from engineering_rag.modules.document_parser.internal.mineru.v24_adapter import adapt_to_v24
from engineering_rag.modules.document_parser.internal.semantic import assemble_semantics

pytestmark = [
    pytest.mark.real_mineru,
    pytest.mark.skipif(
        os.environ.get("ENGINEERING_RAG_RUN_REAL_MINERU") != "1",
        reason="set ENGINEERING_RAG_RUN_REAL_MINERU=1 for saved-real manual-review replay",
    ),
]

SHA = "43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682"
RUN = Path("data/eval/task1_6_e2e/runs/gb50010-full-v1/batches")


def test_saved_real_manual_review_pages_regenerate_correct_semantics() -> None:
    adaptations = [_adapt(batch) for batch in ("004", "005", "006")]
    result = assemble_semantics(merge_documents([item.document for item in adaptations]))
    document = Document.model_validate_json(result.document.model_dump_json())

    for page in document.pages:
        assert all(
            not (
                block.ocr
                and block.ocr.text
                and block.ocr.text.isdigit()
                and block.bbox.y_min >= page.height * 0.82
            )
            for block in page.blocks
        )
    page_17 = next(page for page in document.pages if page.page_number == 17)
    clause_heading = next(
        block for block in page_17.blocks if block.ocr and block.ocr.text.startswith("2.1.1 ")
    )
    assert clause_heading.block_type == BlockType.BODY

    clause_332 = next(
        clause for clause in document.clauses.normative if clause.clause_number == "3.3.2"
    )
    assert clause_332.clause_content.plain_text is not None
    assert clause_332.clause_content.plain_text.count("承载能力极限状态下作用组合") == 1
    assert "4.1.4条及第4.2.3条的规定取值" in clause_332.clause_content.plain_text
    assert "几何参数的标准值" in clause_332.clause_content.plain_text
    assert "\\prime" not in clause_332.clause_content.plain_text

    tables = {table.table_number: table for table in document.tables}
    assert [note.number for note in tables["3.4.3"].notes or []] == [1, 2, 3, 4]
    assert [note.number for note in tables["3.4.5"].notes or []] == list(range(1, 8))
    assert [note.number for note in tables["3.5.2"].notes or []] == list(range(1, 6))
    assert len(tables["3.5.3"].notes or []) == 6


def _adapt(batch: str):  # type: ignore[no-untyped-def]
    normalized = RUN / f"batch-{batch}" / "normalized-01.json"
    result = MinerUParseResult.model_validate_json(normalized.read_text(encoding="utf-8"))
    return adapt_to_v24(
        result,
        source_file=FileRef(
            file_id=f"sha256-{SHA}",
            uri="GB50010.pdf",
            mime_type="application/pdf",
            sha256=SHA,
            size_bytes=154122112,
        ),
        standard=StandardMetadata(
            standard_name="混凝土结构设计规范",
            standard_code="GB 50010-2010",
            edition="2015年版",
        ),
        page_count=441,
    )
