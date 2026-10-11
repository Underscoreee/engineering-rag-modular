from copy import deepcopy

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.documents import Document


def test_cross_page_and_single_page_tables(document_data: dict[str, object]) -> None:
    document = Document.model_validate(document_data)
    first, second = document.tables
    assert first.source_block_ids == ["table-a-1", "table-a-2"]
    assert [part.page_number for part in first.fragments] == [1, 2]
    assert [
        part.table_id
        for page in document.pages
        for part in page.blocks
        if part.table_id == "table-a"
    ] == ["table-a", "table-a"]
    assert first.columns[0].header_path == ["构件", "类别"]
    assert first.columns[1].derived is True
    assert first.data[1].root["value"] == "≥演示值乙"
    assert first.data[1].root["source_page"] == 2
    assert [note.number for note in first.notes] == [1, 2]
    assert second.notes is None and len(second.fragments) == 1


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("tables", 1, "table_id"), "table-a"),
        (("tables", 0, "fragments", 1, "fragment_index"), 0),
        (("tables", 0, "fragments", 1, "page_number"), 1),
        (("tables", 0, "fragments", 1, "block_id"), "body-1"),
        (("pages", 1, "blocks", 0, "table_id"), "missing-table"),
        (("tables", 0, "columns", 1, "key"), "kind"),
        (("tables", 0, "data", 0, "value"), 123),
    ],
)
def test_invalid_table_graph(document_data: dict[str, object], path: tuple, value: object) -> None:
    data = deepcopy(document_data)
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        Document.model_validate(data)


def test_table_row_and_note_constraints(document_data: dict[str, object]) -> None:
    for mutate in (
        lambda d: d["tables"][0]["data"][0].update(typo="wrong column"),
        lambda d: d["tables"][0]["data"][0].update(source_page=4),
        lambda d: d["tables"][0]["data"][0].update(source_page=2),
        lambda d: d["tables"][0]["notes"].append({"number": 1, "content": "duplicate"}),
        lambda d: d["tables"][0]["columns"][0].update(header_path=[]),
        lambda d: d["tables"][0]["columns"][0].update(role="invalid"),
        lambda d: d["tables"][0]["columns"][0].update(key="source_page"),
        lambda d: d["tables"][0].update(extraction_status="structure_only"),
    ):
        data = deepcopy(document_data)
        mutate(data)
        with pytest.raises(ValidationError):
            Document.model_validate(data)
