"""Decode the observed MinerU 4.x MiddleJson protocol without guessing fields."""

from __future__ import annotations

import json
from pathlib import Path

from .models import MinerUBbox, MinerUElement, MinerUPage


class MinerUProtocolError(ValueError):
    """Raised when an output is not supported MinerU 4.x MiddleJson."""


def read_middle_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MinerUProtocolError(f"cannot read MiddleJson {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise MinerUProtocolError("MiddleJson root must be an object")
    return payload


def normalize_middle_json(
    payload: dict[str, object],
    *,
    expected_pages: list[int],
    page_idx_to_original: dict[int, int] | None = None,
) -> tuple[str, str, str, list[MinerUPage], list[str]]:
    if payload.get("schema") != "docvortex.middle":
        raise MinerUProtocolError("output is not docvortex.middle")
    if payload.get("schema_version") != "2.0":
        raise MinerUProtocolError("unsupported MiddleJson protocol version")
    metadata = _mapping(payload.get("metadata"), "metadata")
    producer = _mapping(metadata.get("producer"), "metadata.producer")
    version = producer.get("version")
    if (
        producer.get("name") != "mineru"
        or not isinstance(version, str)
        or not version.startswith("4.")
    ):
        raise MinerUProtocolError("MiddleJson was not produced by MinerU 4.x")
    extensions = _mapping(payload.get("extensions"), "extensions")
    _mapping(extensions.get("mineru"), "extensions.mineru")
    layout = _mapping(extensions.get("docvortex_layout"), "extensions.docvortex_layout")
    if layout.get("version") != 1:
        raise MinerUProtocolError("unsupported docvortex_layout version")
    dimensions: dict[int, tuple[float, float]] = {}
    for item in _list(layout.get("pages"), "layout.pages"):
        record = _mapping(item, "layout page")
        page_idx = _integer(record.get("page_idx"), "layout page_idx")
        dimensions[page_idx] = (
            _positive_number(record.get("width_pt"), "width_pt"),
            _positive_number(record.get("height_pt"), "height_pt"),
        )
    page_map = page_idx_to_original or {number - 1: number for number in expected_pages}
    if set(page_map.values()) != set(expected_pages):
        raise MinerUProtocolError("page mapping does not cover expected original pages")
    expected_indexes = set(page_map)
    pages: list[MinerUPage] = []
    diagnostics: list[str] = []
    seen: set[int] = set()
    for raw_page in _list(payload.get("pages"), "pages"):
        page = _mapping(raw_page, "page")
        page_idx = _integer(page.get("page_idx"), "page_idx")
        if page_idx not in expected_indexes:
            raise MinerUProtocolError(f"unexpected source page_idx {page_idx}")
        if page_idx in seen:
            raise MinerUProtocolError(f"duplicate source page_idx {page_idx}")
        seen.add(page_idx)
        if page_idx not in dimensions:
            raise MinerUProtocolError(f"page_idx {page_idx} lacks PDF point geometry")
        width, height = dimensions[page_idx]
        elements = [
            _normalize_element(
                block,
                page_idx=page_idx,
                page_number=page_map[page_idx],
                fallback_index=index,
            )
            for index, block in enumerate(_list(page.get("blocks", []), "page.blocks"))
        ]
        pages.append(
            MinerUPage(
                page_number=page_map[page_idx],
                page_idx=page_idx,
                width_points=width,
                height_points=height,
                elements=elements,
            )
        )
    missing = sorted(expected_indexes - seen)
    if missing:
        diagnostics.append(f"MiddleJson omitted source page_idx values: {missing}")
    pages.sort(key=lambda item: item.page_number)
    return (
        str(payload["schema"]),
        str(payload["schema_version"]),
        version,
        pages,
        diagnostics,
    )


def _normalize_element(
    raw: object, *, page_idx: int, page_number: int, fallback_index: int
) -> MinerUElement:
    block = _mapping(raw, "block")
    raw_type = block.get("type")
    if not isinstance(raw_type, str) or not raw_type:
        raise MinerUProtocolError("block type must be non-empty")
    source_index = block.get("index", fallback_index)
    if not isinstance(source_index, int) or source_index < 0:
        raise MinerUProtocolError("block index must be a nonnegative integer")
    diagnostics: list[str] = []
    bbox = _bbox(block.get("bbox"), diagnostics)
    text: str | None = None
    latex: str | None = None
    table_html: str | None = None
    table_caption: str | None = None
    table_footnotes: list[str] = []
    content = block.get("content")
    if raw_type == "equation" and isinstance(content, str):
        latex = content.strip() or None
    elif raw_type == "table" and isinstance(content, list):
        for item in content:
            child = _mapping(item, "table content")
            child_type = child.get("type")
            child_text = _content_text(child.get("content"))
            if child_type == "table_body" and isinstance(child.get("content"), str):
                table_html = str(child["content"])
            elif child_type == "table_caption":
                table_caption = child_text or None
            elif child_type == "table_footnote" and child_text:
                table_footnotes.append(child_text)
        text = table_caption
    else:
        text = _content_text(content) or None
    if bbox is None:
        diagnostics.append("element has no trustworthy bbox and remains sidecar-only")
    return MinerUElement(
        page_number=page_number,
        page_idx=page_idx,
        source_index=source_index,
        raw_type=raw_type,
        bbox=bbox,
        text=text,
        latex=latex,
        table_html=table_html,
        table_caption=table_caption,
        table_footnotes=table_footnotes,
        raw=dict(block),
        diagnostics=diagnostics,
    )


def _bbox(value: object, diagnostics: list[str]) -> MinerUBbox | None:
    if value is None:
        return None
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value)
    ):
        raise MinerUProtocolError("bbox must contain four numeric normalized coordinates")
    try:
        return MinerUBbox(x_min=value[0], y_min=value[1], x_max=value[2], y_max=value[3])
    except ValueError as exc:
        diagnostics.append(f"invalid bbox: {exc}")
        return None


def _content_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, list):
        return ""
    pieces: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            pieces.append(content.strip())
    return "".join(pieces)


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise MinerUProtocolError(f"{name} must be an object")
    return value


def _list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise MinerUProtocolError(f"{name} must be an array")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MinerUProtocolError(f"{name} must be a nonnegative integer")
    return value


def _positive_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise MinerUProtocolError(f"{name} must be positive")
    return float(value)
