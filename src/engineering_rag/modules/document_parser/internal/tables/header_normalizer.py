"""Conservative header-path and flat-row derivation from a retained raw grid."""

from __future__ import annotations

import re

from engineering_rag.contracts.documents import TableColumn, TableColumnRole, TableRow

from .models import ParsedHtmlCell, ParsedHtmlGrid

_ROW_HEADER_TERMS = {"类别", "种类", "项目", "工况", "环境类别", "环境等级", "板的类别"}


def infer_header_row_count(
    grid: ParsedHtmlGrid, *, mineru_caption: str | None = None
) -> tuple[int, str]:
    explicit_rows: list[int] = []
    for row in range(grid.row_count):
        cells = [cell for cell in grid.cells if cell.row == row]
        if cells and any(cell.is_header for cell in cells):
            explicit_rows.append(row)
        elif explicit_rows:
            break
    if explicit_rows and explicit_rows == list(range(len(explicit_rows))):
        return len(explicit_rows), "explicit_th_or_thead"
    if mineru_caption and _row_is_fully_covered(grid, 0):
        return 1, "inferred_first_printed_row_from_captioned_mineru_table"
    return 0, "no_trustworthy_header_evidence"


def build_header_paths(grid: ParsedHtmlGrid, header_rows: int) -> list[list[str]]:
    if header_rows <= 0:
        return []
    paths: list[list[str]] = []
    for col in range(grid.column_count):
        path: list[str] = []
        seen_cells: set[int] = set()
        for row in range(header_rows):
            cell = cell_covering(grid, row, col)
            if cell is None or cell.source_order in seen_cells or not cell.text:
                continue
            seen_cells.add(cell.source_order)
            if not path or _signature(path[-1]) != _signature(cell.text):
                path.append(cell.text)
        if not path:
            return []
        paths.append(path)
    return paths


def build_columns(grid: ParsedHtmlGrid, header_paths: list[list[str]]) -> list[TableColumn]:
    if len(header_paths) != grid.column_count:
        return []
    columns: list[TableColumn] = []
    for index, path in enumerate(header_paths):
        has_vertical_merge = any(
            cell.col <= index < cell.col + cell.col_span and cell.row_span > 1 and cell.row >= 1
            for cell in grid.cells
        )
        leaf = _signature(path[-1])
        role = (
            TableColumnRole.ROW_HEADER
            if leaf in _ROW_HEADER_TERMS or (index == 0 and has_vertical_merge)
            else TableColumnRole.VALUE
        )
        columns.append(
            TableColumn(
                key=f"column_{index + 1}",
                header_path=path,
                role=role,
                derived=True,
                description="Derived from retained HTML header topology; machine-unverified",
            )
        )
    return columns


def build_data_rows(
    grid: ParsedHtmlGrid,
    columns: list[TableColumn],
    *,
    header_rows: int,
    page_number: int,
    block_id: str,
) -> list[TableRow]:
    if not columns:
        return []
    rows: list[TableRow] = []
    for row_index in range(header_rows, grid.row_count):
        values: dict[str, str | int | None] = {}
        for col_index, column in enumerate(columns):
            cell = cell_covering(grid, row_index, col_index)
            values[column.key] = (
                cell.text
                if cell is not None and cell.row == row_index and cell.col == col_index
                else None
            )
        values["source_page"] = page_number
        values["source_block_id"] = block_id
        rows.append(TableRow(values))
    return rows


def cell_covering(grid: ParsedHtmlGrid, row: int, col: int) -> ParsedHtmlCell | None:
    return next(
        (
            cell
            for cell in grid.cells
            if cell.row <= row < cell.row + cell.row_span
            and cell.col <= col < cell.col + cell.col_span
        ),
        None,
    )


def normalized_header_signature(paths: list[list[str]]) -> tuple[str, ...]:
    return tuple("/".join(_signature(item) for item in path) for path in paths)


def _row_is_fully_covered(grid: ParsedHtmlGrid, row: int) -> bool:
    return all(cell_covering(grid, row, col) is not None for col in range(grid.column_count))


def _signature(value: str) -> str:
    return re.sub(r"[\s\\{}()（）_\-]", "", value).casefold()
