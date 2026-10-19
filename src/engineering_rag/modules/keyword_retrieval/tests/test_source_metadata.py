"""Only _source -> public evidence conversion; no Elasticsearch dependency."""

import pytest

from engineering_rag.contracts.chunks import ChunkContentType
from engineering_rag.modules.keyword_retrieval.internal.errors import KeywordResponseError
from engineering_rag.modules.keyword_retrieval.internal.searcher import _convert_hits

from .helpers import make_chunk


def converted(source):
    return _convert_hits(
        {"hits": {"hits": [{"_source": source, "_score": 7.25}]}}, index_name="fiction-index"
    )[0]


@pytest.mark.parametrize("explanation", [None, False, True])
@pytest.mark.parametrize("mandatory", [None, False, True])
@pytest.mark.parametrize("content_type", [None, *ChunkContentType])
def test_source_metadata_values_are_preserved(explanation, mandatory, content_type) -> None:
    source = make_chunk().model_dump(mode="json")
    source.update(
        is_explanation=explanation,
        is_mandatory=mandatory,
        content_type=content_type.value if content_type else None,
    )
    hit = converted(source)
    assert (hit.is_explanation, hit.is_mandatory, hit.content_type) == (
        explanation,
        mandatory,
        content_type,
    )
    legacy = {
        k: v
        for k, v in source.items()
        if k not in {"is_explanation", "is_mandatory", "content_type"}
    }
    old = converted(legacy)
    assert all(
        getattr(old, field) is None for field in ("is_explanation", "is_mandatory", "content_type")
    )
    assert hit.model_dump(
        exclude={"is_explanation", "is_mandatory", "content_type"}
    ) == old.model_dump(exclude={"is_explanation", "is_mandatory", "content_type"})
    assert hit.score == 7.25 and hit.rank == 1 and hit.score_type == "bm25"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("is_explanation", "true"),
        ("is_explanation", 1),
        ("is_explanation", []),
        ("is_mandatory", "false"),
        ("is_mandatory", 0),
        ("is_mandatory", {}),
        ("content_type", "body"),
        ("content_type", 1),
        ("content_type", ""),
        ("content_type", b"clause"),
    ],
)
def test_illegal_source_metadata_raises_typed_response_error(field, value) -> None:
    source = make_chunk().model_dump(mode="json")
    source[field] = value
    with pytest.raises(KeywordResponseError):
        converted(source)
