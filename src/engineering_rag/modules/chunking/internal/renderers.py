"""Deterministic retrieval-semantic renderers for public V2.4 objects."""

import json

from engineering_rag.contracts.documents import FormulaGroup, LogicalTable


def render_table(table: LogicalTable) -> str:
    return _stable_json(_build_table_semantic_content(table))


def render_formula(group: FormulaGroup) -> str:
    return _stable_json(_build_formula_semantic_content(group))


def _build_table_semantic_content(table: LogicalTable) -> dict[str, object]:
    column_keys = [column.key for column in table.columns]
    return {
        "table_number": table.table_number,
        "title": table.title,
        "columns": [
            {"key": column.key, "header_path": column.header_path} for column in table.columns
        ],
        "data": (
            [{key: row.root[key] for key in column_keys} for row in table.data]
            if table.data is not None
            else None
        ),
        "notes": (
            [{"number": note.number, "content": note.content} for note in table.notes]
            if table.notes is not None
            else None
        ),
    }


def _build_formula_semantic_content(group: FormulaGroup) -> dict[str, object]:
    return {
        "equations": [
            {"equation_number": equation.equation_number, "latex": equation.latex}
            for equation in group.equations
        ],
        "symbol_explanations": (
            [
                {
                    "latex": item.latex or item.symbol,
                    "content": item.description,
                }
                for item in group.symbol_explanations.items
            ]
            if group.symbol_explanations is not None
            else None
        ),
    }


def _stable_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
