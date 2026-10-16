"""Clause-first Chunk V1 acceptance and regression tests."""

import json

from engineering_rag.contracts.chunks import ChunkContentType, ChunkingConfig
from engineering_rag.modules.chunking.api import create_chunking_service

from .support import append_body_block, document_with_updates, example_document


def _chunk(document=None, *, max_tokens: int = 800):  # type: ignore[no-untyped-def]
    return create_chunking_service().chunk(
        document or example_document(),
        ChunkingConfig(strategy_id="clause-first-v1", max_tokens=max_tokens),
    )


def test_single_normal_clause_produces_one_main_physical_chunk() -> None:
    batch = _chunk()
    chunks = [
        chunk
        for chunk in batch.chunks
        if chunk.clause_id == "n-4.2.2" and chunk.content_type == ChunkContentType.CLAUSE
    ]
    assert len(chunks) == 1
    assert len({chunk.logical_chunk_id for chunk in chunks}) == 1


def test_cross_page_clause_keeps_one_logical_identity_and_page_range() -> None:
    chunks = [
        chunk
        for chunk in _chunk().chunks
        if chunk.clause_id == "n-4.2.1" and chunk.content_type == ChunkContentType.CLAUSE
    ]
    assert len(chunks) == 1
    assert (chunks[0].page_start, chunks[0].page_end) == (1, 2)


def test_normative_and_explanation_with_same_number_are_isolated() -> None:
    chunks = [
        chunk
        for chunk in _chunk().chunks
        if chunk.clause_number == "4.2.1" and chunk.content_type == ChunkContentType.CLAUSE
    ]
    assert {chunk.is_explanation for chunk in chunks} == {False, True}
    assert len({chunk.logical_chunk_id for chunk in chunks}) == 2


def test_list_items_remain_in_the_clause_chunk() -> None:
    def mutate(payload):  # type: ignore[no-untyped-def]
        page = payload["pages"][2]
        page["blocks"][1]["reading_order"] = 3
        page["blocks"][2]["reading_order"] = 4
        append_body_block(
            page,
            block_id="list-1",
            text="1 第一项虚构要求。",
            reading_order=1,
            y_min=105,
            y_max=115,
        )
        append_body_block(
            page,
            block_id="list-2",
            text="2 第二项虚构要求。",
            reading_order=2,
            y_min=116,
            y_max=126,
        )
        clause = payload["clauses"]["normative"][1]
        clause["clause_content"]["content_units"] = [
            {"order": 0, "content_type": "body", "source_block_ids": ["body-2"]},
            {
                "order": 1,
                "content_type": "list_item",
                "source_block_ids": ["list-1"],
                "list_item_label": "1",
            },
            {
                "order": 2,
                "content_type": "list_item",
                "source_block_ids": ["list-2"],
                "list_item_label": "2",
            },
            {
                "order": 3,
                "content_type": "table",
                "source_block_ids": ["table-b-1"],
                "table_id": "table-b",
            },
            {
                "order": 4,
                "content_type": "image",
                "source_block_ids": ["image-1"],
                "asset_id": "synthetic-figure",
            },
        ]
        clause["source_block_ids"] = [
            "body-2",
            "list-1",
            "list-2",
            "table-b-1",
            "image-1",
        ]

    main = next(
        chunk
        for chunk in _chunk(document_with_updates(mutate)).chunks
        if chunk.clause_id == "n-4.2.2" and chunk.content_type == ChunkContentType.CLAUSE
    )
    assert "第一项虚构要求" in main.content and "第二项虚构要求" in main.content


def test_table_chunk_preserves_structure_and_parent_relation() -> None:
    chunks = _chunk().chunks
    parent = next(
        chunk
        for chunk in chunks
        if chunk.clause_id == "n-4.2.1" and chunk.content_type == ChunkContentType.CLAUSE
    )
    table = next(chunk for chunk in chunks if chunk.table_id == "table-a")
    payload = json.loads(table.content)
    assert table.parent_chunk_id == parent.chunk_id
    assert payload["columns"] and payload["data"] and payload["notes"]
    assert payload["raw_grid"]["column_count"] == 3


def test_cross_page_table_remains_one_atomic_chunk() -> None:
    tables = [chunk for chunk in _chunk().chunks if chunk.table_id == "table-a"]
    assert len(tables) == 1
    assert (tables[0].page_start, tables[0].page_end) == (1, 2)
    assert tables[0].source_block_ids == ["table-a-1", "table-a-2"]


def test_formula_group_stays_atomic_with_all_equations_and_symbols() -> None:
    formula = next(
        chunk for chunk in _chunk().chunks if chunk.content_type == ChunkContentType.FORMULA
    )
    payload = json.loads(formula.content)
    assert formula.formula_ids == ["f-norm-421-1", "f-norm-421-2"]
    assert len(payload["equations"]) == 2
    assert payload["symbol_explanations"]["items"][0]["symbol"] == "q"


def test_long_clause_splits_without_overlap_and_keeps_logical_id() -> None:
    sentence = "这是用于测试超长条文稳定切分的虚构句子。"

    def mutate(payload):  # type: ignore[no-untyped-def]
        payload["pages"][2]["blocks"][0]["ocr"]["text"] = sentence * 20

    chunks = [
        chunk
        for chunk in _chunk(document_with_updates(mutate), max_tokens=60).chunks
        if chunk.clause_id == "n-4.2.2" and chunk.content_type == ChunkContentType.CLAUSE
    ]
    assert len(chunks) > 1
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
    assert len({chunk.logical_chunk_id for chunk in chunks}) == 1
    assert all(not chunk.exceeds_max_tokens for chunk in chunks)
    assert sum(chunk.content.count(sentence) for chunk in chunks) == 20


def test_oversized_table_is_not_split_and_is_marked() -> None:
    tables = [chunk for chunk in _chunk(max_tokens=40).chunks if chunk.table_id == "table-a"]
    assert len(tables) == 1
    assert tables[0].exceeds_max_tokens
    assert tables[0].token_count > 40
    assert json.loads(tables[0].content)["raw_grid"] is not None


def test_unclaimed_body_becomes_paragraph_chunk() -> None:
    def mutate(payload):  # type: ignore[no-untyped-def]
        append_body_block(
            payload["pages"][2],
            block_id="orphan-body",
            text="未归入条文但需要保留的虚构正文。",
            reading_order=3,
            y_min=700,
            y_max=730,
        )

    paragraph = next(
        chunk
        for chunk in _chunk(document_with_updates(mutate)).chunks
        if chunk.content_type == ChunkContentType.PARAGRAPH
    )
    assert paragraph.clause_number is None
    assert paragraph.source_block_ids == ["orphan-body"]


def test_repeated_headers_and_printed_page_numbers_do_not_create_chunks() -> None:
    def mutate(payload):  # type: ignore[no-untyped-def]
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

    source_ids = {
        block_id
        for chunk in _chunk(document_with_updates(mutate)).chunks
        for block_id in chunk.source_block_ids
    }
    assert source_ids.isdisjoint({"header-0", "header-1", "footer-0", "footer-1"})


def test_chunking_is_fully_deterministic() -> None:
    first = _chunk()
    second = _chunk()
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_metadata_and_context_are_inherited_without_mandatory_inference() -> None:
    chunk = next(
        chunk
        for chunk in _chunk().chunks
        if chunk.clause_id == "n-4.2.1" and chunk.content_type == ChunkContentType.CLAUSE
    )
    assert chunk.standard.standard_name == "虚构结构化演示规范"
    assert chunk.standard.standard_code == "DEMO-24"
    assert chunk.section_path == ["4 虚构章", "4.2 虚构节"]
    assert chunk.clause_number == "4.2.1"
    assert chunk.is_mandatory is True
    assert chunk.embedding_text == f"{chunk.context_header}\n\n{chunk.content}"


def test_pure_image_without_caption_does_not_invent_figure_text() -> None:
    def mutate(payload):  # type: ignore[no-untyped-def]
        payload["pages"][2]["blocks"][2]["ocr"] = None

    chunks = _chunk(document_with_updates(mutate)).chunks
    assert all(chunk.figure_id != "synthetic-figure" for chunk in chunks)


def test_content_units_are_authoritative_over_cached_plain_text() -> None:
    document = example_document()
    clause = document.clauses.normative[0]
    assert clause.clause_content.plain_text is not None
    main = next(
        chunk
        for chunk in _chunk(document).chunks
        if chunk.clause_id == clause.clause_id and chunk.content_type == ChunkContentType.CLAUSE
    )
    assert main.content != clause.clause_content.plain_text
    assert main.source_block_ids == ["body-1", "formula-intro"]
