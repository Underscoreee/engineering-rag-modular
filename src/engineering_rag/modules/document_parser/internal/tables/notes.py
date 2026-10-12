"""Parse only explicitly numbered table notes; retain everything else as sidecar evidence."""

from __future__ import annotations

import re

from engineering_rag.contracts.documents import TableNote

_NUMBERED_NOTE = re.compile(r"^\s*(?:注\s*[:：]?\s*)?(\d+)\s*(.+?)\s*$")


def parse_table_notes(values: list[str]) -> tuple[list[TableNote] | None, list[str], list[str]]:
    notes: list[TableNote] = []
    unnumbered: list[str] = []
    diagnostics: list[str] = []
    seen: set[int] = set()
    for value in values:
        match = _NUMBERED_NOTE.match(value)
        if match is None:
            unnumbered.append(value)
            diagnostics.append("unnumbered table note retained only in sidecar")
            continue
        number = int(match.group(1))
        content = match.group(2).strip()
        if number in seen:
            unnumbered.append(value)
            diagnostics.append(f"duplicate note number {number} retained only in sidecar")
            continue
        seen.add(number)
        notes.append(TableNote(number=number, content=content))
    return notes or None, unnumbered, diagnostics
