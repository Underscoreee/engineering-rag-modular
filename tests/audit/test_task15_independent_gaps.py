"""Additional independent negative tests for Task 1.5. Run separately; not shipped upstream."""

import pytest
from scripts.assemble_mineru_clauses import _merge_documents

from engineering_rag.contracts.common import BoundingBox, FileRef
from engineering_rag.contracts.documents import Document
from engineering_rag.modules.document_parser.internal.semantic.assembler import (
    assemble_semantics,
)
from engineering_rag.modules.document_parser.internal.semantic.block_splitter import (
    TextSpanEvidence,
    split_body_block,
)
from engineering_rag.modules.document_parser.tests.path_helpers import repository_root
from engineering_rag.modules.document_parser.tests.test_semantic_structure import (
    _body,
    _document,
    _page,
)


def test_unknown_page_text_is_retained_as_pending_candidate():
    doc = _document([_page(301, _body("unknown-ocr", "前页条文的跨页续文。", 0))])
    result = assemble_semantics(doc)
    assert result.document.pages[0].page_type.value == "unknown"
    assert any(
        "unknown-ocr" in item.evidence_block_ids for item in result.pending_links.relations
    ), "Unknown page OCR evidence is retained in pages but never queued for semantic review"


def test_merge_rejects_same_document_id_but_conflicting_source_pdf():
    one = _document([_page(16, _body("p16", "1.0.1 条文", 0))])
    two = _document([_page(17, _body("p17", "1.0.2 条文", 0))])
    two.source_file = FileRef(
        file_id="other-pdf",
        uri="memory://other.pdf",
        mime_type="application/pdf",
        sha256="b" * 64,
    )
    with pytest.raises((ValueError, SystemExit), match="source|identity|sha256|file"):
        _merge_documents([one, two])


def test_safe_split_requires_child_bbox_inside_original_block_bbox():
    doc = _document([_page(16, _body("mixed", "1.0.1 第一条。1.0.2 第二条。", 0))])
    text = doc.pages[0].blocks[0].ocr.text
    cut = text.index("1.0.2")
    with pytest.raises(ValueError, match="bbox|geometry|source|region|within"):
        split_body_block(
            doc,
            "mixed",
            [
                TextSpanEvidence(
                    start=0,
                    end=cut,
                    bbox=BoundingBox(x_min=20, y_min=220, x_max=350, y_max=240),
                ),
                TextSpanEvidence(
                    start=cut,
                    end=len(text),
                    bbox=BoundingBox(x_min=20, y_min=250, x_max=350, y_max=270),
                ),
            ],
        )


def test_standalone_real_explanation_page_301_does_not_become_normative_body():
    """Without verified zone context, p301 explanation text must not be labelled normative."""
    path = repository_root(__file__) / (
        "data/eval/task1_5_semantics/runs/final/GB-COMBINED/document.semantic.partial.json"
    )
    existing = Document.model_validate_json(path.read_text(encoding="utf-8"))
    payload = existing.model_dump(mode="json")
    source_page = next(item for item in payload["pages"] if item["page_number"] == 301)
    source_page["page_type"] = "unknown"
    source_page["page_type_basis"] = "unclassified_input"
    payload.update(
        pages=[source_page],
        sections=[],
        tables=[],
        clauses={"normative": [], "explanations": []},
    )
    result = assemble_semantics(Document.model_validate(payload))
    assert result.document.pages[0].page_type.value == "unknown", (
        "Real 301 explanation page became normative body without cover or trusted "
        "page-zone evidence"
    )
