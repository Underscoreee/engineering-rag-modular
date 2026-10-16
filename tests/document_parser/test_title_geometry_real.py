"""Saved-real regression for MinerU title geometry classification."""

from pathlib import Path

from engineering_rag.contracts.common import FileRef
from engineering_rag.contracts.documents import BlockType, StandardMetadata
from engineering_rag.modules.document_parser.internal.mineru.models import MinerUParseResult
from engineering_rag.modules.document_parser.internal.mineru.v24_adapter import adapt_to_v24
from engineering_rag.modules.document_parser.internal.semantic import assemble_semantics

ROOT = Path(__file__).resolve().parents[2]
NORMALIZED = (
    ROOT
    / "data/eval/task1_6_e2e/runs/GB50010-2010-v4-partial"
    / "batches/batch-001/normalized-01.json"
)
MISCLASSIFIED_BLOCK_ID = "block-3d7c865c28c55b9faf1eba4715749285"
BODY_CONTROL_BLOCK_ID = "block-5e4fb8ec5fac56a79e5bdc0bee5e4ee5"


def test_saved_real_page_53_off_center_item_is_not_a_title() -> None:
    result = MinerUParseResult.model_validate_json(NORMALIZED.read_text(encoding="utf-8"))
    adaptation = adapt_to_v24(
        result,
        source_file=FileRef(
            file_id=f"sha256-{result.source_sha256}",
            uri="fixture://gb50010-v4",
            mime_type="application/pdf",
            sha256=result.source_sha256,
        ),
        standard=StandardMetadata(
            standard_code="GB 50010-2010",
            standard_name="混凝土结构设计规范",
            edition="2015年版",
        ),
        page_count=441,
    )
    page_53 = next(page for page in adaptation.document.pages if page.page_number == 53)
    blocks = {block.block_id: block for block in page_53.blocks}

    assert blocks[MISCLASSIFIED_BLOCK_ID].block_type is BlockType.BODY
    assert blocks[BODY_CONTROL_BLOCK_ID].block_type is BlockType.BODY

    page_49 = next(page for page in adaptation.document.pages if page.page_number == 49)
    assert any(
        block.block_type is BlockType.TITLE
        and block.ocr is not None
        and block.ocr.text == "6 承载能力极限状态计算"
        for block in page_49.blocks
    )

    semantic = assemble_semantics(adaptation.document).document
    assert all(section.title != "1 钢筋混凝土构件" for section in semantic.sections)
