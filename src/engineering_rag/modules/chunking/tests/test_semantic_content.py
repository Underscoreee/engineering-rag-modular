"""Formula and table Chunk content contains semantics, not parser metadata."""

import json

from engineering_rag.contracts.chunks import Chunk, ChunkContentType, ChunkingConfig
from engineering_rag.modules.chunking.api import create_chunking_service
from engineering_rag.modules.chunking.internal.splitter import count_tokens

from .support import document_with_updates, example_document

FORMULA_MACHINE_FIELDS = {
    "equation_number_status",
    "formula_group_id",
    "formula_id",
    "recognition_status",
    "text",
    "symbol",
    "description",
    "source_block_ids",
    "bbox",
    "extraction_method",
    "bbox_status",
    "fragment_index",
    "fragment_status",
}
TABLE_MACHINE_FIELDS = {
    "raw_grid",
    "recognition_status",
    "extraction_status",
    "normalization_warning",
    "source_block_ids",
    "derived",
    "description",
    "row",
    "col",
    "row_span",
    "col_span",
    "is_header",
    "source_page",
    "source_block_id",
    "extraction_method",
    "bbox",
    "bbox_status",
    "fragment_index",
    "fragment_status",
}


def _chunk(document=None):  # type: ignore[no-untyped-def]
    return create_chunking_service().chunk(
        document or example_document(),
        ChunkingConfig(strategy_id="clause-first-v1", max_tokens=800),
    )


def _first(content_type: ChunkContentType, *, explanation: bool = False) -> Chunk:
    return next(
        chunk
        for chunk in _chunk().chunks
        if chunk.content_type == content_type and chunk.is_explanation is explanation
    )


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_keys(item) for item in value), set())
    return set()


def test_formula_content_keeps_only_equations_and_symbol_semantics() -> None:
    def mutate(payload):  # type: ignore[no-untyped-def]
        block = next(
            block
            for page in payload["pages"]
            for block in page["blocks"]
            if block["block_id"] == "formula-1"
        )
        block["recognition_status"] = "unverified"
        equation = block["ocr"]["formula_group"]["equations"][0]
        equation.update(
            {
                "equation_number": "3.3.2-1",
                "latex": "\\gamma_{0} S \\leqslant R\\tag{3.3.2-1}",
                "recognition_status": "unverified",
            }
        )
        clause_content = payload["clauses"]["normative"][0]["clause_content"]
        clause_content["plain_text"] = None
        clause_content["plain_text_renderer_version"] = None
        clause_content["plain_text_source_digest"] = None

    formula = next(
        chunk
        for chunk in _chunk(document_with_updates(mutate)).chunks
        if chunk.content_type == ChunkContentType.FORMULA and not chunk.is_explanation
    )
    payload = json.loads(formula.content)
    assert set(payload) == {"equations", "symbol_explanations"}
    assert payload["equations"][0] == {
        "equation_number": "3.3.2-1",
        "latex": "\\gamma_{0} S \\leqslant R\\tag{3.3.2-1}",
    }
    assert payload["symbol_explanations"] == [{"latex": "q", "content": "虚构量"}]
    assert _keys(payload).isdisjoint(FORMULA_MACHINE_FIELDS)


def test_formula_without_equation_number_is_retained() -> None:
    formula = _first(ChunkContentType.FORMULA, explanation=True)
    payload = json.loads(formula.content)
    assert payload["equations"] == [{"equation_number": None, "latex": "z=a+b"}]
    assert payload["symbol_explanations"] is None


def test_formula_content_retains_all_equations() -> None:
    def mutate(payload):  # type: ignore[no-untyped-def]
        block = next(
            block
            for page in payload["pages"]
            for block in page["blocks"]
            if block["block_id"] == "formula-1"
        )
        block["ocr"]["formula_group"]["equations"].append(
            {
                "formula_id": "f-norm-421-3",
                "equation_number": "(4.2.1-3)",
                "equation_number_status": "printed",
                "latex": "s=u+v",
                "text": "s=u+v",
                "recognition_status": "verified",
            }
        )
        clause = payload["clauses"]["normative"][0]
        formula_unit = next(
            unit
            for unit in clause["clause_content"]["content_units"]
            if unit["content_type"] == "formula"
        )
        formula_unit["formula_ids"].append("f-norm-421-3")
        clause["clause_content"]["plain_text"] = None
        clause["clause_content"]["plain_text_renderer_version"] = None
        clause["clause_content"]["plain_text_source_digest"] = None

    formula = next(
        chunk
        for chunk in _chunk(document_with_updates(mutate)).chunks
        if chunk.content_type == ChunkContentType.FORMULA and not chunk.is_explanation
    )
    payload = json.loads(formula.content)
    assert [item["equation_number"] for item in payload["equations"]] == [
        "(4.2.1-1)",
        "(4.2.1-2)",
        "(4.2.1-3)",
    ]
    assert formula.formula_ids == ["f-norm-421-1", "f-norm-421-2", "f-norm-421-3"]


def test_symbol_text_falls_back_to_latex_field_without_invention() -> None:
    def mutate(payload):  # type: ignore[no-untyped-def]
        block = next(
            block
            for page in payload["pages"]
            for block in page["blocks"]
            if block["block_id"] == "formula-1"
        )
        block["ocr"]["formula_group"]["symbol_explanations"]["items"][0]["latex"] = None
        clause_content = payload["clauses"]["normative"][0]["clause_content"]
        clause_content["plain_text"] = None
        clause_content["plain_text_renderer_version"] = None
        clause_content["plain_text_source_digest"] = None

    formula = next(
        chunk
        for chunk in _chunk(document_with_updates(mutate)).chunks
        if chunk.content_type == ChunkContentType.FORMULA and not chunk.is_explanation
    )
    payload = json.loads(formula.content)
    assert payload["symbol_explanations"][0] == {"latex": "q", "content": "虚构量"}


def test_table_content_keeps_only_retrieval_semantics_across_pages() -> None:
    table = next(chunk for chunk in _chunk().chunks if chunk.table_id == "table-a")
    payload = json.loads(table.content)
    assert set(payload) == {"table_number", "title", "columns", "data", "notes"}
    assert payload["table_number"] == "表4.2.1"
    assert payload["title"] == "虚构跨页表"
    assert payload["columns"] == [
        {"key": "kind", "header_path": ["构件", "类别"]},
        {"key": "condition", "header_path": ["构件", "演示条件"]},
        {"key": "value", "header_path": ["演示指标", "值"]},
    ]
    assert payload["data"] == [
        {"kind": "甲类", "condition": "常规", "value": "演示值甲"},
        {"kind": "乙类", "condition": "不适用", "value": "≥演示值乙"},
    ]
    assert payload["notes"] == [
        {"number": 1, "content": "所有内容均为虚构演示。"},
        {"number": 2, "content": "比较符号仅用于展示字符串保真。"},
    ]
    assert _keys(payload).isdisjoint(TABLE_MACHINE_FIELDS)
    assert (table.page_start, table.page_end) == (1, 2)


def test_table_without_notes_uses_null() -> None:
    table = next(chunk for chunk in _chunk().chunks if chunk.table_id == "table-b")
    assert json.loads(table.content)["notes"] is None


def test_formula_and_table_metadata_remains_outside_content() -> None:
    formula = _first(ChunkContentType.FORMULA)
    table = next(chunk for chunk in _chunk().chunks if chunk.table_id == "table-a")
    assert formula.formula_ids == ["f-norm-421-1", "f-norm-421-2"]
    assert formula.source_block_ids == ["formula-1"]
    assert formula.source_refs[0].block_id == "formula-1"
    assert table.table_id == "table-a"
    assert table.source_block_ids == ["table-a-1", "table-a-2"]
    assert [ref.page_number for ref in table.source_refs] == [1, 2]


def test_embedding_text_and_token_count_follow_clean_semantic_content() -> None:
    for chunk in (
        _first(ChunkContentType.FORMULA),
        next(chunk for chunk in _chunk().chunks if chunk.table_id == "table-a"),
    ):
        payload = json.loads(chunk.content)
        forbidden = (
            FORMULA_MACHINE_FIELDS
            if chunk.content_type == ChunkContentType.FORMULA
            else TABLE_MACHINE_FIELDS
        )
        assert _keys(payload).isdisjoint(forbidden)
        assert chunk.embedding_text == f"{chunk.context_header}\n\n{chunk.content}"
        assert chunk.token_count == count_tokens(chunk.embedding_text)


def test_non_formula_and_non_table_content_is_unchanged() -> None:
    clause = next(
        chunk
        for chunk in _chunk().chunks
        if chunk.content_type == ChunkContentType.CLAUSE and chunk.clause_id == "n-4.2.1"
    )
    figure = next(
        chunk for chunk in _chunk().chunks if chunk.content_type == ChunkContentType.FIGURE
    )
    assert clause.content == "4.2.1 以下全部内容为虚构演示。\n下列公式仅演示数据结构。"
    assert figure.content == "虚构附图"
