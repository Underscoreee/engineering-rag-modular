#!/usr/bin/env python3
"""Replay saved MinerU output into Task 1.3 table artifacts without model inference."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import time
from pathlib import Path

from engineering_rag.contracts.common import FileRef
from engineering_rag.contracts.documents import BlockType, Document, StandardMetadata
from engineering_rag.modules.document_parser.internal.mineru.models import MinerUParseResult
from engineering_rag.modules.document_parser.internal.mineru.v24_adapter import adapt_to_v24
from engineering_rag.modules.document_parser.internal.tables.assembler import (
    TABLE_ASSEMBLER_VERSION,
)

CASE_PATHS = {
    "GB-T352": "P028029",
    "GB-T4222": "P037038",
    "GB-T912": "P126127",
}
MAX_INPUT_BYTES = 64 * 1024 * 1024


def main() -> int:
    args = _arguments()
    input_root = args.input_root.resolve()
    case_ids = list(CASE_PATHS) if args.all_cases else args.case_id
    modes = ["paired_contiguous", "individual_pages"] if args.mode == "both" else [args.mode]
    source_size, page_count = _verify_pdf(args.pdf, args.expected_sha256)
    summaries: list[dict[str, object]] = []
    for case_id in case_ids:
        mode_summaries: list[dict[str, object]] = []
        for mode in modes:
            result, inputs = _load_result(input_root, CASE_PATHS[case_id], mode)
            if result.source_sha256 != args.expected_sha256:
                raise SystemExit(f"{case_id}/{mode}: normalized source hash does not match")
            mode_root = args.output / case_id / mode
            summary = _write_artifacts(
                result,
                inputs=inputs,
                output=mode_root,
                source_size=source_size,
                page_count=page_count,
                pdf=args.pdf,
            )
            mode_summaries.append(summary)
        comparison = {
            "case_id": case_id,
            "ground_truth_status": "candidate_pending_human_review",
            "accuracy_metrics_computed": False,
            "modes": mode_summaries,
            "differences": _compare_modes(mode_summaries),
        }
        case_root = args.output / case_id
        _write_json(case_root / "comparison.json", comparison)
        summaries.append(comparison)
    _write_json(
        args.output / "run-summary.json",
        {
            "algorithm_version": TABLE_ASSEMBLER_VERSION,
            "source_sha256": args.expected_sha256,
            "local_replay_only": True,
            "cases": summaries,
        },
    )
    print(json.dumps({"cases": len(summaries), "output": str(args.output)}, ensure_ascii=False))
    return 0


def _load_result(
    input_root: Path, task12_case: str, mode: str
) -> tuple[MinerUParseResult, list[Path]]:
    base = _safe_child(input_root, Path(task12_case) / mode)
    paths = (
        sorted(base.glob("page-*/normalized.json"))
        if mode == "individual_pages"
        else [base / "normalized.json"]
    )
    if not paths or any(not path.is_file() for path in paths):
        raise SystemExit(f"missing Task 1.2 normalized input under {base}")
    results = [
        MinerUParseResult.model_validate_json(_read_bounded(path, input_root)) for path in paths
    ]
    first = results[0]
    for result in results[1:]:
        identity = (
            result.schema_id,
            result.schema_version,
            result.producer_version,
            result.source_sha256,
        )
        expected = (
            first.schema_id,
            first.schema_version,
            first.producer_version,
            first.source_sha256,
        )
        if identity != expected:
            raise SystemExit("individual MinerU outputs have incompatible protocol/source identity")
    pages = [page for result in results for page in result.pages]
    if len({page.page_number for page in pages}) != len(pages):
        raise SystemExit("combined individual output contains duplicate source pages")
    combined = MinerUParseResult(
        schema_id=first.schema_id,
        schema_version=first.schema_version,
        producer_version=first.producer_version,
        tier=first.tier,
        parse_mode=first.parse_mode,
        source_sha256=first.source_sha256,
        pages=sorted(pages, key=lambda page: page.page_number),
        raw_middle_json=first.raw_middle_json,
        stdout_log=first.stdout_log,
        stderr_log=first.stderr_log,
        elapsed_seconds=sum(result.elapsed_seconds for result in results),
        raw_artifacts=[path for result in results for path in result.raw_artifacts],
        diagnostics=[item for result in results for item in result.diagnostics],
    )
    return combined, paths


def _write_artifacts(
    result: MinerUParseResult,
    *,
    inputs: list[Path],
    output: Path,
    source_size: int,
    page_count: int,
    pdf: Path,
) -> dict[str, object]:
    postprocess_started = time.perf_counter()
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
    document = adaptation.document.model_validate_json(adaptation.document.model_dump_json())
    output.mkdir(parents=True, exist_ok=True)
    sidecar_root = output / "table_sidecars"
    sidecar_root.mkdir(parents=True, exist_ok=True)
    for sidecar in adaptation.table_sidecars:
        for index, fragment in enumerate(sidecar.fragments):
            path = sidecar_root / f"{sidecar.table_id}-fragment-{index}.html"
            path.write_text(fragment.raw_html, encoding="utf-8")
    _write_json(
        output / "provenance.json",
        {
            "algorithm_version": TABLE_ASSEMBLER_VERSION,
            "mineru_producer_version": result.producer_version,
            "middle_schema": result.schema_id,
            "middle_schema_version": result.schema_version,
            "tier": result.tier,
            "parse_mode": result.parse_mode,
            "source_sha256": result.source_sha256,
            "original_pages": [page.page_number for page in result.pages],
            "normalized_inputs": [
                {"path": str(path), "sha256": _sha256(path), "size_bytes": path.stat().st_size}
                for path in inputs
            ],
            "raw_middle_json_inputs": [
                {
                    "path": str(path),
                    "sha256": _sha256(path),
                    "size_bytes": path.stat().st_size,
                }
                for path in _raw_middle_paths(inputs)
                if path.is_file()
            ],
            "task_1_2_manifests": [
                json.loads(_read_bounded(path.parent / "manifest.json", path.parent))
                for path in inputs
            ],
            "local_replay_only": True,
        },
    )
    _write_json(
        output / "fragments.json",
        [sidecar.model_dump(mode="json") for sidecar in adaptation.table_sidecars],
    )
    _write_json(
        output / "tables.json",
        [table.model_dump(mode="json") for table in document.tables],
    )
    (output / "document.partial.json").write_text(
        document.model_dump_json(indent=2), encoding="utf-8"
    )
    _write_json(
        output / "diagnostics.json",
        {
            "omitted_elements": adaptation.omitted_elements,
            "table_diagnostics": adaptation.table_diagnostics,
            "sidecars": [
                {"table_id": item.table_id, "diagnostics": item.diagnostics}
                for item in adaptation.table_sidecars
            ],
            "ground_truth_status": "candidate_pending_human_review",
            "accuracy_metrics_computed": False,
        },
    )
    _render_overlays(pdf, document, output / "overlay")
    for table in document.tables:
        _render_grid_svg(
            table.model_dump(mode="json"), output / "overlay" / f"{table.table_id}.svg"
        )
    postprocess_elapsed_seconds = time.perf_counter() - postprocess_started
    summary = {
        "status": "succeeded",
        "mode": output.name,
        "pages": [page.page_number for page in result.pages],
        "table_count": len(document.tables),
        "fragment_count": sum(len(table.fragments) for table in document.tables),
        "data_row_count": sum(len(table.data or []) for table in document.tables),
        "table_shapes": [
            {
                "table_number": table.table_number,
                "fragments": len(table.fragments),
                "raw_rows": table.raw_grid.row_count if table.raw_grid else None,
                "raw_columns": table.raw_grid.column_count if table.raw_grid else None,
                "data_rows": len(table.data or []),
                "notes": len(table.notes or []),
            }
            for table in document.tables
        ],
        "tables_digest": hashlib.sha256(
            json.dumps(
                [table.model_dump(mode="json") for table in document.tables],
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest(),
        "elapsed_seconds_from_task_1_2": result.elapsed_seconds,
        "task_1_3_postprocess_elapsed_seconds": postprocess_elapsed_seconds,
    }
    _write_json(
        output / "manifest.json",
        {
            **summary,
            "algorithm_version": TABLE_ASSEMBLER_VERSION,
            "source_sha256": result.source_sha256,
            "document_json": str(output / "document.partial.json"),
            "raw_inputs_unchanged": True,
        },
    )
    return summary


def _render_overlays(pdf_path: Path, document: Document, output: Path) -> None:
    import pymupdf
    from PIL import Image, ImageDraw

    output.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(pdf_path) as pdf:
        for page in document.pages:
            pixmap = pdf[page.page_number - 1].get_pixmap(matrix=pymupdf.Matrix(160 / 72, 160 / 72))
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            draw = ImageDraw.Draw(image)
            scale_x = pixmap.width / page.width
            scale_y = pixmap.height / page.height
            for block in page.blocks:
                if block.block_type != BlockType.TABLE:
                    continue
                box = (
                    block.bbox.x_min * scale_x,
                    block.bbox.y_min * scale_y,
                    block.bbox.x_max * scale_x,
                    block.bbox.y_max * scale_y,
                )
                draw.rectangle(box, outline="#00a86b", width=4)
                draw.text((box[0] + 2, box[1] + 2), block.table_id[-8:], fill="#006b46")
            image.save(output / f"page-{page.page_number:04d}-table-overlay.png")


def _render_grid_svg(table: dict[str, object], output: Path) -> None:
    grid = table.get("raw_grid")
    if not isinstance(grid, dict):
        return
    rows = int(grid["row_count"])
    columns = int(grid["column_count"])
    width = max(600, columns * 150)
    height = max(120, rows * 42)
    column_width = width / columns
    row_height = height / rows
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    for cell in grid["cells"]:
        x = float(cell["col"]) * column_width
        y = float(cell["row"]) * row_height
        cell_width = float(cell["col_span"]) * column_width
        cell_height = float(cell["row_span"]) * row_height
        fill = "#e5f5ff" if cell["is_header"] else "white"
        label = html.escape(str(cell.get("text") or "")[:32])
        parts.append(
            f'<rect x="{x}" y="{y}" width="{cell_width}" height="{cell_height}" '
            f'fill="{fill}" stroke="#333"/>'
        )
        parts.append(f'<text x="{x + 4}" y="{y + 17}" font-size="12">{label}</text>')
    parts.append("</svg>")
    output.write_text("\n".join(parts), encoding="utf-8")


def _compare_modes(modes: list[dict[str, object]]) -> list[str]:
    if len(modes) != 2:
        return []
    left, right = modes
    differences: list[str] = []
    for key in (
        "table_count",
        "fragment_count",
        "data_row_count",
        "table_shapes",
        "tables_digest",
    ):
        if left[key] != right[key]:
            differences.append(f"{key} differs between paired and individual replay")
    return differences


def _raw_middle_paths(inputs: list[Path]) -> list[Path]:
    return [path.parent / "raw" / "bundle" / "middle_json.json" for path in inputs]


def _safe_child(root: Path, relative: Path) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise SystemExit("input path escapes --input-root")
    return candidate


def _read_bounded(path: Path, root: Path) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise SystemExit("input path escapes --input-root")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise SystemExit(f"input exceeds {MAX_INPUT_BYTES} bytes: {path}")
    return path.read_text(encoding="utf-8")


def _verify_pdf(path: Path, expected_sha256: str) -> tuple[int, int]:
    import pymupdf

    if _sha256(path) != expected_sha256:
        raise SystemExit("PDF SHA256 does not match the declared Task 1.2 source")
    with pymupdf.open(path) as document:
        return path.stat().st_size, document.page_count


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay bounded Task 1.2 MinerU table cases; never parses the full PDF."
    )
    parser.add_argument("--input-root", type=Path, required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--case-id", action="append", choices=tuple(CASE_PATHS))
    selection.add_argument("--all-cases", action="store_true")
    parser.add_argument(
        "--mode",
        choices=("paired_contiguous", "individual_pages", "both"),
        default="both",
    )
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
