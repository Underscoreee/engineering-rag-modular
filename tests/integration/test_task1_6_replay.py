"""Saved-real-output Task 1.6 replay smoke tests."""

import json
import os
from pathlib import Path

import pytest

from engineering_rag.contracts.common import FileRef
from engineering_rag.contracts.documents import (
    ClauseContentType,
    Document,
    StandardMetadata,
    derive_clause_plain_text,
)
from engineering_rag.modules.document_parser.internal.e2e import merge_documents
from engineering_rag.modules.document_parser.internal.mineru.models import MinerUParseResult
from engineering_rag.modules.document_parser.internal.mineru.v24_adapter import adapt_to_v24
from engineering_rag.modules.document_parser.internal.semantic import assemble_semantics

pytestmark = [
    pytest.mark.real_mineru,
    pytest.mark.skipif(
        os.environ.get("ENGINEERING_RAG_RUN_REAL_MINERU") != "1",
        reason="set ENGINEERING_RAG_RUN_REAL_MINERU=1 for saved-real Task 1.6 replay",
    ),
]

SHA = "43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682"


def test_saved_real_p16_replay_is_strict_v24_and_deterministic() -> None:
    path = Path("data/eval/task1_2_mineru/runs/final/P016/single_page/normalized.json")
    result = MinerUParseResult.model_validate_json(path.read_text(encoding="utf-8"))
    adaptation = adapt_to_v24(
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
    merged = merge_documents([adaptation.document])
    first = assemble_semantics(merged)
    second = assemble_semantics(merged)
    assert first.document == second.document
    assert first.document.pages[0].page_number == 16
    assert first.document.pages[0].page_type.value == "body"
    assert Document.model_validate_json(first.document.model_dump_json()) == first.document


def test_saved_real_p49_50_formula_semantics_are_complete_and_deduplicated() -> None:
    document = Document.model_validate_json(
        Path(
            "data/eval/task1_6_e2e/runs/replay-formula-final3-20261012/"
            "final/document.v2.4.partial.json"
        ).read_text(encoding="utf-8")
    )
    clause = next(item for item in document.clauses.normative if item.clause_number == "6.2.1")
    formula_units = [
        item
        for item in clause.clause_content.content_units
        if item.content_type == ClauseContentType.FORMULA
    ]
    assert [len(item.formula_ids) for item in formula_units] == [5, 2]
    rendered = derive_clause_plain_text(document, clause)
    assert rendered is not None
    assert "ε_c ≤ ε_0" in rendered[0]
    assert "ε_0 < ε_c ≤ ε_cu" in rendered[0]
    assert rendered[0].count("混凝土轴心抗压强度设计值") == 1
    integrity = json.loads(
        Path(
            "data/eval/task1_6_e2e/runs/replay-formula-final3-20261012/qa/semantic_integrity.json"
        ).read_text(encoding="utf-8")
    )["formula_6_2_1"]
    assert integrity["condition_not_propagated"] is True
    assert integrity["condition_body_duplicate_count"] == 0
    assert integrity["symbol_description_body_duplicate_count"] == 0
