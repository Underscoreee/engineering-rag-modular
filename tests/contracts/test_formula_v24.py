from copy import deepcopy

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.documents import Document


def test_number_states_and_content_references(document_data: dict[str, object]) -> None:
    document = Document.model_validate(document_data)
    numbered = document.pages[1].blocks[2].ocr.formula_group.equations
    unnumbered = document.pages[3].blocks[1].ocr.formula_group.equations[0]
    assert all(equation.equation_number for equation in numbered)
    assert unnumbered.equation_number is None
    assert unnumbered.equation_number_status.value == "confirmed_absent"
    assert document.clauses.normative[0].clause_content.content_units[-1].formula_ids == [
        "f-norm-421-1",
        "f-norm-421-2",
    ]


def test_dangling_formula_reference_rejected(document_data: dict[str, object]) -> None:
    data = deepcopy(document_data)
    data["clauses"]["normative"][0]["clause_content"]["content_units"][-1]["formula_ids"] = [
        "missing"
    ]
    with pytest.raises(ValidationError, match="formula_ids"):
        Document.model_validate(data)
