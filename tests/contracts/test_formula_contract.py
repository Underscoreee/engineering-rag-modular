from copy import deepcopy

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.documents import Document, Equation, SymbolExplanationItem


def test_numbered_and_confirmed_unnumbered_equations(document_data: dict[str, object]) -> None:
    document = Document.model_validate(document_data)
    group = document.pages[1].blocks[2].ocr.formula_group
    assert [equation.equation_number for equation in group.equations] == ["(4.2.1-1)", "(4.2.1-2)"]
    assert group.symbol_explanations.items[0].symbol == "q"
    unnumbered = document.pages[3].blocks[1].ocr.formula_group.equations[0]
    assert unnumbered.equation_number is None
    assert unnumbered.equation_number_status.value == "confirmed_absent"
    assert document.pages[3].blocks[1].ocr.formula_group.symbol_explanations is None
    assert Document.model_validate_json(document.model_dump_json()) == document
    assert "\\\\begin{aligned}" in document.model_dump_json()


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_id",
        "duplicate_id",
        "duplicate_across_blocks",
        "missing_latex",
        "unknown_number",
        "absent_unverified",
    ],
)
def test_formula_invalid_states(document_data: dict[str, object], mutation: str) -> None:
    data = deepcopy(document_data)
    equations = data["pages"][1]["blocks"][2]["ocr"]["formula_group"]["equations"]
    if mutation == "missing_id":
        del equations[0]["formula_id"]
    elif mutation == "duplicate_id":
        equations[1]["formula_id"] = equations[0]["formula_id"]
    elif mutation == "duplicate_across_blocks":
        data["pages"][3]["blocks"][1]["ocr"]["formula_group"]["equations"][0]["formula_id"] = (
            equations[0]["formula_id"]
        )
    elif mutation == "missing_latex":
        equations[0]["latex"] = None
    elif mutation == "unknown_number":
        equations[0]["equation_number"] = None
        equations[0]["equation_number_status"] = "unknown"
    else:
        equations[0]["equation_number"] = None
        equations[0]["equation_number_status"] = "confirmed_absent"
        equations[0]["recognition_status"] = "unverified"
    with pytest.raises(ValidationError):
        Document.model_validate(data)


@pytest.mark.parametrize("name", ["unit", "intro", "line_index"])
def test_removed_formula_fields_rejected(name: str) -> None:
    equation = {
        "formula_id": "f",
        "equation_number": "(1)",
        "equation_number_status": "printed",
        "latex": "a=b",
        "recognition_status": "verified",
        name: "forbidden",
    }
    with pytest.raises(ValidationError):
        Equation.model_validate(equation)


@pytest.mark.parametrize("name", ["unit", "intro", "line_index"])
def test_removed_symbol_explanation_fields_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        SymbolExplanationItem.model_validate(
            {"symbol": "q", "latex": "q", "description": "虚构量", name: "forbidden"}
        )


def test_untranscribed_formula_cannot_claim_latex() -> None:
    with pytest.raises(ValidationError):
        Equation.model_validate(
            {
                "formula_id": "pending",
                "equation_number": None,
                "equation_number_status": "unknown",
                "latex": "a=b",
                "recognition_status": "not_transcribed",
            }
        )
