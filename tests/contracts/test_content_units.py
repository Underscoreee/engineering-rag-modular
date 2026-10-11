from copy import deepcopy

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.documents import Document, derive_clause_plain_text


def test_reference_only_units_and_plain_text_cache(document_data: dict[str, object]) -> None:
    document = Document.model_validate(document_data)
    clause = document.clauses.normative[0]
    rendered = derive_clause_plain_text(document, clause)
    assert rendered is not None
    text, digest = rendered
    assert text == clause.clause_content.plain_text
    assert digest == clause.clause_content.plain_text_source_digest
    assert [unit.content_type.value for unit in clause.clause_content.content_units] == [
        "body",
        "table",
        "body",
        "formula",
    ]


@pytest.mark.parametrize("field", ["text", "table", "formula_group"])
def test_old_authoritative_copies_are_rejected(
    document_data: dict[str, object], field: str
) -> None:
    data = deepcopy(document_data)
    unit = data["clauses"]["normative"][0]["clause_content"]["content_units"][0]
    unit[field] = "forbidden"
    with pytest.raises(ValidationError):
        Document.model_validate(data)


def test_changed_source_invalidates_cached_plain_text(document_data: dict[str, object]) -> None:
    data = deepcopy(document_data)
    data["pages"][0]["blocks"][0]["ocr"]["text"] = "changed"
    with pytest.raises(ValidationError, match="plain_text cache"):
        Document.model_validate(data)


def test_clause_source_cache_must_match_units(document_data: dict[str, object]) -> None:
    data = deepcopy(document_data)
    data["clauses"]["normative"][0]["source_block_ids"].reverse()
    with pytest.raises(ValidationError, match="source cache"):
        Document.model_validate(data)
