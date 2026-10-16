"""Lossless-enough deterministic renderers for public V2.4 semantic objects."""

import json

from engineering_rag.contracts.documents import FormulaGroup, LogicalTable


def render_table(table: LogicalTable) -> str:
    payload = {
        "table_number": table.table_number,
        "title": table.title,
        "columns": [column.model_dump(mode="json") for column in table.columns],
        "data": [row.model_dump(mode="json") for row in table.data or []],
        "notes": [note.model_dump(mode="json") for note in table.notes or []],
        "raw_grid": table.raw_grid.model_dump(mode="json") if table.raw_grid else None,
        "extraction_status": table.extraction_status.value,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def render_formula(formula_group_id: str, group: FormulaGroup) -> str:
    payload = {
        "formula_group_id": formula_group_id,
        "equations": [equation.model_dump(mode="json") for equation in group.equations],
        "symbol_explanations": (
            group.symbol_explanations.model_dump(mode="json")
            if group.symbol_explanations is not None
            else None
        ),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
