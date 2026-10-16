"""Public Chunk V1 shape and cross-reference invariants."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.chunks import (
    CHUNK_SCHEMA_VERSION,
    ChunkBatch,
    ChunkingConfig,
)

EXAMPLE = Path(__file__).parents[2] / "examples/chunk_batch.example.json"


def test_chunk_v1_example_exposes_required_retrieval_metadata() -> None:
    batch = ChunkBatch.model_validate_json(EXAMPLE.read_text(encoding="utf-8"))
    assert batch.schema_version == CHUNK_SCHEMA_VERSION == "1.0"
    chunk = batch.chunks[0]
    assert chunk.standard.standard_name == "虚构工程示例规范"
    assert chunk.standard.standard_code == "DEMO 100-2026"
    assert chunk.section_path == ["4 虚构构造"]
    assert chunk.source_block_ids == [ref.block_id for ref in chunk.source_refs]
    assert chunk.embedding_text == f"{chunk.context_header}\n\n{chunk.content}"


def test_chunk_v1_config_defaults_to_800_without_overlap() -> None:
    config = ChunkingConfig(strategy_id="clause-first-v1")
    assert (config.max_tokens, config.overlap_tokens, config.options) == (800, 0, {})
    with pytest.raises(ValidationError, match="overlap_tokens=0"):
        ChunkingConfig(strategy_id="clause-first-v1", overlap_tokens=1)


def test_chunk_v1_parent_must_belong_to_the_same_batch() -> None:
    payload = ChunkBatch.model_validate_json(EXAMPLE.read_text(encoding="utf-8")).model_dump(
        mode="json"
    )
    payload["chunks"][0]["parent_chunk_id"] = "missing-parent"
    with pytest.raises(ValidationError, match="same batch"):
        ChunkBatch.model_validate(payload)


def test_chunk_v1_type_specific_references_are_not_accepted_on_clause() -> None:
    payload = ChunkBatch.model_validate_json(EXAMPLE.read_text(encoding="utf-8")).model_dump(
        mode="json"
    )
    payload["chunks"][0]["table_id"] = "table-not-allowed"
    with pytest.raises(ValidationError, match="table_id belongs only"):
        ChunkBatch.model_validate(payload)


def test_chunk_v1_page_range_must_come_from_block_sources() -> None:
    payload = ChunkBatch.model_validate_json(EXAMPLE.read_text(encoding="utf-8")).model_dump(
        mode="json"
    )
    payload["chunks"][0]["page_end"] = 4
    with pytest.raises(ValidationError, match="page range must match source_refs"):
        ChunkBatch.model_validate(payload)
