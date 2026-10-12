#!/usr/bin/env python3
"""Run the Task 1.6 MinerU pipeline in explicitly separated live/replay modes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO
from uuid import NAMESPACE_URL, uuid5

from engineering_rag.contracts.common import FileRef
from engineering_rag.contracts.documents import (
    Document,
    ParseConfig,
    ParseRequest,
    StandardMetadata,
)
from engineering_rag.modules.document_parser.api import create_document_parser
from engineering_rag.modules.document_parser.internal.e2e import (
    BatchState,
    CheckpointStore,
    RunMode,
    RunState,
    SourceIdentity,
    build_candidate_records,
    ensure_full_document_authorized,
    evaluate_verified_records,
    merge_documents,
    plan_batches,
)
from engineering_rag.modules.document_parser.internal.e2e.models import RunStatus
from engineering_rag.modules.document_parser.internal.mineru.models import MinerUParseResult
from engineering_rag.modules.document_parser.internal.mineru.v24_adapter import adapt_to_v24
from engineering_rag.modules.document_parser.internal.semantic import assemble_semantics

SOURCE_SHA256 = "43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682"
DEFAULT_PAGES = "1,2,3,9,12,16,24,28-29,37-38,50,126-127,275-279,282,301"
MAX_JSON_BYTES = 128 * 1024 * 1024
REPLAY_CATALOG = {
    (1,): "data/eval/task1_2_mineru/runs/final/P001/single_page/normalized.json",
    (2,): "data/eval/task1_2_mineru/runs/final/P002/single_page/normalized.json",
    (3,): "data/eval/task1_2_mineru/runs/final/P003/single_page/normalized.json",
    (9,): "data/eval/task1_2_mineru/runs/final/P009/single_page/normalized.json",
    (12,): "data/eval/task1_2_mineru/runs/final/P012/single_page/normalized.json",
    (16,): "data/eval/task1_2_mineru/runs/final/P016/single_page/normalized.json",
    (24,): "data/eval/task1_4_formulas/preflight/P024-fallback-run/normalized.json",
    (28, 29): "data/eval/task1_2_mineru/runs/final/P028029/paired_contiguous/normalized.json",
    (37, 38): "data/eval/task1_2_mineru/runs/final/P037038/paired_contiguous/normalized.json",
    (49, 50): "data/eval/task1_5_semantics/upstream/P049050/paired_contiguous/normalized.json",
    (50,): "data/eval/task1_2_mineru/runs/final/P050/single_page/normalized.json",
    (126, 127): "data/eval/task1_2_mineru/runs/final/P126127/paired_contiguous/normalized.json",
    (275,): "data/eval/task1_2_mineru/runs/final/P275/single_page/normalized.json",
    (276,): "data/eval/task1_2_mineru/runs/final/P276/single_page/normalized.json",
    (277,): "data/eval/task1_2_mineru/runs/final/P277/single_page/normalized.json",
    (278,): "data/eval/task1_2_mineru/runs/final/P278/single_page/normalized.json",
    (279,): "data/eval/task1_2_mineru/runs/final/P279/single_page/normalized.json",
    (282,): "data/eval/task1_2_mineru/runs/final/P282/single_page/normalized.json",
    (301,): "data/eval/task1_2_mineru/runs/final/P301/single_page/normalized.json",
}


class LocalReadOnlyFileStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def read(self, reference: FileRef) -> Iterator[BinaryIO]:
        del reference
        with self.path.open("rb") as stream:
            yield stream


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    started = time.perf_counter()
    pdf = args.pdf.resolve()
    sha256, size_bytes = _digest(pdf)
    if args.expected_sha256 and sha256 != args.expected_sha256:
        raise SystemExit("source PDF SHA-256 does not match the required identity")
    page_count = _page_count(pdf)
    pages = _parse_pages(args.pages, page_count)
    try:
        ensure_full_document_authorized(
            selected_page_count=len(pages),
            page_count=page_count,
            explicitly_approved=args.confirm_full_document,
        )
    except PermissionError as exc:
        raise SystemExit(f"{exc}; --confirm-full-document is also required") from exc
    plans = plan_batches(pages, max_batch_size=args.batch_size)
    run_dir = args.output.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    standard = StandardMetadata(
        standard_name=args.standard_name,
        standard_code=args.standard_code,
        edition=args.edition,
        revision=args.revision,
        language="zh-CN",
    )
    file_ref = FileRef(
        file_id=f"sha256-{sha256}",
        uri=pdf.name,
        mime_type="application/pdf",
        sha256=sha256,
        size_bytes=size_bytes,
    )
    identity = "|".join(
        (
            file_ref.file_id,
            standard.standard_code,
            standard.edition or "",
            standard.revision or "",
        )
    )
    document_id = f"doc-{uuid5(NAMESPACE_URL, identity).hex}"
    config_payload = {
        "mode": args.mode,
        "pages": pages,
        "batch_size": args.batch_size,
        "continue_on_batch_error": args.continue_on_batch_error,
        "tier": args.tier,
        "standard": standard.model_dump(mode="json"),
        "explanation_cover_page": args.explanation_cover_page,
    }
    config_sha = _json_sha(config_payload)
    replay_paths = (
        [] if args.mode == RunMode.LIVE_MINERU else (args.normalized or _catalog_paths(pages))
    )
    model_signature = (
        _model_signature(args.mineru_home)
        if args.mode == RunMode.LIVE_MINERU
        else _replay_signature(replay_paths)
    )
    source = SourceIdentity(
        document_id=document_id,
        file_id=file_ref.file_id,
        sha256=sha256,
        size_bytes=size_bytes,
        page_count=page_count,
        standard_code=standard.standard_code,
        edition=standard.edition,
        revision=standard.revision,
    )
    checkpoint = CheckpointStore(run_dir)
    resumed_batch_ids: list[str] = []
    if replay_paths:
        _atomic_json(
            run_dir / "replay_inputs_manifest.json",
            {
                "mode": args.mode,
                "claim": "saved real MinerU output replay; no inference performed",
                "inputs": [_replay_file_record(path) for path in replay_paths],
            },
        )
    if args.resume:
        state = checkpoint.load(
            expected_source_sha256=sha256,
            expected_config_sha256=config_sha,
            expected_model_signature=model_signature,
        )
        resumed_batch_ids = [
            batch.batch_id for batch in state.batches if batch.status == RunStatus.SUCCEEDED
        ]
    else:
        now = datetime.now(UTC)
        state = RunState(
            run_id=args.run_id,
            mode=args.mode,
            status=RunStatus.PLANNED,
            created_at=now,
            updated_at=now,
            source=source,
            config_sha256=config_sha,
            model_signature=model_signature,
            batches=[BatchState(batch_id=plan.batch_id, pages=plan.pages) for plan in plans],
        )
        checkpoint.save(state)
    batch_documents: list[Document] = []
    all_results: list[MinerUParseResult] = []
    sidecars: dict[str, list[object]] = {
        "omitted_elements": [],
        "table_sidecars": [],
        "table_diagnostics": [],
        "formula_sidecars": [],
        "formula_dedup_coverage": [],
        "formula_diagnostics": [],
    }
    state.status = RunStatus.RUNNING
    state.updated_at = datetime.now(UTC)
    checkpoint.save(state)
    try:
        for plan, batch_state in zip(plans, state.batches, strict=True):
            batch_dir = run_dir / "batches" / plan.batch_id
            batch_dir.mkdir(parents=True, exist_ok=True)
            document_path = batch_dir / "document.partial.json"
            if batch_state.status == RunStatus.SUCCEEDED and args.resume:
                batch_documents.append(
                    Document.model_validate_json(document_path.read_text(encoding="utf-8"))
                )
                all_results.extend(_load_saved_batch_results(batch_dir))
                _merge_saved_sidecars(sidecars, batch_dir / "private_sidecars.json")
                continue
            batch_state.status = RunStatus.RUNNING
            batch_state.attempts += 1
            batch_state.started_at = datetime.now(UTC)
            batch_state.error = None
            checkpoint.save(state)
            batch_started = time.perf_counter()
            try:
                results = (
                    [_run_live_batch(args, pdf, file_ref, standard, plan.pages, batch_dir)]
                    if args.mode == RunMode.LIVE_MINERU
                    else _load_replay_batch(plan.pages, args.normalized)
                )
                adaptations = [
                    adapt_to_v24(
                        result,
                        source_file=file_ref,
                        standard=standard,
                        page_count=page_count,
                    )
                    for result in results
                ]
                document = merge_documents([item.document for item in adaptations])
                _atomic_json(document_path, document.model_dump(mode="json"))
                for index, result in enumerate(results, start=1):
                    _atomic_json(
                        batch_dir / f"normalized-{index:02d}.json",
                        result.model_dump(mode="json"),
                    )
                batch_sidecars = _adaptation_sidecars(adaptations)
                _atomic_json(batch_dir / "private_sidecars.json", batch_sidecars)
                _extend_sidecars(sidecars, batch_sidecars)
                batch_documents.append(document)
                all_results.extend(results)
                batch_state.status = RunStatus.SUCCEEDED
                batch_state.document_path = str(document_path.relative_to(run_dir))
                batch_state.document_sha256 = _digest(document_path)[0]
                batch_state.artifact_sha256 = _batch_artifact_hashes(batch_dir, run_dir)
            except Exception as exc:
                batch_state.status = RunStatus.FAILED
                batch_state.error = f"{type(exc).__name__}: {exc}"
                if not args.continue_on_batch_error:
                    raise
            finally:
                batch_state.finished_at = datetime.now(UTC)
                batch_state.elapsed_seconds = time.perf_counter() - batch_started
                batch_state.peak_rss_bytes = _peak_rss_bytes()
                checkpoint.save(state)
            if batch_state.status == RunStatus.FAILED:
                continue
        if not batch_documents:
            raise RuntimeError("all parser batches failed; no final Document can be committed")
        merged = merge_documents(batch_documents)
        incomplete_group_ids = {
            str(item["target_formula_group_id"])
            for item in sidecars["formula_dedup_coverage"]
            if item.get("cross_page_incomplete") is True
        }
        incomplete_ids = {
            str(item["block_id"])
            for item in sidecars["formula_sidecars"]
            if item.get("formula_group_id") in incomplete_group_ids
        }
        semantic = assemble_semantics(
            merged,
            source_indexes=_source_indexes(all_results),
            incomplete_block_ids=incomplete_ids,
            known_explanation_cover_page=args.explanation_cover_page,
        )
        final_document = Document.model_validate_json(semantic.document.model_dump_json())
        final_dir = run_dir / "final"
        final_dir.mkdir(exist_ok=True)
        _atomic_json(
            final_dir / "document.v2.4.partial.json", final_document.model_dump(mode="json")
        )
        _atomic_json(final_dir / "parser_private_sidecars.json", sidecars)
        _atomic_json(
            final_dir / "semantic_source_lineage.json", semantic.lineage.model_dump(mode="json")
        )
        _atomic_json(
            final_dir / "semantic_pending_links.json",
            semantic.pending_links.model_dump(mode="json"),
        )
        _render_overlays(pdf, final_document, final_dir / "overlays")
        matrix = json.loads(args.test_matrix.read_text(encoding="utf-8"))
        candidates = build_candidate_records(matrix, final_document)
        qa_dir = run_dir / "qa"
        qa_dir.mkdir(exist_ok=True)
        _write_jsonl(qa_dir / "gold_candidates.jsonl", candidates)
        verified = _read_jsonl(args.verified_gold) if args.verified_gold else []
        _write_jsonl(qa_dir / "gold_verified.jsonl", verified)
        metrics = evaluate_verified_records(verified)
        metrics["coverage"] = _coverage(final_document, semantic.statistics, pages)
        _atomic_json(qa_dir / "metrics.json", metrics)
        _atomic_json(qa_dir / "semantic_integrity.json", _semantic_integrity(final_document))
        _atomic_json(qa_dir / "error_catalog.json", _error_catalog(final_document, semantic, state))
        elapsed = time.perf_counter() - started
        batch_seconds = [
            batch.elapsed_seconds for batch in state.batches if batch.elapsed_seconds is not None
        ]
        succeeded_pages = sum(
            len(batch.pages) for batch in state.batches if batch.status == RunStatus.SUCCEEDED
        )
        resource_name = "resume_resource_profile.json" if args.resume else "resource_profile.json"
        _atomic_json(
            qa_dir / resource_name,
            {
                "mode": args.mode,
                "wall_seconds": elapsed,
                "selected_page_count": len(pages),
                "wall_seconds_per_page": elapsed / len(pages),
                "peak_rss_bytes_process_tree_boundary": _peak_rss_bytes(),
                "measurement_note": "ru_maxrss covers this process and completed child processes",
                "batch_seconds": batch_seconds,
                "batch_seconds_p50": _percentile(batch_seconds, 0.50),
                "batch_seconds_p95": _percentile(batch_seconds, 0.95),
                "succeeded_page_count": succeeded_pages,
                "failed_page_count": len(pages) - succeeded_pages,
                "page_success_rate": succeeded_pages / len(pages),
                "artifact_bytes_at_measurement": _directory_bytes(run_dir),
                "full_441_page_run": "NOT_RUN_REQUIRES_EXPLICIT_APPROVAL",
                "estimated_minimum_batches_for_441_at_current_limit": 23,
            },
        )
        _atomic_json(
            final_dir / "artifact_manifest.json",
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "files": _artifact_records(run_dir),
            },
        )
        state.status = (
            RunStatus.FAILED
            if any(batch.status == RunStatus.FAILED for batch in state.batches)
            else RunStatus.SUCCEEDED
        )
        state.updated_at = datetime.now(UTC)
        checkpoint.save(state)
        if args.resume:
            _atomic_json(
                qa_dir / "resume_audit.json",
                {
                    "resumed_at": state.updated_at.isoformat(),
                    "reused_succeeded_batches": resumed_batch_ids,
                    "rerun_batches": [
                        batch.batch_id
                        for batch in state.batches
                        if batch.batch_id not in resumed_batch_ids
                    ],
                    "integrity_checks": [
                        "source_sha256",
                        "config_sha256",
                        "model_signature",
                        "batch_document_sha256",
                        "all_batch_artifact_sha256",
                    ],
                },
            )
    except Exception as exc:
        state.status = RunStatus.FAILED
        state.updated_at = datetime.now(UTC)
        running = next((item for item in state.batches if item.status == RunStatus.RUNNING), None)
        if running is not None:
            running.status = RunStatus.FAILED
            running.finished_at = datetime.now(UTC)
            running.error = f"{type(exc).__name__}: {exc}"
        checkpoint.save(state)
        raise
    print(json.dumps({"run_dir": str(run_dir), "status": state.status}, ensure_ascii=False))
    return 0 if state.status == RunStatus.SUCCEEDED else 1


def _run_live_batch(
    args: argparse.Namespace,
    pdf: Path,
    file_ref: FileRef,
    standard: StandardMetadata,
    pages: list[int],
    batch_dir: Path,
) -> MinerUParseResult:
    parser = create_document_parser(
        LocalReadOnlyFileStore(pdf),
        document_engine="mineru",
        mineru_executable=args.mineru_executable.resolve(),
        mineru_home=args.mineru_home.resolve(),
    )
    parser.parse(
        ParseRequest(
            source_file=file_ref,
            supplied_standard=standard,
            config=ParseConfig(
                config_id="task1.6-live-mineru",
                options={
                    "document_engine": "mineru",
                    "page_selection": ",".join(str(page) for page in pages),
                    "max_selected_pages": 20,
                    "engine_timeout_seconds": args.timeout,
                    "engine_output_dir": str(batch_dir / "engine"),
                    "mineru_tier": args.tier,
                    "mineru_bundle": True,
                    "semantic_structure": False,
                },
            ),
        )
    )
    if parser.last_mineru_result is None:
        raise RuntimeError("live parser completed without a MinerU result")
    return parser.last_mineru_result


def _load_replay_batch(pages: list[int], explicit: list[Path]) -> list[MinerUParseResult]:
    if explicit:
        loaded = [_load_result(path) for path in explicit]
        results = [
            result for result in loaded if {page.page_number for page in result.pages} <= set(pages)
        ]
    else:
        results = [_load_result(path) for path in _catalog_paths(pages)]
    actual = sorted(page.page_number for result in results for page in result.pages)
    if actual != pages:
        raise ValueError(f"replay page mapping mismatch: expected {pages}, got {actual}")
    return results


def _catalog_paths(pages: list[int]) -> list[Path]:
    remaining = set(pages)
    paths = []
    for group in sorted(REPLAY_CATALOG, key=lambda value: (-len(value), value)):
        if set(group) <= remaining:
            paths.append(Path(REPLAY_CATALOG[group]))
            remaining.difference_update(group)
    if remaining:
        raise ValueError(f"no saved real MinerU artifact for pages {sorted(remaining)}")
    return paths


def _load_result(path: Path) -> MinerUParseResult:
    path = path.resolve()
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError(f"unsafe, absent, or oversized replay input: {path}")
    result = MinerUParseResult.model_validate_json(path.read_text(encoding="utf-8"))
    if result.source_sha256 != SOURCE_SHA256:
        raise ValueError(f"replay source identity mismatch: {path}")
    return result


def _load_saved_batch_results(batch_dir: Path) -> list[MinerUParseResult]:
    return [_load_result(path) for path in sorted(batch_dir.glob("normalized-*.json"))]


def _adaptation_sidecars(adaptations: list[object]) -> dict[str, list[object]]:
    output: dict[str, list[object]] = {
        "omitted_elements": [],
        "table_sidecars": [],
        "table_diagnostics": [],
        "formula_sidecars": [],
        "formula_dedup_coverage": [],
        "formula_diagnostics": [],
    }
    for adaptation in adaptations:
        output["omitted_elements"].extend(adaptation.omitted_elements)
        output["table_sidecars"].extend(
            item.model_dump(mode="json") for item in adaptation.table_sidecars
        )
        output["table_diagnostics"].extend(adaptation.table_diagnostics)
        output["formula_sidecars"].extend(
            item.model_dump(mode="json") for item in adaptation.formula_sidecars
        )
        output["formula_dedup_coverage"].extend(
            item.model_dump(mode="json") for item in adaptation.formula_dedup_coverage
        )
        output["formula_diagnostics"].extend(adaptation.formula_diagnostics)
    return output


def _extend_sidecars(target: dict[str, list[object]], source: dict[str, list[object]]) -> None:
    for key in target:
        target[key].extend(source[key])


def _merge_saved_sidecars(target: dict[str, list[object]], path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    _extend_sidecars(target, payload)


def _source_indexes(results: list[MinerUParseResult]) -> dict[str, int]:
    indexes = {}
    for result in results:
        for page in result.pages:
            for element in page.elements:
                identity = "|".join(
                    (
                        result.source_sha256,
                        str(page.page_number),
                        str(element.source_index),
                        element.raw_type,
                    )
                )
                indexes[f"block-{uuid5(NAMESPACE_URL, identity).hex}"] = element.source_index
    return indexes


def _coverage(
    document: Document, statistics: dict[str, int], selected: list[int]
) -> dict[str, object]:
    return {
        "selected_pages": len(selected),
        "output_pages": len(document.pages),
        "output_page_numbers": [page.page_number for page in document.pages],
        "page_type_counts": _counts(page.page_type.value for page in document.pages),
        "content_status_counts": _counts(
            page.content_extraction_status.value for page in document.pages
        ),
        "sections": len(document.sections),
        "normative_clauses": len(document.clauses.normative),
        "explanation_clauses": len(document.clauses.explanations),
        "tables": len(document.tables),
        "formula_groups": sum(
            bool(block.formula_group_id) for page in document.pages for block in page.blocks
        ),
        "pending_relations": statistics.get("pending_relations", 0),
    }


def _error_catalog(document: Document, semantic: object, state: RunState) -> dict[str, object]:
    pending = semantic.pending_links.model_dump(mode="json")["relations"]
    failures = [
        {
            "category": "resource_timeout"
            if batch.error and "timed out" in batch.error.lower()
            else "engine_failure",
            "batch_id": batch.batch_id,
            "physical_pages": batch.pages,
            "diagnostic": batch.error,
            "review_status": "unverified",
        }
        for batch in state.batches
        if batch.status == RunStatus.FAILED
    ]
    return {
        "unknown_pages": [
            page.page_number for page in document.pages if page.page_type.value == "unknown"
        ],
        "pending_relations": pending,
        "batch_failures": failures,
        "category_counts": {
            "clause_page_zone": sum(
                relation["relation_type"] in {"clause_section", "section_parent"}
                for relation in pending
            ),
            "unresolved_pending": len(pending),
            "partial_extraction": sum(
                page.content_extraction_status.value != "complete" for page in document.pages
            ),
            "engine_failure": sum(item["category"] == "engine_failure" for item in failures),
            "resource_timeout": sum(item["category"] == "resource_timeout" for item in failures),
        },
        "processing_warnings": [
            item.model_dump(mode="json") for item in document.processing.warnings
        ],
        "policy": "machine findings are candidates; unresolved evidence remains partial/pending",
    }


def _semantic_integrity(document: Document) -> dict[str, object]:
    formula_blocks = [
        block
        for page in document.pages
        for block in page.blocks
        if block.ocr is not None and block.ocr.formula_group is not None
    ]
    equations = [
        equation
        for block in formula_blocks
        for equation in block.ocr.formula_group.equations  # type: ignore[union-attr]
    ]
    by_number = {equation.equation_number: equation for equation in equations}
    first = by_number.get("6.2.1-1")
    second = by_number.get("6.2.1-2")
    other_contexts = [
        equation.text
        for number, equation in by_number.items()
        if number in {"6.2.1-3", "6.2.1-4", "6.2.1-5"}
    ]
    groups_621 = [
        block.ocr.formula_group
        for block in formula_blocks
        if any(
            equation.equation_number and equation.equation_number.startswith("6.2.1-")
            for equation in block.ocr.formula_group.equations  # type: ignore[union-attr]
        )
    ]
    body_texts = [
        block.ocr.text
        for page in document.pages
        for block in page.blocks
        if block.block_type.value == "body" and block.ocr is not None and block.ocr.text
    ]
    symbol_descriptions = [
        item.description
        for group in groups_621
        if group.symbol_explanations
        for item in group.symbol_explanations.items
    ]
    table_ranges = {
        table.table_number: [table.page_start, table.page_end]
        for table in document.tables
        if table.table_number
    }
    clause_621 = next(
        (clause for clause in document.clauses.normative if clause.clause_number == "6.2.1"),
        None,
    )
    return {
        "document_v2_4_roundtrip": (
            Document.model_validate_json(document.model_dump_json()) == document
        ),
        "formula_ids_unique": len({item.formula_id for item in equations}) == len(equations),
        "formula_6_2_1": {
            "status": "evaluated" if first is not None and second is not None else "not_evaluated",
            "equation_count": sum(
                bool(item.equation_number and item.equation_number.startswith("6.2.1-"))
                for item in equations
            ),
            "condition_1_correct": bool(first and first.text and "ε_c ≤ ε_0" in first.text),
            "condition_2_correct": bool(
                second and second.text and "ε_0 < ε_c ≤ ε_cu" in second.text
            ),
            "condition_not_propagated": all(text is None for text in other_contexts),
            "condition_body_duplicate_count": sum(
                "ε_c ≤ ε_0" in text or "ε_0 < ε_c ≤ ε_cu" in text for text in body_texts
            ),
            "symbol_description_body_duplicate_count": sum(
                description in text for description in symbol_descriptions for text in body_texts
            ),
            "symbol_item_counts": [
                len(group.symbol_explanations.items) if group.symbol_explanations else 0
                for group in groups_621
            ],
            "clause_formula_reference_count": (
                sum(len(unit.formula_ids) for unit in clause_621.clause_content.content_units)
                if clause_621
                else None
            ),
        },
        "cross_page_table_ranges": table_ranges,
    }


def _render_overlays(pdf_path: Path, document: Document, output: Path) -> None:
    import pymupdf
    from PIL import Image, ImageDraw

    output.mkdir(parents=True, exist_ok=True)
    colors = {"table": "#d97706", "formula": "#dc2626", "title": "#059669", "body": "#2563eb"}
    with pymupdf.open(pdf_path) as pdf:
        for page in document.pages:
            pixmap = pdf[page.page_number - 1].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5))
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            draw = ImageDraw.Draw(image)
            sx, sy = pixmap.width / page.width, pixmap.height / page.height
            for block in page.blocks:
                box = (
                    block.bbox.x_min * sx,
                    block.bbox.y_min * sy,
                    block.bbox.x_max * sx,
                    block.bbox.y_max * sy,
                )
                draw.rectangle(box, outline=colors[block.block_type.value], width=3)
            draw.rectangle((8, 8, 530, 36), fill="white", outline="black")
            draw.text(
                (14, 14), f"Task 1.6 p{page.page_number} | {page.page_type.value}", fill="black"
            )
            image.save(output / f"page-{page.page_number:04d}.png")


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=[item.value for item in RunMode], required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--pages", default=DEFAULT_PAGES)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--continue-on-batch-error", action="store_true")
    parser.add_argument("--confirm-full-document", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--normalized", type=Path, action="append", default=[])
    parser.add_argument("--verified-gold", type=Path)
    parser.add_argument("--test-matrix", type=Path, default=Path("TASK_1_6_TEST_MATRIX.json"))
    parser.add_argument("--standard-name", default="混凝土结构设计规范")
    parser.add_argument("--standard-code", default="GB 50010-2010")
    parser.add_argument("--expected-sha256", default=SOURCE_SHA256)
    parser.add_argument("--edition", default="2015年版")
    parser.add_argument("--revision")
    parser.add_argument("--explanation-cover-page", type=int, default=277)
    parser.add_argument("--tier", choices=("basic", "standard", "advanced"), default="basic")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument(
        "--mineru-executable",
        type=Path,
        default=Path(".local/mineru-runtime/.venv/bin/mineru-kit"),
    )
    parser.add_argument("--mineru-home", type=Path, default=Path(".local/mineru-runtime/state"))
    args = parser.parse_args(argv)
    args.mode = RunMode(args.mode)
    if args.mode == RunMode.SYNTHETIC and not args.normalized:
        parser.error("synthetic mode requires explicit --normalized test fixtures")
    return args


def _parse_pages(value: str, page_count: int) -> list[int]:
    pages = set()
    for token in value.split(","):
        token = token.strip()
        if "-" in token:
            start, end = (int(item) for item in token.split("-", 1))
            pages.update(range(start, end + 1))
        else:
            pages.add(int(token))
    ordered = sorted(pages)
    if not ordered or ordered[0] < 1 or ordered[-1] > page_count:
        raise ValueError("page selection is outside the source PDF")
    return ordered


def _page_count(path: Path) -> int:
    import pymupdf

    with pymupdf.open(path) as document:
        return document.page_count


def _model_signature(root: Path) -> str:
    digest = hashlib.sha256()
    model_root = root.resolve() / "models"
    files = sorted(
        path for path in model_root.rglob("*") if path.is_file() and not path.is_symlink()
    )
    if not files:
        raise ValueError("MinerU model state is absent; live mode cannot start")
    for path in files:
        digest.update(str(path.relative_to(model_root)).encode())
        digest.update(_digest(path)[0].encode())
    return digest.hexdigest()


def _replay_signature(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(path.resolve() for path in paths):
        digest.update(_digest(path)[0].encode())
    return digest.hexdigest()


def _replay_file_record(path: Path) -> dict[str, object]:
    result = _load_result(path)
    sha256, size = _digest(path)
    return {
        "path": str(path),
        "sha256": sha256,
        "size_bytes": size,
        "physical_pages": [page.page_number for page in result.pages],
        "source_pdf_sha256": result.source_sha256,
        "producer_version": result.producer_version,
        "protocol": f"{result.schema_id}/{result.schema_version}",
        "provenance_note": (
            "derived raster fallback retained as replay-only evidence"
            if "P024-fallback" in str(path)
            else "saved local MinerU output"
        ),
    }


def _digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _json_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    text = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records)
    path.write_text(text, encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _counts(values: Iterator[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _peak_rss_bytes() -> int:
    self_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    child_rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    multiplier = 1024 if sys.platform != "darwin" else 1
    return (self_rss + child_rss) * multiplier


def _percentile(values: list[float], proportion: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * proportion
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _directory_bytes(root: Path) -> int:
    return sum(
        path.stat().st_size for path in root.rglob("*") if path.is_file() and not path.is_symlink()
    )


def _artifact_records(root: Path) -> list[dict[str, object]]:
    excluded = {root / "run_manifest.json", root / "final" / "artifact_manifest.json"}
    records = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path in excluded or path.is_symlink():
            continue
        sha256, size = _digest(path)
        records.append({"path": str(path.relative_to(root)), "sha256": sha256, "size_bytes": size})
    return records


def _batch_artifact_hashes(batch_dir: Path, run_dir: Path) -> dict[str, str]:
    return {
        str(path.relative_to(run_dir)): _digest(path)[0]
        for path in sorted(item for item in batch_dir.rglob("*") if item.is_file())
        if not path.is_symlink()
    }


if __name__ == "__main__":
    raise SystemExit(main())
