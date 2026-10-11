from copy import deepcopy

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.documents import Document, RawTableGrid


def test_merged_headers_and_partial_gaps(document_data: dict[str, object]) -> None:
    document = Document.model_validate(document_data)
    grid = document.tables[0].raw_grid
    assert grid is not None
    assert grid.cells[0].row_span == 2
    assert grid.cells[1].col_span == 2
    partial = RawTableGrid.model_validate(
        {
            "row_count": 2,
            "column_count": 2,
            "extraction_status": "partial",
            "cells": [
                {
                    "row": 0,
                    "col": 0,
                    "text": None,
                    "is_header": True,
                    "recognition_status": "not_transcribed",
                    "source_block_ids": ["fragment"],
                }
            ],
        }
    )
    assert len(partial.cells) == 1


@pytest.mark.parametrize("mutation", ["overlap", "row_overflow", "incomplete_complete"])
def test_invalid_raw_grid_rejected(document_data: dict[str, object], mutation: str) -> None:
    data = deepcopy(document_data)
    grid = data["tables"][0]["raw_grid"]
    if mutation == "overlap":
        grid["cells"][1]["col"] = 0
    elif mutation == "row_overflow":
        grid["cells"][0]["row_span"] = 5
    else:
        grid["cells"].pop()
    with pytest.raises(ValidationError):
        Document.model_validate(data)


def test_raw_cell_source_must_belong_to_logical_table(document_data: dict[str, object]) -> None:
    data = deepcopy(document_data)
    data["tables"][0]["raw_grid"]["cells"][0]["source_block_ids"] = ["body-1"]
    with pytest.raises(ValidationError, match="raw cell source"):
        Document.model_validate(data)
