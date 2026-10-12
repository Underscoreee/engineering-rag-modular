#!/usr/bin/env python3
"""Replay bounded real MinerU artifacts into Task 1.5 semantic views."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from engineering_rag.contracts.common import FileRef
from engineering_rag.contracts.documents import (
    ClauseGroups,
    Document,
    LogicalTable,
    Page,
    ProcessingMetadata,
    StandardMetadata,
)
from engineering_rag.modules.document_parser.internal.mineru.models import MinerUParseResult
from engineering_rag.modules.document_parser.internal.mineru.v24_adapter import adapt_to_v24
from engineering_rag.modules.document_parser.internal.semantic import (
    SEMANTIC_ASSEMBLER_VERSION,
    assemble_semantics,
)

SOURCE_SHA256 = "43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682"
MAX_JSON_BYTES = 64 * 1024 * 1024
DEFAULT_INPUTS = (
    "data/eval/task1_2_mineru/runs/final/P016/single_page/normalized.json",
    "data/eval/task1_5_semantics/upstream/P049050/paired_contiguous/normalized.json",
    "data/eval/task1_2_mineru/runs/final/P126127/paired_contiguous/normalized.json",
    "data/eval/task1_2_mineru/runs/final/P277/single_page/normalized.json",
    "data/eval/task1_2_mineru/runs/final/P282/single_page/normalized.json",
    "data/eval/task1_2_mineru/runs/final/P301/single_page/normalized.json",
)


def main() -> int:
    args = _arguments()
    source_size, page_count = _verify_pdf(args.pdf)
    normalized_paths = [Path(value) for value in args.normalized or DEFAULT_INPUTS]
    results = [_load_result(path) for path in normalized_paths]
    started = time.perf_counter()
    adaptations = [
        adapt_to_v24(
            result,
            source_file=FileRef(
                file_id=f"sha256-{SOURCE_SHA256}",
                uri=args.pdf.name,
                mime_type="application/pdf",
                sha256=SOURCE_SHA256,
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
        for result in results
    ]
    merged = _merge_documents([item.document for item in adaptations])
    source_indexes = _source_index_map(results, adaptations)
    incomplete_blocks = {
        sidecar.block_id
        for adaptation in adaptations
        for coverage in adaptation.formula_dedup_coverage
        if coverage.cross_page_incomplete
        for sidecar in adaptation.formula_sidecars
        if sidecar.formula_group_id == coverage.target_formula_group_id
    }
    semantic = assemble_semantics(
        merged,
        source_indexes=source_indexes,
        incomplete_block_ids=incomplete_blocks,
        known_explanation_cover_page=277,
    )
    repeated = assemble_semantics(
        merged,
        source_indexes=source_indexes,
        incomplete_block_ids=incomplete_blocks,
        known_explanation_cover_page=277,
    )
    deterministic = semantic.document == repeated.document
    if not deterministic:
        raise SystemExit("semantic replay is not deterministic")
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    _write_json(
        output / "document.semantic.partial.json", semantic.document.model_dump(mode="json")
    )
    _write_json(output / "semantic_source_lineage.json", semantic.lineage.model_dump(mode="json"))
    _write_json(
        output / "semantic_pending_links.json", semantic.pending_links.model_dump(mode="json")
    )
    _write_json(output / "semantic_summary.json", _semantic_summary(semantic.document))
    _write_json(
        output / "raw_inputs_manifest.json",
        _raw_manifest(normalized_paths, results, args.pdf),
    )
    checks = _real_case_checks(semantic.document, semantic.pending_links.model_dump(mode="json"))
    _write_json(
        output / "task_1_5_results.json",
        {
            "algorithm_version": SEMANTIC_ASSEMBLER_VERSION,
            "source_pdf_sha256": SOURCE_SHA256,
            "mineru_versions": sorted({result.producer_version for result in results}),
            "middle_protocols": sorted(
                {f"{result.schema_id}/{result.schema_version}" for result in results}
            ),
            "local_replay_only": True,
            "golden_dataset_status": "candidate_pending_human_review",
            "accuracy_metrics_computed": False,
            "deterministic_repeat": deterministic,
            "postprocess_seconds": time.perf_counter() - started,
            "statistics": semantic.statistics,
            "cases": checks,
        },
    )
    _render_overlays(args.pdf, semantic.document, output / "overlays")
    if args.comparison_baseline is not None:
        _write_json(
            output / "repair_diff.json",
            _repair_diff(args.comparison_baseline, semantic.document, semantic.statistics),
        )
        _write_json(
            output / "repair_replay_manifest.json",
            _repair_replay_manifest(
                output,
                args.comparison_baseline,
                normalized_paths,
                args.pdf,
            ),
        )
    print(
        json.dumps(
            {
                "output": str(output),
                "statistics": semantic.statistics,
                "real_checks": checks,
            },
            ensure_ascii=False,
        )
    )
    return 0 if all(item["status"] in {"pass", "partial"} for item in checks) else 1


def _merge_documents(documents: list[Document]) -> Document:
    if not documents:
        raise SystemExit("at least one normalized input is required")
    base = documents[0]
    _validate_merge_source_identity(base, documents)
    pages = sorted(
        [page for document in documents for page in document.pages],
        key=lambda page: page.page_number,
    )
    if len({page.page_number for page in pages}) != len(pages):
        raise SystemExit("normalized inputs contain duplicate physical pages")
    block_ids = [block.block_id for page in pages for block in page.blocks]
    if len(set(block_ids)) != len(block_ids):
        raise SystemExit("normalized inputs contain duplicate block identities")
    tables = [table for document in documents for table in document.tables]
    if len({table.table_id for table in tables}) != len(tables):
        raise SystemExit("normalized inputs contain duplicate table identities")
    _validate_merged_table_fragments(pages, tables)
    warnings = [warning for document in documents for warning in document.processing.warnings]
    payload = base.model_dump(mode="json")
    payload.update(
        pages=[page.model_dump(mode="json") for page in pages],
        sections=[],
        tables=[table.model_dump(mode="json") for table in tables],
        clauses=ClauseGroups().model_dump(mode="json"),
        processing=ProcessingMetadata(
            parser_id="engineering_rag.document_parser.mineru.semantic",
            parser_version=SEMANTIC_ASSEMBLER_VERSION,
            partial=True,
            is_complete_document_ocr=False,
            warnings=warnings,
        ).model_dump(mode="json"),
    )
    return Document.model_validate(payload)


def _validate_merge_source_identity(base: Document, documents: list[Document]) -> None:
    """Fail closed before combining evidence from independently parsed batches."""

    if base.source_file.sha256 is None:
        raise SystemExit(
            "source identity cannot be verified: source_file.sha256 is required or a trusted "
            "upstream manifest must resolve it"
        )
    expected = {
        "document_id": base.document_id,
        "source_file.file_id": base.source_file.file_id,
        "source_file.sha256": base.source_file.sha256,
        "page_count": base.page_count,
        "standard.standard_code": base.standard.standard_code,
        "standard.edition": base.standard.edition,
        "bbox_coordinate_system": base.bbox_coordinate_system.model_dump(mode="json"),
    }
    for batch_index, document in enumerate(documents[1:], start=1):
        actual = {
            "document_id": document.document_id,
            "source_file.file_id": document.source_file.file_id,
            "source_file.sha256": document.source_file.sha256,
            "page_count": document.page_count,
            "standard.standard_code": document.standard.standard_code,
            "standard.edition": document.standard.edition,
            "bbox_coordinate_system": document.bbox_coordinate_system.model_dump(mode="json"),
        }
        if actual["source_file.sha256"] is None:
            raise SystemExit(
                f"source identity cannot be verified for batch {batch_index}: "
                "source_file.sha256 is required"
            )
        conflicts = [field for field, value in actual.items() if value != expected[field]]
        if conflicts:
            raise SystemExit(
                f"source identity conflict in batch {batch_index}: {', '.join(conflicts)}"
            )


def _validate_merged_table_fragments(pages: list[Page], tables: list[LogicalTable]) -> None:
    blocks = {block.block_id: (page.page_number, block) for page in pages for block in page.blocks}
    claimed_fragments: dict[str, str] = {}
    for table in tables:
        fragment_ids = [fragment.block_id for fragment in table.fragments]
        source_ids = list(table.source_block_ids)
        if fragment_ids != source_ids:
            raise SystemExit(
                f"table fragment integrity conflict for {table.table_id}: source order mismatch"
            )
        for fragment in table.fragments:
            previous_table = claimed_fragments.setdefault(fragment.block_id, table.table_id)
            if previous_table != table.table_id:
                raise SystemExit(
                    f"table fragment {fragment.block_id} is claimed by multiple logical tables"
                )
            location = blocks.get(fragment.block_id)
            if location is None:
                raise SystemExit(
                    f"table fragment integrity conflict for {table.table_id}: missing block "
                    f"{fragment.block_id}"
                )
            page_number, block = location
            if (
                page_number != fragment.page_number
                or block.table_id != table.table_id
                or block.fragment_index != fragment.fragment_index
            ):
                raise SystemExit(
                    f"table fragment integrity conflict for {table.table_id}: "
                    f"page/table/index mismatch at {fragment.block_id}"
                )


def _source_index_map(
    results: list[MinerUParseResult], adaptations: list[object]
) -> dict[str, int]:
    indexes: dict[str, int] = {}
    for result, adaptation in zip(results, adaptations, strict=True):
        for page in result.pages:
            for element in page.elements:
                block_id = _stable_id(
                    "block",
                    result.source_sha256,
                    str(element.page_number),
                    str(element.source_index),
                    element.raw_type,
                )
                indexes[block_id] = element.source_index
        for sidecar in adaptation.formula_sidecars:  # type: ignore[attr-defined]
            indexes[sidecar.block_id] = min(sidecar.source_indices)
    return indexes


def _semantic_summary(document: Document) -> dict[str, object]:
    return {
        "normative_section_tree": _section_tree(document, "normative"),
        "explanation_section_tree": _section_tree(document, "explanation"),
        "normative_clauses": [_clause_summary(clause) for clause in document.clauses.normative],
        "explanation_clauses": [
            _clause_summary(clause) for clause in document.clauses.explanations
        ],
    }


def _section_tree(document: Document, group: str) -> list[dict[str, object]]:
    return [
        {
            "section_id": section.section_id,
            "number": section.number,
            "title": section.title,
            "parent_section_id": section.parent_section_id,
            "structure_path": section.structure_path,
        }
        for section in document.sections
        if section.content_group.value == group
    ]


def _clause_summary(clause: object) -> dict[str, object]:
    return {
        "clause_id": clause.clause_id,
        "clause_number": clause.clause_number,
        "section_id": clause.section_id,
        "page_start": clause.page_start,
        "page_end": clause.page_end,
        "source_block_ids": clause.source_block_ids,
        "content_types": [unit.content_type.value for unit in clause.clause_content.content_units],
        "has_plain_text_cache": clause.clause_content.plain_text is not None,
        "review_warning": clause.clause_content.review_warning,
        "explains_clause_id": clause.explains_clause_id,
    }


def _real_case_checks(document: Document, pending: dict[str, object]) -> list[dict[str, object]]:
    normative = {clause.clause_number: clause for clause in document.clauses.normative}
    explanations = {clause.clause_number: clause for clause in document.clauses.explanations}
    page_types = {page.page_number: page.page_type.value for page in document.pages}
    c621 = normative.get("6.2.1")
    c912 = normative.get("9.1.2")
    formula_ids = (
        []
        if c621 is None
        else [
            formula_id
            for unit in c621.clause_content.content_units
            for formula_id in unit.formula_ids
        ]
    )
    relations = pending["relations"]
    checks = [
        _check("GB-C01", "1.0.1" in normative and page_types.get(16) == "body"),
        _check(
            "GB-C02",
            c621 is not None
            and (c621.page_start, c621.page_end) == (49, 50)
            and len(formula_ids) == 7,
        ),
        _check(
            "GB-C04",
            c912 is not None
            and any(len(unit.source_block_ids) == 2 for unit in c912.clause_content.content_units)
            and "9.1.3" in normative,
        ),
        _check("GB-C07", page_types.get(277) == "explanation_cover"),
        _check(
            "GB-C08",
            "1.0.1" in explanations
            and explanations["1.0.1"].explains_clause_id == normative["1.0.1"].clause_id,
        ),
        _check(
            "GB-C10",
            page_types.get(301) == "explanation_body"
            and "4.1.5" not in normative
            and not any(
                item["relation_type"] == "orphan_content" and item["source_id"].startswith("f-")
                for item in relations
            ),
            status="partial",
            note=(
                "page 301 begins mid-section; clauses without loaded section parent remain pending"
            ),
        ),
    ]
    return checks


def _check(
    case_id: str, condition: bool, *, status: str = "pass", note: str | None = None
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "status": status if condition else "fail",
        "machine_candidate_only": True,
        "note": note,
    }


def _raw_manifest(
    normalized_paths: list[Path], results: list[MinerUParseResult], pdf: Path
) -> dict[str, object]:
    return {
        "source_pdf": _file_record(pdf),
        "local_only": True,
        "inputs": [
            {
                "normalized": _file_record(path),
                "raw_middle_json": _file_record(result.raw_middle_json),
                "physical_pages": [page.page_number for page in result.pages],
                "producer_version": result.producer_version,
                "protocol": f"{result.schema_id}/{result.schema_version}",
                "inference_seconds": result.elapsed_seconds,
            }
            for path, result in zip(normalized_paths, results, strict=True)
        ],
    }


def _repair_diff(
    baseline_path: Path,
    repaired: Document,
    repaired_statistics: dict[str, int],
) -> dict[str, object]:
    if baseline_path.is_symlink() or baseline_path.stat().st_size > MAX_JSON_BYTES:
        raise SystemExit(f"unsafe or oversized comparison baseline: {baseline_path}")
    baseline = Document.model_validate_json(baseline_path.read_text(encoding="utf-8"))
    baseline_pages = {page.page_number: page for page in baseline.pages}
    repaired_pages = {page.page_number: page for page in repaired.pages}
    page_zone_changes = []
    for page_number in sorted(set(baseline_pages) | set(repaired_pages)):
        before = baseline_pages.get(page_number)
        after = repaired_pages.get(page_number)
        before_value = None if before is None else before.page_type.value
        after_value = None if after is None else after.page_type.value
        before_basis = None if before is None else before.page_type_basis
        after_basis = None if after is None else after.page_type_basis
        if (before_value, before_basis) != (after_value, after_basis):
            page_zone_changes.append(
                {
                    "physical_page": page_number,
                    "before": {"page_type": before_value, "page_type_basis": before_basis},
                    "after": {"page_type": after_value, "page_type_basis": after_basis},
                }
            )
    return {
        "baseline": _file_record(baseline_path),
        "repaired_document_id": repaired.document_id,
        "source_pdf_sha256": repaired.source_file.sha256,
        "schema_version": repaired.schema_version,
        "algorithm_version": SEMANTIC_ASSEMBLER_VERSION,
        "page_zone_changes": page_zone_changes,
        "baseline_statistics": {
            "pages": len(baseline.pages),
            "sections": len(baseline.sections),
            "normative_clauses": len(baseline.clauses.normative),
            "explanation_clauses": len(baseline.clauses.explanations),
        },
        "repaired_statistics": repaired_statistics,
        "public_schema_changed": False,
    }


def _repair_replay_manifest(
    output: Path,
    baseline_path: Path,
    normalized_paths: list[Path],
    pdf_path: Path,
) -> dict[str, object]:
    output_files = [
        path
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "repair_replay_manifest.json"
    ]
    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "repair_scope": "task1.5-semantic-source-repair",
        "algorithm_version": SEMANTIC_ASSEMBLER_VERSION,
        "source_pdf": _file_record(pdf_path),
        "immutable_normalized_inputs": [_file_record(path) for path in normalized_paths],
        "comparison_baseline": _file_record(baseline_path),
        "output_directory": str(output),
        "outputs": [_file_record(path) for path in output_files],
    }


def _render_overlays(pdf_path: Path, document: Document, output: Path) -> None:
    import pymupdf
    from PIL import Image, ImageDraw

    output.mkdir(parents=True, exist_ok=True)
    clause_by_block = {
        block_id: clause.clause_number
        for clause in document.clauses.normative + document.clauses.explanations
        for block_id in clause.source_block_ids
    }
    section_blocks = {
        record.source_block_id: record.candidate_label
        for record in assemble_semantics(
            document, known_explanation_cover_page=277
        ).lineage.source_records
        if record.candidate_kind == "section_heading"
    }
    with pymupdf.open(pdf_path) as pdf:
        for page in document.pages:
            pixmap = pdf[page.page_number - 1].get_pixmap(matrix=pymupdf.Matrix(144 / 72, 144 / 72))
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            draw = ImageDraw.Draw(image)
            scale_x = pixmap.width / page.width
            scale_y = pixmap.height / page.height
            for block in page.blocks:
                label = clause_by_block.get(block.block_id) or section_blocks.get(block.block_id)
                if label is None:
                    continue
                box = (
                    block.bbox.x_min * scale_x,
                    block.bbox.y_min * scale_y,
                    block.bbox.x_max * scale_x,
                    block.bbox.y_max * scale_y,
                )
                color = "#0057d9" if block.block_id in clause_by_block else "#00a86b"
                draw.rectangle(box, outline=color, width=3)
                draw.text((box[0] + 2, box[1] + 2), str(label), fill=color)
            draw.rectangle((10, 10, 430, 58), fill="#ffffff", outline="#222222", width=2)
            draw.text((18, 18), f"Task 1.5 | physical page {page.page_number}", fill="#111111")
            draw.text((18, 38), "GREEN section | BLUE clause source", fill="#111111")
            image.save(output / f"page_{page.page_number:04d}_semantic_overlay.png")


def _load_result(path: Path) -> MinerUParseResult:
    if path.is_symlink() or path.stat().st_size > MAX_JSON_BYTES:
        raise SystemExit(f"unsafe or oversized normalized input: {path}")
    result = MinerUParseResult.model_validate_json(path.read_text(encoding="utf-8"))
    if (
        result.schema_id != "docvortex.middle"
        or result.schema_version != "2.0"
        or not result.producer_version.startswith("4.")
        or result.source_sha256 != SOURCE_SHA256
    ):
        raise SystemExit(f"unsupported or mismatched MinerU input: {path}")
    return result


def _verify_pdf(path: Path) -> tuple[int, int]:
    import pymupdf

    if _sha256(path) != SOURCE_SHA256:
        raise SystemExit("PDF SHA256 does not match the fixed Task 1.5 source")
    with pymupdf.open(path) as document:
        if document.page_count != 441:
            raise SystemExit("Task 1.5 source must contain 441 physical pages")
        return path.stat().st_size, document.page_count


def _file_record(path: Path) -> dict[str, object]:
    return {"path": str(path), "sha256": _sha256(path), "size_bytes": path.stat().st_size}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{uuid5(NAMESPACE_URL, '|'.join(parts)).hex}"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay bounded Task 1.5 semantic cases locally")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--normalized", action="append", default=[])
    parser.add_argument(
        "--comparison-baseline",
        type=Path,
        help="optional prior Document JSON used only to emit an auditable semantic diff",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
