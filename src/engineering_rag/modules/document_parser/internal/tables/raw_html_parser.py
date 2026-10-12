"""Bounded, non-networking HTML table parser with occupancy-grid validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

from .models import ParsedHtmlCell, ParsedHtmlGrid

MAX_HTML_BYTES = 1_048_576
MAX_ROWS = 500
MAX_COLUMNS = 100
MAX_CELLS = 10_000
MAX_SPAN = 100
MAX_NESTING_DEPTH = 64
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}


class TableHtmlError(ValueError):
    """Raised when HTML cannot be safely represented as one bounded table."""


@dataclass(slots=True)
class _CellToken:
    row_span: int
    col_span: int
    is_header: bool
    parts: list[str] = field(default_factory=list)


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables = 0
        self.table_depth = 0
        self.in_head = False
        self.current_row: list[_CellToken] | None = None
        self.current_cell: _CellToken | None = None
        self.rows: list[list[_CellToken]] = []
        self.diagnostics: list[str] = []
        self._ignored_depth = 0
        self._open_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in _VOID_TAGS:
            self._open_tags.append(tag)
            if len(self._open_tags) > MAX_NESTING_DEPTH:
                raise TableHtmlError(f"HTML nesting exceeds {MAX_NESTING_DEPTH} elements")
        if tag in {"script", "style"}:
            self._ignored_depth += 1
            self.diagnostics.append(f"ignored unsafe {tag} element")
            return
        if self._ignored_depth:
            return
        for name, value in attrs:
            if name.lower() in {"src", "href", "srcset"} and value:
                self.diagnostics.append("ignored external resource attribute")
        if tag == "table":
            if self.table_depth:
                raise TableHtmlError("nested table is not supported")
            self.tables += 1
            if self.tables > 1:
                raise TableHtmlError("multiple table elements must be split before parsing")
            self.table_depth = 1
            return
        if self.table_depth != 1:
            return
        if tag == "thead":
            self.in_head = True
        elif tag == "tr":
            if self.current_row is not None:
                raise TableHtmlError("nested or unclosed tr element")
            if len(self.rows) >= MAX_ROWS:
                raise TableHtmlError(f"table exceeds {MAX_ROWS} source rows")
            self.current_row = []
        elif tag in {"th", "td"}:
            if self.current_row is None or self.current_cell is not None:
                raise TableHtmlError("cell must be directly contained in a row")
            row_span = _span(attrs, "rowspan")
            col_span = _span(attrs, "colspan")
            self.current_cell = _CellToken(
                row_span=row_span,
                col_span=col_span,
                is_header=tag == "th" or self.in_head,
            )
        elif tag == "br" and self.current_cell is not None:
            self.current_cell.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        self._close_open_tag(tag)
        if tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if tag == "table" and self.table_depth == 1:
            if self.current_cell is not None or self.current_row is not None:
                raise TableHtmlError("table ended before its row or cell")
            self.table_depth = 0
            return
        if self.table_depth != 1:
            return
        if tag in {"th", "td"} and self.current_cell is not None:
            if self.current_row is None:
                raise TableHtmlError("cell ended outside a row")
            self.current_row.append(self.current_cell)
            self.current_cell = None
        elif tag == "tr" and self.current_row is not None:
            if self.current_cell is not None:
                raise TableHtmlError("row ended before its cell")
            if not self.current_row:
                raise TableHtmlError("empty table row is not representable")
            self.rows.append(self.current_row)
            self.current_row = None
        elif tag == "thead":
            self.in_head = False

    def _close_open_tag(self, tag: str) -> None:
        for index in range(len(self._open_tags) - 1, -1, -1):
            if self._open_tags[index] == tag:
                del self._open_tags[index:]
                return

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and self.current_cell is not None:
            self.current_cell.parts.append(data)


def parse_html_table(html: str) -> ParsedHtmlGrid:
    """Parse exactly one local HTML table without loading any external resource."""

    if not isinstance(html, str) or not html.strip():
        raise TableHtmlError("table HTML must be non-empty")
    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
        raise TableHtmlError(f"table HTML exceeds {MAX_HTML_BYTES} bytes")
    parser = _TableParser()
    try:
        parser.feed(html)
        parser.close()
    except TableHtmlError:
        raise
    except (ValueError, TypeError) as exc:
        raise TableHtmlError(f"invalid table HTML: {exc}") from exc
    if parser.tables != 1:
        raise TableHtmlError("exactly one table element is required")
    if parser.table_depth or parser.current_row is not None or parser.current_cell is not None:
        raise TableHtmlError("unclosed table markup")
    if not parser.rows:
        raise TableHtmlError("table contains no rows")
    return _build_grid(parser.rows, parser.diagnostics)


def _build_grid(rows: list[list[_CellToken]], diagnostics: list[str]) -> ParsedHtmlGrid:
    occupied: set[tuple[int, int]] = set()
    cells: list[ParsedHtmlCell] = []
    max_row = 0
    max_col = 0
    order = 0
    for row_index, row in enumerate(rows):
        col = 0
        for token in row:
            while (row_index, col) in occupied:
                col += 1
            if col >= MAX_COLUMNS:
                raise TableHtmlError(f"table exceeds {MAX_COLUMNS} columns")
            if row_index + token.row_span > MAX_ROWS or col + token.col_span > MAX_COLUMNS:
                raise TableHtmlError("cell span exceeds configured table bounds")
            covered = {
                (row, column)
                for row in range(row_index, row_index + token.row_span)
                for column in range(col, col + token.col_span)
            }
            if occupied & covered:
                raise TableHtmlError("table cell spans overlap")
            occupied.update(covered)
            cells.append(
                ParsedHtmlCell(
                    row=row_index,
                    col=col,
                    row_span=token.row_span,
                    col_span=token.col_span,
                    text=_normalize_text("".join(token.parts)),
                    is_header=token.is_header,
                    source_order=order,
                )
            )
            order += 1
            if order > MAX_CELLS:
                raise TableHtmlError(f"table exceeds {MAX_CELLS} cells")
            max_row = max(max_row, row_index + token.row_span)
            max_col = max(max_col, col + token.col_span)
            col += token.col_span
    expected = max_row * max_col
    complete = len(occupied) == expected and max_row <= len(rows)
    if max_row > len(rows):
        diagnostics = [*diagnostics, "rowspan exceeds the explicitly printed source rows"]
    if not complete:
        diagnostics = [*diagnostics, "occupancy grid contains unfilled positions"]
    return ParsedHtmlGrid(
        row_count=max_row,
        column_count=max_col,
        cells=cells,
        complete=complete,
        diagnostics=diagnostics,
    )


def _span(attrs: list[tuple[str, str | None]], name: str) -> int:
    raw = next((value for key, value in attrs if key.lower() == name), None)
    if raw is None:
        return 1
    try:
        value = int(raw)
    except ValueError as exc:
        raise TableHtmlError(f"{name} must be an integer") from exc
    if not 1 <= value <= MAX_SPAN:
        raise TableHtmlError(f"{name} must be between 1 and {MAX_SPAN}")
    return value


def _normalize_text(value: str) -> str:
    lines = [" ".join(line.split()) for line in value.splitlines()]
    return "\n".join(line for line in lines if line).strip()
