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


def test_split_formula_group_renders_symbols_once(document_data: dict[str, object]) -> None:
    data = deepcopy(document_data)
    content = data["clauses"]["normative"][0]["clause_content"]
    formula_unit = content["content_units"].pop()
    first = deepcopy(formula_unit)
    first["formula_ids"] = ["f-norm-421-1"]
    second = deepcopy(formula_unit)
    second["order"] = 4
    second["formula_ids"] = ["f-norm-421-2"]
    content["content_units"].extend([first, second])
    content["plain_text"] = None
    content.pop("plain_text_renderer_version")
    content.pop("plain_text_source_digest")
    document = Document.model_validate(data)
    rendered = derive_clause_plain_text(document, document.clauses.normative[0])
    assert rendered is not None
    assert rendered[0].count("虚构量") == 1
    assert rendered[0].index("q=F/A") < rendered[0].index("r=ΔL/L₀")
    assert rendered[0].index("r=ΔL/L₀") < rendered[0].index("式中：q：虚构量")


def test_consecutive_formula_groups_preserve_order_and_each_symbol_set(
    document_data: dict[str, object],
) -> None:
    data = deepcopy(document_data)
    data["pages"][1]["blocks"].append(
        {
            "block_id": "formula-extra",
            "block_type": "formula",
            "bbox": {"x_min": 70, "y_min": 620, "x_max": 520, "y_max": 700},
            "reading_order": 3,
            "formula_group_id": "fg-norm-extra",
            "ocr": {
                "text": "x=y；式中：x为第二个虚构量。",
                "formula_group": {
                    "equations": [
                        {
                            "formula_id": "f-norm-extra",
                            "equation_number": "(4.2.1-3)",
                            "equation_number_status": "printed",
                            "latex": "x=y",
                            "text": "x=y",
                            "recognition_status": "verified",
                        }
                    ],
                    "symbol_explanations": {
                        "items": [{"symbol": "x", "description": "第二个虚构量"}]
                    },
                },
            },
        }
    )
    clause = data["clauses"]["normative"][0]
    clause["clause_content"]["content_units"].append(
        {
            "order": 4,
            "content_type": "formula",
            "source_block_ids": ["formula-extra"],
            "formula_ids": ["f-norm-extra"],
        }
    )
    clause["source_block_ids"].append("formula-extra")
    content = clause["clause_content"]
    content["plain_text"] = None
    content.pop("plain_text_renderer_version")
    content.pop("plain_text_source_digest")
    document = Document.model_validate(data)
    rendered = derive_clause_plain_text(document, document.clauses.normative[0])
    assert rendered is not None
    assert rendered[0].count("式中：q：虚构量") == 1
    assert rendered[0].count("式中：x：第二个虚构量") == 1
    assert rendered[0].index("式中：q：虚构量") < rendered[0].index("x=y")
