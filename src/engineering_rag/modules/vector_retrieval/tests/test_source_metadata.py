"""Milvus entity -> public evidence conversion; no Milvus/Embedding runtime."""

import pytest

from engineering_rag.contracts.chunks import ChunkContentType
from engineering_rag.modules.vector_retrieval.internal.errors import VectorResponseError
from engineering_rag.modules.vector_retrieval.internal.searcher import OUTPUT_FIELDS, _to_result


def entity() -> dict[str, object]:
    return {
        "chunk_id": "fiction-chunk",
        "logical_chunk_id": "fiction-logical",
        "document_id": "fiction-doc",
        "content": "虚构演示文本。",
        "standard_name": "虚构规范",
        "standard_code": "DEMO 1-2026",
        "edition": "2026-demo",
        "clause_id": None,
        "clause_number": None,
        "page_start": 1,
        "page_end": 2,
    }


def converted(row):
    return _to_result({"entity": row, "distance": 0.875}, rank=2, index_name="fiction_vectors")


def test_metadata_fields_are_requested_from_actual_milvus_entity() -> None:
    assert {"is_explanation", "mandatory_state", "content_type"}.issubset(OUTPUT_FIELDS)
    assert len(OUTPUT_FIELDS) == len(set(OUTPUT_FIELDS))


@pytest.mark.parametrize("explanation", [None, False, True])
@pytest.mark.parametrize(("state", "expected"), [(-1, None), (0, False), (1, True)])
@pytest.mark.parametrize("content_type", [None, *ChunkContentType])
def test_known_milvus_metadata(explanation, state, expected, content_type) -> None:
    hit = converted(
        {
            **entity(),
            "is_explanation": explanation,
            "mandatory_state": state,
            "content_type": content_type.value if content_type else None,
        }
    )
    assert (hit.is_explanation, hit.is_mandatory, hit.content_type) == (
        explanation,
        expected,
        content_type,
    )
    assert hit.score == 0.875 and hit.rank == 2 and hit.score_type == "cosine_similarity"


def test_legacy_entity_missing_fields_stays_unknown() -> None:
    hit = converted(entity())
    assert (hit.is_explanation, hit.is_mandatory, hit.content_type) == (None, None, None)


@pytest.mark.parametrize("state", [-2, 2, True, False, "-1", "0", 0.0, 1.0, None, [], {}])
def test_invalid_mandatory_state_is_not_coerced(state) -> None:
    with pytest.raises(VectorResponseError):
        converted({**entity(), "mandatory_state": state})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("is_explanation", "false"),
        ("is_explanation", 0),
        ("content_type", "title"),
        ("content_type", {}),
        ("content_type", b"clause"),
    ],
)
def test_invalid_other_metadata_is_rejected(field, value) -> None:
    with pytest.raises(VectorResponseError):
        converted({**entity(), field: value})
