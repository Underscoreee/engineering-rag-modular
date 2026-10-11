from copy import deepcopy

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.documents import Document


def test_normative_and_explanation_identity_and_order(document_data: dict[str, object]) -> None:
    document = Document.model_validate(document_data)
    normative = document.clauses.normative[0]
    explanation = document.clauses.explanations[0]
    assert normative.clause_number == explanation.clause_number == "4.2.1"
    assert normative.clause_id != explanation.clause_id
    assert explanation.explains_clause_id == normative.clause_id
    assert normative.is_mandatory is None
    assert normative.page_start == 1 and normative.page_end == 2
    assert [unit.content_type.value for unit in normative.clause_content.content_units] == [
        "body",
        "table",
        "body",
        "formula",
    ]


@pytest.mark.parametrize(
    "change",
    [
        "unknown_block",
        "wrong_section",
        "wrong_target",
        "duplicate_clause",
        "short_range",
        "page_out_of_range",
        "missing_fragment",
        "bad_unit_source",
        "cycle",
    ],
)
def test_invalid_clause_or_section_graph(document_data: dict[str, object], change: str) -> None:
    data = deepcopy(document_data)
    norm = data["clauses"]["normative"][0]
    exp = data["clauses"]["explanations"][0]
    if change == "unknown_block":
        norm["source_block_ids"][0] = "missing"
    elif change == "wrong_section":
        norm["section_id"] = "e-4"
    elif change == "wrong_target":
        exp["explains_clause_id"] = exp["clause_id"]
    elif change == "duplicate_clause":
        exp["clause_id"] = norm["clause_id"]
    elif change == "short_range":
        norm["page_end"] = 1
    elif change == "page_out_of_range":
        norm["page_end"] = 5
    elif change == "missing_fragment":
        norm["clause_content"]["content_units"][1]["source_block_ids"] = ["table-a-1"]
    elif change == "bad_unit_source":
        norm["clause_content"]["content_units"][0]["source_block_ids"] = ["missing"]
    else:
        data["sections"][0]["parent_section_id"] = "n-4.2"
    with pytest.raises(ValidationError):
        Document.model_validate(data)
