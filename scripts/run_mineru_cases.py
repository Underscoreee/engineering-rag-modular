#!/usr/bin/env python3
"""Run the bounded Task 1.2 case matrix with a local MinerU 4.x runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import resource
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import pymupdf

from engineering_rag.contracts.common import FileRef
from engineering_rag.contracts.documents import StandardMetadata
from engineering_rag.modules.document_parser.internal.mineru.adapter import MinerUAdapter
from engineering_rag.modules.document_parser.internal.mineru.models import MinerUParseRequest
from engineering_rag.modules.document_parser.internal.mineru.v24_adapter import adapt_to_v24

MAX_CASES = 30
ALLOWED_MODES = {"single_page", "paired_contiguous", "individual_pages"}


def main() -> int:
    args = _arguments()
    configuration = json.loads(args.cases.read_text(encoding="utf-8"))
    cases = _selected_cases(configuration["cases"], args.case_id)
    if len(cases) > MAX_CASES:
        raise SystemExit(f"refusing to run more than {MAX_CASES} cases")
    source_sha256 = _sha256(args.pdf)
    source_size = args.pdf.stat().st_size
    with pymupdf.open(args.pdf) as pdf:
        page_count = pdf.page_count
    expected = configuration["document_reference"]["expected_page_count"]
    if page_count != expected:
        raise SystemExit(f"source has {page_count} pages; evaluation requires {expected}")
    adapter = MinerUAdapter(args.executable, args.mineru_home)
    producer_version = adapter.probe_version() if not args.dry_run else "dry-run"
    summary: list[dict[str, object]] = []
    for case in cases:
        for mode in case["modes"]:
            if mode not in ALLOWED_MODES:
                raise SystemExit(f"unsupported mode {mode!r}")
            result = _run_mode(
                adapter=adapter,
                case=case,
                mode=mode,
                args=args,
                source_sha256=source_sha256,
                source_size=source_size,
                page_count=page_count,
                producer_version=producer_version,
            )
            summary.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    output = {
        "evaluation_id": configuration["evaluation_id"],
        "generated_at": datetime.now(UTC).isoformat(),
        "source_sha256": source_sha256,
        "producer_version": producer_version,
        "tier": args.tier,
        "ocr_mode": "ocr",
        "results": summary,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "run-summary.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 1 if any(item["status"] == "failed" for item in summary) else 0


def _run_mode(
    *,
    adapter: MinerUAdapter,
    case: dict[str, Any],
    mode: str,
    args: argparse.Namespace,
    source_sha256: str,
    source_size: int,
    page_count: int,
    producer_version: str,
) -> dict[str, object]:
    case_id = str(case["case_id"])
    root = args.output / case_id / mode
    pages = [int(page) for page in case["physical_pages"]]
    groups = [[page] for page in pages] if mode == "individual_pages" else [pages]
    if args.dry_run:
        return {"case_id": case_id, "mode": mode, "status": "not_run", "pages": pages}
    group_results: list[dict[str, object]] = []
    for group in groups:
        run_dir = root if len(groups) == 1 else root / f"page-{group[0]:04d}"
        existing = run_dir / "manifest.json"
        if existing.is_file() and not args.retry:
            group_results.append(
                _backfill_manifest(existing, run_dir=run_dir, pages=group, args=args)
            )
            continue
        group_results.append(
            _run_group(
                adapter=adapter,
                run_dir=run_dir,
                pages=group,
                args=args,
                case=case,
                source_sha256=source_sha256,
                source_size=source_size,
                page_count=page_count,
                producer_version=producer_version,
            )
        )
    status = (
        "succeeded" if all(item["status"] == "succeeded" for item in group_results) else "failed"
    )
    mode_manifest = {
        "case_id": case_id,
        "mode": mode,
        "status": status,
        "pages": pages,
        "ground_truth_status": case["ground_truth_status"],
        "accuracy_metrics_computed": False,
        "runs": group_results,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "mode-manifest.json").write_text(
        json.dumps(mode_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return mode_manifest


def _run_group(
    *,
    adapter: MinerUAdapter,
    run_dir: Path,
    pages: list[int],
    args: argparse.Namespace,
    case: dict[str, Any],
    source_sha256: str,
    source_size: int,
    page_count: int,
    producer_version: str,
) -> dict[str, object]:
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_input_pages(args.pdf, pages, run_dir / "input_pages.json")
    started = datetime.now(UTC)
    wall_started = perf_counter()
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    manifest: dict[str, object] = {
        "case_id": case["case_id"],
        "kind": case["kind"],
        "pages": pages,
        "status": "failed",
        "started_at": started.isoformat(),
        "engine": "mineru",
        "producer_version": producer_version,
        "tier": args.tier,
        "ocr_mode": "ocr",
        "local_only": True,
        "source_sha256": source_sha256,
        "ground_truth_status": case["ground_truth_status"],
        "accuracy_metrics_computed": False,
        "command": _parse_command(args, pages, run_dir),
    }
    try:
        result = adapter.parse(
            MinerUParseRequest(
                source_pdf=args.pdf,
                source_sha256=source_sha256,
                original_pages=pages,
                output_dir=run_dir,
                timeout_seconds=args.timeout,
                tier=args.tier,
                ocr_mode="ocr",
            ),
            bundle=True,
        )
        normalized = run_dir / "normalized.json"
        normalized.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        adaptation = adapt_to_v24(
            result,
            source_file=FileRef(
                file_id=f"sha256-{source_sha256}",
                uri=args.pdf.name,
                mime_type="application/pdf",
                sha256=source_sha256,
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
        document_path = run_dir / "document.v2.4.partial.json"
        document_path.write_text(adaptation.document.model_dump_json(indent=2), encoding="utf-8")
        diagnostics = {
            "normalizer": result.diagnostics,
            "omitted_elements": adaptation.omitted_elements,
            "review_status": "candidate_pending_human_review",
        }
        (run_dir / "diagnostics.json").write_text(
            json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        manifest.update(
            status="succeeded",
            elapsed_seconds=result.elapsed_seconds,
            normalized_json=str(normalized),
            document_json=str(document_path),
            raw_artifacts=[str(path) for path in result.raw_artifacts],
        )
    except Exception as exc:  # noqa: BLE001 - runner must preserve per-case failures
        manifest["error_type"] = type(exc).__name__
        manifest["error"] = str(exc)
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    manifest["wall_seconds"] = perf_counter() - wall_started
    manifest["child_user_cpu_seconds"] = usage_after.ru_utime - usage_before.ru_utime
    manifest["child_system_cpu_seconds"] = usage_after.ru_stime - usage_before.ru_stime
    manifest["child_max_rss_observed_kib"] = usage_after.ru_maxrss
    manifest["resource_note"] = "ru_maxrss is the process-wide maximum across completed child runs"
    manifest["output_size_bytes"] = sum(
        item.stat().st_size for item in run_dir.rglob("*") if item.is_file()
    )
    manifest["finished_at"] = datetime.now(UTC).isoformat()
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def _backfill_manifest(
    path: Path, *, run_dir: Path, pages: list[int], args: argparse.Namespace
) -> dict[str, object]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    _write_input_pages(args.pdf, pages, run_dir / "input_pages.json")
    manifest["command"] = _parse_command(args, pages, run_dir)
    manifest["output_size_bytes"] = sum(
        item.stat().st_size for item in run_dir.rglob("*") if item.is_file()
    )
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _write_input_pages(pdf_path: Path, pages: list[int], output: Path) -> None:
    records: list[dict[str, object]] = []
    with pymupdf.open(pdf_path) as document:
        for number in pages:
            page = document[number - 1]
            records.append(
                {
                    "original_page_number": number,
                    "page_idx": number - 1,
                    "width_points": float(page.rect.width),
                    "height_points": float(page.rect.height),
                    "rotation": int(page.rotation),
                    "cropbox": [float(value) for value in page.cropbox],
                }
            )
    output.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_command(args: argparse.Namespace, pages: list[int], run_dir: Path) -> list[str]:
    return [
        str(args.executable),
        "parse",
        str(args.pdf),
        "-o",
        str(run_dir / "raw" / "mineru-output.zip"),
        "--pages",
        ",".join(str(page) for page in pages),
        "--format",
        "zip",
        "--tier",
        args.tier,
        "--ocr-mode",
        "ocr",
    ]


def _selected_cases(cases: list[dict[str, Any]], requested: list[str]) -> list[dict[str, Any]]:
    if not requested:
        return cases
    selected = [case for case in cases if case["case_id"] in requested]
    missing = sorted(set(requested) - {case["case_id"] for case in selected})
    if missing:
        raise SystemExit(f"unknown case ids: {', '.join(missing)}")
    return selected


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--mineru-home", type=Path, required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--case-id", action="append", default=[])
    selection.add_argument("--all-cases", action="store_true")
    parser.add_argument("--tier", choices=("basic", "standard", "advanced"), default="basic")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--retry", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    sys.exit(main())
