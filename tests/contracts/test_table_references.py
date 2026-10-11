from copy import deepcopy

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.documents import Document


def test_cross_page_table_has_one_authoritative_logical_table(
    document_data: dict[str, object],
) -> None:
    document = Document.model_validate(document_data)
    table = document.tables[0]
    assert table.source_block_ids == ["table-a-1", "table-a-2"]
    assert document.clauses.normative[0].clause_content.content_units[1].table_id == table.table_id


def test_dangling_clause_table_reference_is_rejected(document_data: dict[str, object]) -> None:
    data = deepcopy(document_data)
    data["clauses"]["normative"][0]["clause_content"]["content_units"][1]["table_id"] = "missing"
    with pytest.raises(ValidationError, match="unknown table_id"):
        Document.model_validate(data)


def test_every_table_block_must_be_a_logical_fragment(document_data: dict[str, object]) -> None:
    data = deepcopy(document_data)
    extra = deepcopy(data["pages"][0]["blocks"][1])
    extra["block_id"] = "table-a-unlisted"
    extra["reading_order"] = 2
    extra["fragment_index"] = 2
    data["pages"][0]["blocks"].append(extra)
    with pytest.raises(ValidationError, match="missing from logical table fragments"):
        Document.model_validate(data)
