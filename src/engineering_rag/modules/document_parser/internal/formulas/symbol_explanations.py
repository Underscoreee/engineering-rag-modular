"""Parse bounded, source-retaining '式中' symbol explanations."""

from __future__ import annotations

import re

from engineering_rag.contracts.documents import SymbolExplanationItem, SymbolExplanations
from engineering_rag.modules.document_parser.internal.mineru.models import MinerUElement

from .models import SymbolEvidence, SymbolSourceCoverage

_PREFIX = re.compile(r"^\s*式中\s*[:：]?\s*")
_PLAIN_ITEM = re.compile(r"\s*([^；。]+?)\s*(?:——|--|—)\s*(.+?)(?:；|。|$)")
_SINGLE_PLAIN_ITEM = re.compile(r"^\s*([^；。]{1,80}?)\s*(?:——|--|—)\s*(.+?)\s*$")
_LEADING_SYMBOL = re.compile(r"^\s*([A-Za-zΑ-ωα-ω][A-Za-z0-9_]*)\s+(.+?)(?:；|。|$)")
_STRUCTURAL_BOUNDARY = re.compile(r"^\s*(?:\d+(?:\.\d+)+|\d+\s+\S)")


def is_symbol_start(element: MinerUElement) -> bool:
    if element.raw_type != "text":
        return False
    children = _children(element)
    first_text = next(
        (str(item.get("content")) for item in children if item.get("type") == "text"), ""
    )
    return _PREFIX.match(first_text) is not None


def collect_symbol_explanations(
    elements: list[MinerUElement], start: int
) -> tuple[SymbolExplanations | None, SymbolEvidence, int]:
    items: list[SymbolExplanationItem] = []
    raw_fragments: list[dict[str, object]] = []
    source_indices: list[int] = []
    diagnostics: list[str] = []
    coverage: list[SymbolSourceCoverage] = []
    position = start
    while position < len(elements):
        element = elements[position]
        if position > start and _is_boundary(element):
            break
        if element.raw_type != "text":
            break
        item_start = len(items)
        parsed, parser_consumed_all = _parse_element(element, first=position == start)
        if _has_ambiguous_inline_separator(element):
            diagnostics.append(
                f"ambiguous OCR separator between symbols in block {element.source_index} retained"
            )
        if parsed:
            items.extend(parsed)
            item_indices = list(range(item_start, len(items)))
        elif items and element.text:
            previous = items[-1]
            previous.description = f"{previous.description}{element.text.strip()}"
            diagnostics.append(f"continued wrapped description from block {element.source_index}")
            item_indices = [len(items) - 1]
            parser_consumed_all = True
        else:
            diagnostics.append(f"unparsed symbol text block {element.source_index}")
            item_indices = []
            parser_consumed_all = False
        coverage.append(
            SymbolSourceCoverage(
                source_index=element.source_index,
                item_indices=item_indices,
                fully_consumed=parser_consumed_all,
                unconsumed_text=None if parser_consumed_all else element.text,
                reason=(
                    "all OCR tokens mapped to authoritative symbol explanation"
                    if parser_consumed_all
                    else "source contains unparsed or mixed content"
                ),
            )
        )
        raw_fragments.append(dict(element.raw))
        source_indices.append(element.source_index)
        position += 1
    evidence = SymbolEvidence(
        source_indices=source_indices,
        raw_fragments=raw_fragments,
        source_coverage=coverage,
        diagnostics=diagnostics,
    )
    return SymbolExplanations(items=items) if items else None, evidence, position


def parse_plain_symbol_lines(lines: list[str]) -> SymbolExplanations | None:
    items: list[SymbolExplanationItem] = []
    for index, line in enumerate(lines):
        text = _PREFIX.sub("", line, count=1) if index == 0 else line
        parsed = _parse_plain(text)
        if parsed:
            items.extend(parsed)
        elif items:
            items[-1].description = f"{items[-1].description}{text.strip()}"
    return SymbolExplanations(items=items) if items else None


def _parse_element(
    element: MinerUElement, *, first: bool
) -> tuple[list[SymbolExplanationItem], bool]:
    children = _children(element)
    if not children:
        return _parse_plain_with_coverage(
            _PREFIX.sub("", element.text or "", count=1) if first else element.text or ""
        )
    prepared: list[dict[str, object]] = []
    for child in children:
        value = child.get("content")
        if not isinstance(value, str):
            continue
        if first and child.get("type") == "text":
            value = _PREFIX.sub("", value, count=1)
            first = False
        if value:
            prepared.append({"type": child.get("type"), "content": value})
    leading_symbols: list[str] = []
    leading_tokens: list[str] = []
    description_parts: list[str] = []
    description_started = False
    for child in prepared:
        value = str(child["content"])
        if child["type"] == "equation_inline" and not description_started:
            symbol = value.strip()
            leading_symbols.append(symbol)
            leading_tokens.append(symbol)
        elif (
            leading_symbols
            and not description_started
            and bool(value.strip())
            and len(value.strip()) <= 3
            and not _contains_cjk(value)
        ):
            leading_tokens.append(value.strip())
        elif value.strip():
            description_started = True
            description_parts.append(value)
    if leading_symbols and description_parts:
        symbol = (
            "".join(token for token in leading_tokens if token)
            if len(leading_tokens) > len(leading_symbols)
            else "、".join(leading_symbols)
        )
        description = "".join(description_parts).strip(" ：:—-").rstrip("；。;").strip()
        return (
            [
                SymbolExplanationItem(
                    symbol=symbol,
                    latex=leading_symbols[0] if len(leading_symbols) == 1 else None,
                    description=description,
                )
            ],
            True,
        )
    plain = "".join(str(child["content"]) for child in prepared)
    return _parse_plain_with_coverage(plain)


def _parse_plain(value: str) -> list[SymbolExplanationItem]:
    return _parse_plain_with_coverage(value)[0]


def _parse_plain_with_coverage(value: str) -> tuple[list[SymbolExplanationItem], bool]:
    single = _SINGLE_PLAIN_ITEM.match(value)
    if single is not None and len(re.findall(r"(?:——|--|—)", value)) == 1:
        symbol = single.group(1).strip()
        raw_description = single.group(2).strip()
        description = raw_description.rstrip("；。;").strip()
        has_mixed_sentence = "。" in raw_description.rstrip("。").strip()
        if symbol and description and not has_mixed_sentence:
            return [SymbolExplanationItem(symbol=symbol, latex=None, description=description)], True
    matches = list(_PLAIN_ITEM.finditer(value))
    items = [
        SymbolExplanationItem(
            symbol=match.group(1).strip(),
            latex=None,
            description=match.group(2).strip(),
        )
        for match in matches
        if match.group(1).strip() and match.group(2).strip()
    ]
    if items:
        remainder = value
        for match in reversed(matches):
            remainder = remainder[: match.start()] + remainder[match.end() :]
        return items, not remainder.strip()
    leading = _LEADING_SYMBOL.match(value)
    if leading is None:
        return [], False
    return (
        [
            SymbolExplanationItem(
                symbol=leading.group(1),
                latex=None,
                description=leading.group(2).strip(),
            )
        ],
        leading.end() == len(value),
    )


def _children(element: MinerUElement) -> list[dict[str, object]]:
    content = element.raw.get("content")
    return [item for item in content if isinstance(item, dict)] if isinstance(content, list) else []


def _has_ambiguous_inline_separator(element: MinerUElement) -> bool:
    children = _children(element)
    for index, child in enumerate(children[1:-1], start=1):
        value = child.get("content")
        if (
            child.get("type") == "text"
            and isinstance(value, str)
            and value.strip()
            and len(value.strip()) <= 3
            and children[index - 1].get("type") == "equation_inline"
            and children[index + 1].get("type") == "equation_inline"
        ):
            return True
    return False


def _contains_cjk(value: str) -> bool:
    return any("\u3400" <= character <= "\u9fff" for character in value)


def _is_boundary(element: MinerUElement) -> bool:
    if element.raw_type in {"equation", "title", "paragraph_title", "page_number", "table"}:
        return True
    return bool(element.text and _STRUCTURAL_BOUNDARY.match(element.text))
