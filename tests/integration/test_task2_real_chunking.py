"""Opt-in Chunk V1 regression over the saved 441-page partial Document."""

import json
import os
from collections import Counter
from pathlib import Path

import pytest

from engineering_rag.contracts.chunks import ChunkBatch, ChunkingConfig
from engineering_rag.contracts.documents import Document
from engineering_rag.modules.chunking.api import create_chunking_service

REPOSITORY_ROOT = Path(__file__).parents[2]
REAL_DOCUMENT = (
    REPOSITORY_ROOT / "data/eval/task1_6_e2e/runs/GB50010-full-v6/final/document.v2.4.partial.json"
)


@pytest.mark.real_chunking
@pytest.mark.skipif(
    os.getenv("ENGINEERING_RAG_RUN_REAL_CHUNKING") != "1",
    reason="set ENGINEERING_RAG_RUN_REAL_CHUNKING=1 to use the saved real artifact",
)
def test_task2_real_document_chunking_regression() -> None:
    document = Document.model_validate_json(REAL_DOCUMENT.read_text(encoding="utf-8"))
    batch = create_chunking_service().chunk(
        document,
        ChunkingConfig(strategy_id="clause-first-v1", max_tokens=800),
    )
    assert ChunkBatch.model_validate_json(batch.model_dump_json()) == batch

    counts = Counter(chunk.content_type.value for chunk in batch.chunks)
    assert (len(document.clauses.normative), len(document.clauses.explanations)) == (436, 344)
    assert len(batch.chunks) == 1305
    assert counts == {
        "clause": 815,
        "formula": 374,
        "table": 73,
        "figure": 24,
        "paragraph": 19,
    }
    assert sum(chunk.is_explanation for chunk in batch.chunks) == 452
    assert sum(chunk.exceeds_max_tokens for chunk in batch.chunks) == 27

    for chunk in batch.chunks:
        if chunk.content_type.value == "formula":
            content = json.loads(chunk.content)
            assert set(content) == {"equations", "symbol_explanations"}
            assert all(
                set(equation) == {"equation_number", "latex"} for equation in content["equations"]
            )
            assert content["symbol_explanations"] is None or all(
                set(item) == {"latex", "content"} for item in content["symbol_explanations"]
            )
        elif chunk.content_type.value == "table":
            content = json.loads(chunk.content)
            assert set(content) == {"table_number", "title", "columns", "data", "notes"}
            assert all(set(column) == {"key", "header_path"} for column in content["columns"])

    block_ids = {block.block_id for page in document.pages for block in page.blocks}
    assert all(set(chunk.source_block_ids).issubset(block_ids) for chunk in batch.chunks)
