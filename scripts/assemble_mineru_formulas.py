#!/usr/bin/env python3
"""Replay three bounded MinerU formula cases into frozen V2.4 artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path

from engineering_rag.contracts.common import FileRef
from engineering_rag.contracts.documents import BlockType, Document, StandardMetadata
from engineering_rag.modules.document_parser.internal.formulas.assembler import (
    FORMULA_ASSEMBLER_VERSION,
)
from engineering_rag.modules.document_parser.internal.formulas.models import (
    FormulaSemanticCoverage,
    FormulaSidecar,
)
from engineering_rag.modules.document_parser.internal.mineru.models import MinerUParseResult
from engineering_rag.modules.document_parser.internal.mineru.v24_adapter import adapt_to_v24

CASE_INPUTS = {
    "GB-E332": (24, "P024-fallback"),
    "GB-E621": (50, "P050"),
    "GB-EEXPL": (301, "P301"),
}
MAX_INPUT_BYTES = 64 * 1024 * 1024


def main() -> int:
    args = _arguments()
    source_size, page_count = _verify_pdf(args.pdf, args.expected_sha256)
    case_ids = list(CASE_INPUTS) if args.all_cases else args.case_id
    if len(case_ids) > args.max_cases:
        raise SystemExit(f"refusing to process more than {args.max_cases} cases")
    summaries: list[dict[str, object]] = []
    for case_id in case_ids:
        page_number, source_name = CASE_INPUTS[case_id]
        normalized, source_manifest, fallback = _input_paths(args, source_name)
        result = MinerUParseResult.model_validate_json(_read_bounded(normalized, normalized.parent))
        _validate_result(result, page_number, args.expected_sha256)
        case_root = args.output / case_id
        summary = _write_case(
            result,
            case_id=case_id,
            page_number=page_number,
            case_root=case_root,
            source_manifest=source_manifest,
            fallback=fallback,
            pdf=args.pdf,
            source_size=source_size,
            page_count=page_count,
        )
        summaries.append(summary)
    _write_json(
        args.output / "run-summary.json",
        {
            "algorithm_version": FORMULA_ASSEMBLER_VERSION,
            "source_sha256": args.expected_sha256,
            "local_replay_only": True,
            "accuracy_metrics_computed": False,
            "cases": summaries,
        },
    )
    print(json.dumps({"cases": len(summaries), "output": str(args.output)}, ensure_ascii=False))
    return 0


def _input_paths(
    args: argparse.Namespace, source_name: str
) -> tuple[Path, Path | None, dict[str, object] | None]:
    if source_name == "P024-fallback":
        normalized = _safe_child(args.page24_fallback_root, Path("normalized.json"))
        fallback = {
            "kind": "local_rasterized_page_fallback",
            "original_physical_page": 24,
            "mineru_source_page": 1,
            "derived_pdf": str(args.page24_derived_pdf),
            "derived_pdf_sha256": _sha256(args.page24_derived_pdf),
            "raster_dpi": 200,
            "original_direct_run_failure_manifest": str(
                args.input_root / "P024" / "single_page" / "manifest.json"
            ),
        }
        return normalized, None, fallback
    root = _safe_child(args.input_root, Path(source_name) / "single_page")
    return root / "normalized.json", root / "manifest.json", None


def _write_case(
    result: MinerUParseResult,
    *,
    case_id: str,
    page_number: int,
    case_root: Path,
    source_manifest: Path | None,
    fallback: dict[str, object] | None,
    pdf: Path,
    source_size: int,
    page_count: int,
) -> dict[str, object]:
    started = time.perf_counter()
    adaptation = adapt_to_v24(
        result,
        source_file=FileRef(
            file_id=f"sha256-{result.source_sha256}",
            uri=pdf.name,
            mime_type="application/pdf",
            sha256=result.source_sha256,
            size_bytes=source_size,
        ),
        standard=StandardMetadata(
            standard_name="混凝土结构设计规范",
            standard_code="GB 50010-2010",
            edition="2015年版",
            language="zh-CN",
        ),
        page_count=page_count,
    )
    document = Document.model_validate_json(adaptation.document.model_dump_json())
    case_root.mkdir(parents=True, exist_ok=True)
    raw_root = case_root / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    raw_copy = raw_root / "middle_json.json"
    if raw_copy.exists():
        if _sha256(raw_copy) != _sha256(result.raw_middle_json):
            raise SystemExit("refusing to replace an existing non-identical raw MiddleJson")
    else:
        shutil.copyfile(result.raw_middle_json, raw_copy)
    grouped = case_id == "GB-E621"
    _write_formula_sidecars(
        adaptation.formula_sidecars,
        case_root,
        directory="formula_sidecars_grouped" if grouped else "formula_sidecars",
    )
    document_name = "document.grouped.partial.json" if grouped else "document.partial.json"
    (case_root / document_name).write_text(document.model_dump_json(indent=2), encoding="utf-8")
    if grouped:
        _write_json(
            case_root / "formula_semantic_group_sidecar.json",
            {
                "algorithm_version": FORMULA_ASSEMBLER_VERSION,
                "source_pdf_sha256": result.source_sha256,
                "source_middle_json_sha256": _sha256(result.raw_middle_json),
                "raw_layer_immutable": True,
                "groups": [
                    sidecar.model_dump(mode="json") for sidecar in adaptation.formula_sidecars
                ],
            },
        )
        _write_json(
            case_root / "formula_source_consumption_report.json",
            {
                "algorithm_version": FORMULA_ASSEMBLER_VERSION,
                "source_pdf_sha256": result.source_sha256,
                "condition_sources": [
                    {
                        "source_block_id": condition.raw_source_block_ids[0],
                        "source_page_number": condition.source_page_number,
                        "source_index": condition.source_index,
                        "raw_text": condition.raw_text,
                        "raw_bbox": condition.bbox.model_dump(mode="json"),
                        "consumed_text_ranges": [[0, len(condition.raw_text)]],
                        "target_formula_group_id": sidecar.formula_group_id,
                        "target_formula_ids": condition.target_formula_ids,
                        "semantic_role": "condition",
                        "disposition": "consumed",
                        "review_status": condition.review_status,
                        "correction_evidence": condition.match_evidence,
                        "diagnostics": condition.diagnostics,
                    }
                    for sidecar in adaptation.formula_sidecars
                    for condition in sidecar.conditions
                ],
                "symbol_explanation_sources": [
                    item.model_dump(mode="json") for item in adaptation.formula_dedup_coverage
                ],
                "summary": {
                    "condition_sources_consumed": sum(
                        len(sidecar.conditions) for sidecar in adaptation.formula_sidecars
                    ),
                    "symbol_sources_consumed": sum(
                        item.duplicate_disposition == "consumed"
                        for item in adaptation.formula_dedup_coverage
                    ),
                    "unresolved_sources_retained": sum(
                        item.duplicate_disposition != "consumed"
                        for item in adaptation.formula_dedup_coverage
                    ),
                    "cross_page_incomplete_sources": sum(
                        item.cross_page_incomplete for item in adaptation.formula_dedup_coverage
                    ),
                },
            },
        )
    formulas_name = "formulas.grouped.json" if grouped else "formulas.json"
    _write_json(
        case_root / formulas_name,
        [
            {
                "block_id": block.block_id,
                "formula_group_id": block.formula_group_id,
                "page_number": page.page_number,
                "bbox": block.bbox.model_dump(mode="json"),
                "formula_group": block.ocr.formula_group.model_dump(mode="json"),
            }
            for page in document.pages
            for block in page.blocks
            if block.block_type == BlockType.FORMULA
            and block.ocr is not None
            and block.ocr.formula_group is not None
        ],
    )
    diagnostics_name = "diagnostics.grouped.json" if grouped else "diagnostics.json"
    _write_json(
        case_root / diagnostics_name,
        {
            "normalizer": result.diagnostics,
            "formula_omissions": adaptation.formula_diagnostics,
            "formula_sidecars": [
                {
                    "formula_group_id": item.formula_group_id,
                    "diagnostics": item.diagnostics,
                    "symbol_diagnostics": (
                        item.symbol_evidence.diagnostics if item.symbol_evidence else []
                    ),
                }
                for item in adaptation.formula_sidecars
            ],
            "ground_truth_status": "candidate_pending_human_review",
            "accuracy_metrics_computed": False,
        },
    )
    _render_overlay(
        pdf,
        document,
        result,
        adaptation.formula_sidecars,
        case_root / "overlays",
        grouped=grouped,
        dedup_coverage=adaptation.formula_dedup_coverage,
    )
    formulas = [
        block
        for page in document.pages
        for block in page.blocks
        if block.block_type == BlockType.FORMULA
    ]
    equations = [
        equation
        for block in formulas
        if block.ocr is not None and block.ocr.formula_group is not None
        for equation in block.ocr.formula_group.equations
    ]
    summary = {
        "case_id": case_id,
        "status": "succeeded",
        "original_physical_page": page_number,
        "formula_group_count": len(formulas),
        "equation_count": len(equations),
        "printed_equation_numbers": [
            equation.equation_number
            for equation in equations
            if equation.equation_number is not None
        ],
        "symbol_item_count": sum(
            len(block.ocr.formula_group.symbol_explanations.items)
            if block.ocr and block.ocr.formula_group and block.ocr.formula_group.symbol_explanations
            else 0
            for block in formulas
        ),
        "task_1_2_inference_seconds": result.elapsed_seconds,
        "task_1_4_postprocess_seconds": time.perf_counter() - started,
    }
    provenance: dict[str, object] = {
        **summary,
        "algorithm_version": FORMULA_ASSEMBLER_VERSION,
        "source_pdf_sha256": result.source_sha256,
        "mineru_producer_version": result.producer_version,
        "middle_schema": result.schema_id,
        "middle_schema_version": result.schema_version,
        "tier": result.tier,
        "parse_mode": result.parse_mode,
        "raw_middle_json_source": str(result.raw_middle_json),
        "raw_middle_json_sha256": _sha256(result.raw_middle_json),
        "stdout_log": _file_record(result.stdout_log),
        "stderr_log": _file_record(result.stderr_log),
        "raw_artifacts": [_file_record(path) for path in result.raw_artifacts if path.is_file()],
        "page_mapping": [
            {"middle_page_idx": page.page_idx, "original_physical_page": page.page_number}
            for page in result.pages
        ],
        "local_only": True,
        "fallback": fallback,
    }
    if source_manifest is not None:
        provenance["task_1_2_manifest"] = json.loads(
            _read_bounded(source_manifest, source_manifest.parent)
        )
    manifest_name = "manifest.grouped.json" if grouped else "manifest.json"
    _write_json(case_root / manifest_name, provenance)
    return summary


def _write_formula_sidecars(
    sidecars: list[FormulaSidecar], case_root: Path, *, directory: str
) -> None:
    root = case_root / directory
    assets = root / "assets"
    root.mkdir(parents=True, exist_ok=True)
    for sidecar in sidecars:
        _write_json(root / f"{sidecar.formula_group_id}.json", sidecar.model_dump(mode="json"))
        for equation in sidecar.equations:
            if equation.source_asset_path is None:
                continue
            source = Path(equation.source_asset_path)
            assets.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, assets / f"{equation.formula_id}{source.suffix.lower()}")


def _render_overlay(
    pdf_path: Path,
    document: Document,
    result: MinerUParseResult,
    sidecars: list[FormulaSidecar],
    output: Path,
    *,
    grouped: bool,
    dedup_coverage: list[FormulaSemanticCoverage],
) -> None:
    import pymupdf
    from PIL import Image, ImageDraw

    output.mkdir(parents=True, exist_ok=True)
    source_elements = {
        (page.page_number, element.source_index): element
        for page in result.pages
        for element in page.elements
    }
    with pymupdf.open(pdf_path) as pdf:
        for page in document.pages:
            pixmap = pdf[page.page_number - 1].get_pixmap(matrix=pymupdf.Matrix(160 / 72, 160 / 72))
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            draw = ImageDraw.Draw(image)
            scale_x = pixmap.width / page.width
            scale_y = pixmap.height / page.height
            for block in page.blocks:
                if block.block_type == BlockType.BODY:
                    box = (
                        block.bbox.x_min * scale_x,
                        block.bbox.y_min * scale_y,
                        block.bbox.x_max * scale_x,
                        block.bbox.y_max * scale_y,
                    )
                    draw.rectangle(box, outline="#6c757d", width=2)
                    continue
                if block.block_type != BlockType.FORMULA:
                    continue
                box = (
                    block.bbox.x_min * scale_x,
                    block.bbox.y_min * scale_y,
                    block.bbox.x_max * scale_x,
                    block.bbox.y_max * scale_y,
                )
                draw.rectangle(box, outline="#00a86b", width=4)
                draw.text((box[0] + 2, box[1] + 2), block.formula_group_id[-8:], fill="#006b46")
            for sidecar in sidecars:
                if sidecar.page_number != page.page_number:
                    continue
                for condition in sidecar.conditions:
                    box = (
                        condition.bbox.x_min * pixmap.width,
                        condition.bbox.y_min * pixmap.height,
                        condition.bbox.x_max * pixmap.width,
                        condition.bbox.y_max * pixmap.height,
                    )
                    draw.rectangle(box, outline="#7b2cbf", width=4)
                    draw.text(
                        (box[0] + 2, box[1] + 2),
                        f"condition->{condition.target_formula_ids[0][-8:]}",
                        fill="#5a189a",
                    )
                for component in sidecar.semantic_components:
                    if component.semantic_role != "equation":
                        continue
                    box = (
                        component.component_bbox.x_min * pixmap.width,
                        component.component_bbox.y_min * pixmap.height,
                        component.component_bbox.x_max * pixmap.width,
                        component.component_bbox.y_max * pixmap.height,
                    )
                    draw.rectangle(box, outline="#0057d9", width=2)
                if sidecar.symbol_evidence is None:
                    continue
                for source_index in sidecar.symbol_evidence.source_indices:
                    source = source_elements.get((page.page_number, source_index))
                    if source is None or source.bbox is None:
                        continue
                    box = (
                        source.bbox.x_min * pixmap.width,
                        source.bbox.y_min * pixmap.height,
                        source.bbox.x_max * pixmap.width,
                        source.bbox.y_max * pixmap.height,
                    )
                    coverage = next(
                        (
                            item
                            for item in dedup_coverage
                            if getattr(item, "source_page_number", None) == page.page_number
                            and getattr(item, "source_index", None) == source_index
                        ),
                        None,
                    )
                    consumed = getattr(coverage, "duplicate_disposition", None) == "consumed"
                    incomplete = getattr(coverage, "cross_page_incomplete", False)
                    draw.rectangle(
                        box,
                        outline="#d00000" if incomplete else "#ff8c00" if consumed else "#8b0000",
                        width=3,
                    )
                for equation in sidecar.equations:
                    for evidence in equation.number_evidence:
                        if evidence.bbox is None:
                            continue
                        box = (
                            evidence.bbox.x_min * pixmap.width,
                            evidence.bbox.y_min * pixmap.height,
                            evidence.bbox.x_max * pixmap.width,
                            evidence.bbox.y_max * pixmap.height,
                        )
                        draw.rectangle(box, outline="#0057d9", width=3)
            draw.rectangle((10, 10, 520, 88), fill="#ffffff", outline="#222222", width=2)
            draw.text(
                (20, 18), "GREEN semantic group | BLUE equation | PURPLE condition", fill="#111111"
            )
            draw.text((20, 42), "ORANGE explanation | RED cross-page incomplete", fill="#111111")
            draw.text((20, 66), "GRAY/untouched document body remains in Document", fill="#111111")
            suffix = "-grouped" if grouped else ""
            image.save(output / f"page-{page.page_number:04d}-formulas{suffix}.png")


def _validate_result(result: MinerUParseResult, page_number: int, expected_sha256: str) -> None:
    if (
        result.schema_id != "docvortex.middle"
        or result.schema_version != "2.0"
        or not result.producer_version.startswith("4.")
    ):
        raise SystemExit("unsupported MinerU protocol identity")
    if result.source_sha256 != expected_sha256:
        raise SystemExit("normalized source hash does not match original PDF")
    if [page.page_number for page in result.pages] != [page_number]:
        raise SystemExit("normalized result does not map to the requested physical page")


def _safe_child(root: Path, relative: Path) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise SystemExit("input path escapes its declared root")
    return candidate


def _read_bounded(path: Path, root: Path) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise SystemExit("input path escapes its declared root")
    if path.is_symlink():
        raise SystemExit(f"input symlink is not allowed: {path}")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise SystemExit(f"input exceeds {MAX_INPUT_BYTES} bytes: {path}")
    return path.read_text(encoding="utf-8")


def _verify_pdf(path: Path, expected_sha256: str) -> tuple[int, int]:
    import pymupdf

    if _sha256(path) != expected_sha256:
        raise SystemExit("PDF SHA256 does not match the declared source")
    with pymupdf.open(path) as document:
        return path.stat().st_size, document.page_count


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _file_record(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay exactly the bounded Task 1.4 formula cases; never parses a full PDF."
    )
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--page24-fallback-root", type=Path, required=True)
    parser.add_argument("--page24-derived-pdf", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--case-id", action="append", choices=tuple(CASE_INPUTS))
    selection.add_argument("--all-cases", action="store_true")
    parser.add_argument("--max-cases", type=int, default=3, choices=(1, 2, 3))
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
