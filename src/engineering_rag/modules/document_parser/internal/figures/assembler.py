"""Caption-anchored aggregation of MinerU engineering figure evidence."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from uuid import NAMESPACE_URL, uuid5

from engineering_rag.contracts.common import ArtifactRef
from engineering_rag.modules.document_parser.internal.mineru.models import (
    MinerUBbox,
    MinerUElement,
    MinerUParseResult,
)

from .models import (
    FigureAssemblyResult,
    FigureAssetEvidence,
    FigurePlacement,
    FigureSidecar,
    FigureSourceConsumption,
)

FIGURE_ASSEMBLER_VERSION = "1.0.0"
_CAPTION = re.compile(r"^\s*图\s*(?P<number>\d+(?:\.\d+)+(?:[-—]\d+)?)\s*(?P<title>\S.*)$")
_FORMULA_TAG = re.compile(r"\\tag\s*\{")


def assemble_mineru_figures(result: MinerUParseResult) -> FigureAssemblyResult:
    placements: dict[tuple[int, int], FigurePlacement] = {}
    consumed: set[tuple[int, int]] = set()
    sidecars: list[FigureSidecar] = []
    omitted: list[dict[str, object]] = []
    for page in result.pages:
        positions = {
            element.source_index: position for position, element in enumerate(page.elements)
        }
        for element in page.elements:
            if element.raw_type not in {"image", "figure"} or element.bbox is None:
                continue
            caption, caption_bbox = _embedded_caption(element)
            if caption is None:
                continue
            built = _build_figure(
                result,
                image_elements=[element],
                internal_elements=[],
                caption_element=element,
                caption=caption,
                caption_bbox=caption_bbox,
                aggregation_basis="mineru_image_body_with_embedded_caption",
            )
            if built is None:
                omitted.append(_omission(element, "figure_has_no_safe_asset_reference"))
                continue
            placement, sidecar, keys = built
            placements[(page.page_number, element.source_index)] = placement
            sidecars.append(sidecar)
            consumed.update(keys)

        for caption_element in page.elements:
            key = (page.page_number, caption_element.source_index)
            caption_match = _caption_match(caption_element.text)
            if key in consumed or caption_match is None or caption_element.bbox is None:
                continue
            position = positions[caption_element.source_index]
            image_elements, internal_elements = _preceding_visual_run(
                page.elements,
                position,
                caption_element.bbox,
                already_consumed=consumed,
            )
            if not image_elements:
                continue
            anchor = min(image_elements, key=lambda item: positions[item.source_index])
            built = _build_figure(
                result,
                image_elements=image_elements,
                internal_elements=internal_elements,
                caption_element=caption_element,
                caption=caption_element.text or "",
                caption_bbox=caption_element.bbox,
                aggregation_basis="caption_anchored_contiguous_visual_region",
                anchor=anchor,
            )
            if built is None:
                omitted.append(_omission(caption_element, "figure_has_no_safe_asset_reference"))
                continue
            placement, sidecar, keys = built
            placements[(page.page_number, anchor.source_index)] = placement
            sidecars.append(sidecar)
            consumed.update(keys)
    return FigureAssemblyResult(
        placements=placements,
        consumed=consumed,
        sidecars=sidecars,
        omitted=omitted,
    )


def _preceding_visual_run(
    elements: list[MinerUElement],
    caption_position: int,
    caption_bbox: MinerUBbox,
    *,
    already_consumed: set[tuple[int, int]],
) -> tuple[list[MinerUElement], list[MinerUElement]]:
    candidates: list[MinerUElement] = []
    for element in reversed(elements[:caption_position]):
        if (element.page_number, element.source_index) in already_consumed:
            break
        if element.bbox is None:
            break
        if element.raw_type in {"image", "figure"}:
            candidates.append(element)
            continue
        if (
            element.raw_type == "equation"
            and element.latex
            and _FORMULA_TAG.search(element.latex) is None
        ):
            candidates.append(element)
            continue
        break
    images = [item for item in candidates if item.raw_type in {"image", "figure"}]
    internals = [item for item in candidates if item.raw_type == "equation"]
    associated = [item for item in internals if _inside_visual_column(item, images, caption_bbox)]
    if len(associated) != len(internals):
        return [], []
    return sorted(images, key=lambda item: item.source_index), sorted(
        associated, key=lambda item: item.source_index
    )


def _inside_visual_column(
    element: MinerUElement, images: list[MinerUElement], caption_bbox: MinerUBbox
) -> bool:
    if element.bbox is None or element.bbox.y_max >= caption_bbox.y_min:
        return False
    center_x = (element.bbox.x_min + element.bbox.x_max) / 2
    return any(
        image.bbox is not None
        and image.bbox.x_min <= center_x <= image.bbox.x_max
        and image.bbox.y_min <= element.bbox.y_min
        for image in images
    )


def _build_figure(
    result: MinerUParseResult,
    *,
    image_elements: list[MinerUElement],
    internal_elements: list[MinerUElement],
    caption_element: MinerUElement,
    caption: str,
    caption_bbox: MinerUBbox | None,
    aggregation_basis: str,
    anchor: MinerUElement | None = None,
) -> tuple[FigurePlacement, FigureSidecar, set[tuple[int, int]]] | None:
    match = _caption_match(caption)
    if match is None:
        return None
    anchor = anchor or image_elements[0]
    block_id = _source_block_id(result, anchor)
    assets = [
        evidence for element in image_elements for evidence in _asset_evidence(result, element)
    ]
    if not assets:
        return None
    bbox = _union_bbox(
        [item.bbox for item in image_elements + internal_elements if item.bbox is not None]
    )
    artifact = _artifact(result, block_id, assets)
    source_consumption: list[FigureSourceConsumption] = []
    for element in image_elements:
        source_consumption.append(
            _consumption(
                result,
                element,
                block_id,
                "figure_body_and_caption"
                if element.source_index == caption_element.source_index
                else "figure_body",
            )
        )
    source_consumption.extend(
        _consumption(result, element, block_id, "figure_internal_text")
        for element in internal_elements
    )
    if caption_element.source_index not in {item.source_index for item in image_elements}:
        source_consumption.append(_consumption(result, caption_element, block_id, "figure_caption"))
    keys = {(item.source_page_number, item.source_index) for item in source_consumption}
    number = match.group("number")
    title = match.group("title").strip()
    return (
        FigurePlacement(
            block_id=block_id,
            anchor_source_index=anchor.source_index,
            bbox=bbox,
            caption=caption.strip(),
            figure_number=number,
            figure_caption=title,
            asset=artifact,
        ),
        FigureSidecar(
            block_id=block_id,
            page_number=anchor.page_number,
            figure_number=number,
            figure_caption=title,
            full_caption=caption.strip(),
            figure_bbox=bbox,
            caption_bbox=caption_bbox,
            source_consumption=source_consumption,
            assets=assets,
            aggregation_basis=aggregation_basis,
            diagnostics=(
                ["multiple MinerU image fragments represented by one logical Figure asset"]
                if len(assets) > 1
                else []
            ),
        ),
        keys,
    )


def _embedded_caption(element: MinerUElement) -> tuple[str | None, MinerUBbox | None]:
    if element.image_caption:
        return element.image_caption, element.image_caption_bbox
    content = element.raw.get("content")
    if not isinstance(content, list):
        return None, None
    diagnostics: list[str] = []
    for child in content:
        if not isinstance(child, dict) or child.get("type") != "image_caption":
            continue
        text = _raw_text(child.get("content"))
        return text or None, _raw_bbox(child.get("bbox"), diagnostics)
    return None, None


def _asset_evidence(result: MinerUParseResult, element: MinerUElement) -> list[FigureAssetEvidence]:
    references = list(element.image_paths)
    if not references:
        content = element.raw.get("content")
        if isinstance(content, list):
            references.extend(
                str(child["image_path"])
                for child in content
                if isinstance(child, dict)
                and child.get("type") == "image_body"
                and isinstance(child.get("image_path"), str)
                and child.get("image_path")
            )
    evidence: list[FigureAssetEvidence] = []
    for reference in references:
        path, diagnostics = _safe_asset_path(result, reference)
        digest = None
        size = None
        if path is not None:
            payload = path.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            size = len(payload)
        if element.bbox is not None:
            evidence.append(
                FigureAssetEvidence(
                    source_page_number=element.page_number,
                    source_index=element.source_index,
                    raw_reference=reference,
                    resolved_path=str(path) if path is not None else None,
                    sha256=digest,
                    size_bytes=size,
                    bbox=element.bbox,
                    diagnostics=diagnostics,
                )
            )
    return evidence


def _safe_asset_path(result: MinerUParseResult, raw: str) -> tuple[Path | None, list[str]]:
    reference = PurePosixPath(raw)
    if reference.is_absolute() or ".." in reference.parts or "://" in raw:
        return None, ["rejected unsafe figure image path"]
    root = result.raw_middle_json.parent.resolve()
    candidate = (root / Path(*reference.parts)).resolve()
    if not candidate.is_relative_to(root):
        return None, ["rejected figure image path outside raw bundle"]
    if not candidate.is_file() or candidate.is_symlink():
        return None, ["figure source image is missing or is a symlink"]
    return candidate, []


def _artifact(
    result: MinerUParseResult, block_id: str, assets: list[FigureAssetEvidence]
) -> ArtifactRef:
    canonical = json.dumps(
        [
            {
                "raw_reference": item.raw_reference,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
            }
            for item in assets
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    artifact_id = _stable_id("asset", block_id)
    if len(assets) == 1:
        item = assets[0]
        return ArtifactRef(
            artifact_id=artifact_id,
            artifact_type="figure_image",
            uri=(
                f"urn:sha256:{item.sha256}"
                if item.sha256 is not None
                else f"urn:engineering-rag:mineru-image:{artifact_id}"
            ),
            media_type=_media_type(item.raw_reference),
            artifact_version=result.producer_version,
            sha256=item.sha256,
            size_bytes=item.size_bytes,
        )
    return ArtifactRef(
        artifact_id=artifact_id,
        artifact_type="logical_figure",
        uri=f"urn:engineering-rag:figure:{artifact_id}",
        media_type="application/vnd.engineering-rag.figure+json",
        artifact_version=FIGURE_ASSEMBLER_VERSION,
        sha256=digest,
        size_bytes=len(canonical),
    )


def _consumption(
    result: MinerUParseResult,
    element: MinerUElement,
    block_id: str,
    role: str,
) -> FigureSourceConsumption:
    assert element.bbox is not None
    return FigureSourceConsumption(
        source_page_number=element.page_number,
        source_index=element.source_index,
        source_block_id=_source_block_id(result, element),
        raw_type=element.raw_type,
        raw_text=element.text,
        raw_latex=element.latex,
        raw_bbox=element.bbox,
        semantic_role=role,
        target_block_id=block_id,
    )


def _caption_match(text: str | None) -> re.Match[str] | None:
    return _CAPTION.match((text or "").strip())


def _raw_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, list):
        return ""
    return "".join(
        str(item.get("content", "")).strip()
        for item in value
        if isinstance(item, dict) and isinstance(item.get("content"), str)
    )


def _raw_bbox(value: object, diagnostics: list[str]) -> MinerUBbox | None:
    if not isinstance(value, list) or len(value) != 4:
        diagnostics.append("caption bbox is absent or invalid")
        return None
    try:
        return MinerUBbox(x_min=value[0], y_min=value[1], x_max=value[2], y_max=value[3])
    except ValueError:
        diagnostics.append("caption bbox is absent or invalid")
        return None


def _union_bbox(values: list[MinerUBbox]) -> MinerUBbox:
    return MinerUBbox(
        x_min=min(item.x_min for item in values),
        y_min=min(item.y_min for item in values),
        x_max=max(item.x_max for item in values),
        y_max=max(item.y_max for item in values),
    )


def _source_block_id(result: MinerUParseResult, element: MinerUElement) -> str:
    return _stable_id(
        "block",
        result.source_sha256,
        str(element.page_number),
        str(element.source_index),
        element.raw_type,
    )


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{uuid5(NAMESPACE_URL, '|'.join(parts)).hex}"


def _media_type(reference: str) -> str:
    suffix = PurePosixPath(reference).suffix.lower()
    return {".png": "image/png", ".jpeg": "image/jpeg", ".jpg": "image/jpeg"}.get(
        suffix, "application/octet-stream"
    )


def _omission(element: MinerUElement, reason: str) -> dict[str, object]:
    return {
        "page_number": element.page_number,
        "source_index": element.source_index,
        "raw_type": element.raw_type,
        "reason": reason,
    }
