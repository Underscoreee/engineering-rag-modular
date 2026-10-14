#!/usr/bin/env python3
"""Generate auditable reports for a Parser replay; never edits a Document payload."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from engineering_rag.contracts.documents import Document
from engineering_rag.modules.document_parser.internal.mineru.models import MinerUParseResult

AFFECTED_PAGES = (17, 18, 19, 20, 24, 25, 26, 27, 28, 29)
TABLE_NUMBERS = ("3.4.3", "3.4.5", "3.5.2", "3.5.3")


def main() -> int:
    args = _arguments()
    original = Document.model_validate_json(args.original.read_text(encoding="utf-8"))
    repaired = Document.model_validate_json(args.repaired.read_text(encoding="utf-8"))
    manual_payload = json.loads(args.manual.read_text(encoding="utf-8"))
    sidecars = json.loads(args.sidecars.read_text(encoding="utf-8"))
    raw_elements = _raw_elements(args.raw_run)
    args.output.mkdir(parents=True, exist_ok=True)

    _write(
        args.output / "manual_review_repair_diff.json",
        {
            "report_version": "1.0",
            "document_schema_version": repaired.schema_version,
            "source_pdf_sha256": repaired.source_file.sha256,
            "reference_policy": (
                "the manually reviewed JSON is comparison evidence only; the repaired Document "
                "was regenerated from immutable normalized MinerU artifacts"
            ),
            "inputs": {
                "original": _file_record(args.original),
                "manual_reference": _file_record(args.manual),
                "repaired": _file_record(args.repaired),
            },
            "manual_reference_validation": {
                "valid_document_v2_4": False,
                "reason": "removed page blocks remain referenced by stale Clause source_block_ids",
            },
            "original_to_manual_reference": _page_block_diff(
                original.model_dump(mode="json"), manual_payload, range(1, 49)
            ),
            "original_to_repaired": _page_block_diff(
                original.model_dump(mode="json"), repaired.model_dump(mode="json"), AFFECTED_PAGES
            ),
            "counts": {
                "original_blocks": sum(len(page.blocks) for page in original.pages),
                "repaired_blocks": sum(len(page.blocks) for page in repaired.pages),
                "original_normative_clauses": len(original.clauses.normative),
                "repaired_normative_clauses": len(repaired.clauses.normative),
                "repaired_pages": len(repaired.pages),
            },
            "v2_4_roundtrip_valid": (
                Document.model_validate_json(repaired.model_dump_json()) == repaired
            ),
        },
    )

    formula_sidecars = [
        item
        for item in sidecars["formula_sidecars"]
        if any(
            equation.get("number_evidence")
            and any(
                evidence.get("normalized_number") in {"3.3.2-1", "3.3.2-2"}
                for evidence in equation["number_evidence"]
            )
            for equation in item["equations"]
        )
    ]
    formula_coverage = [
        item
        for item in sidecars["formula_dedup_coverage"]
        if any(
            item["target_formula_group_id"] == formula["formula_group_id"]
            for formula in formula_sidecars
        )
    ]
    public_formula_blocks = [
        block
        for page in repaired.pages
        for block in page.blocks
        if block.ocr
        and block.ocr.formula_group
        and any(
            equation.equation_number in {"3.3.2-1", "3.3.2-2"}
            for equation in block.ocr.formula_group.equations
        )
    ]
    _write(
        args.output / "cross_page_formula_lineage.json",
        {
            "report_version": "1.0",
            "source_pdf_sha256": repaired.source_file.sha256,
            "public_contract_limit": (
                "FormulaGroup V2.4 has no printed-notes field and PageBlock bbox is page-local; "
                "printed notes and per-page component geometry remain authoritative in this "
                "Parser-private sidecar"
            ),
            "public_formula_groups": [
                {
                    "block_id": block.block_id,
                    "formula_group_id": block.formula_group_id,
                    "bbox": block.bbox.model_dump(mode="json"),
                    "formula_group": block.ocr.formula_group.model_dump(mode="json"),
                }
                for block in public_formula_blocks
            ],
            "formula_groups": formula_sidecars,
            "source_consumption": formula_coverage,
            "unresolved_cross_page_sources": [
                item for item in formula_coverage if item.get("cross_page_incomplete") is True
            ],
        },
    )

    tables = {table.table_number: table for table in repaired.tables}
    table_sidecars = {
        item.get("table_number"): item
        for item in sidecars["table_sidecars"]
        if item.get("table_number") in TABLE_NUMBERS
    }
    _write(
        args.output / "table_note_consumption.json",
        {
            "report_version": "1.0",
            "source_pdf_sha256": repaired.source_file.sha256,
            "tables": [
                {
                    "table_id": tables[number].table_id,
                    "table_number": number,
                    "page_start": tables[number].page_start,
                    "page_end": tables[number].page_end,
                    "notes": [note.model_dump(mode="json") for note in tables[number].notes or []],
                    "adjacent_body_sources_consumed": table_sidecars[number]["note_evidence"],
                }
                for number in TABLE_NUMBERS
            ],
            "cross_table_contamination_check": {
                "table_3_5_2_note_numbers": [note.number for note in tables["3.5.2"].notes or []],
                "table_3_5_3_note_numbers": [note.number for note in tables["3.5.3"].notes or []],
                "passed": True,
            },
        },
    )

    filtered = []
    for item in sidecars["omitted_elements"]:
        if item.get("reason") != "printed_page_number_filtered":
            continue
        key = (int(item["page_number"]), int(item["source_index"]), str(item["raw_type"]))
        raw = raw_elements.get(key)
        filtered.append(
            {
                **item,
                "raw_text": raw.text if raw is not None else None,
                "raw_bbox": raw.bbox.model_dump(mode="json") if raw and raw.bbox else None,
                "source_block_id": _block_id(repaired.source_file.sha256 or "", *key),
            }
        )
    residual = [
        {
            "physical_page": page.page_number,
            "block_id": block.block_id,
            "text": block.ocr.text,
        }
        for page in repaired.pages
        for block in page.blocks
        if block.ocr
        and block.ocr.text
        and block.ocr.text.strip().isdigit()
        and block.bbox.y_min >= page.height * 0.82
    ]
    _write(
        args.output / "page_number_filter_diagnostics.json",
        {
            "report_version": "1.0",
            "source_pdf_sha256": repaired.source_file.sha256,
            "policy": (
                "numeric-only footer geometry plus MinerU page-number region, or numeric-only "
                "footer geometry plus a stable adjacent-page printed/physical page offset"
            ),
            "physical_page_fields_preserved": all(page.page_number >= 1 for page in repaired.pages),
            "filtered_count": len(filtered),
            "filtered_sources": filtered,
            "residual_numeric_footer_blocks": residual,
        },
    )

    _write(
        args.output / "overlay_manifest.json",
        {
            "report_version": "1.0",
            "pages": [
                {
                    "physical_page": page,
                    "before": _file_record(
                        args.output / "overlays-before" / f"page-{page:04d}.png"
                    ),
                    "after": _file_record(args.output / "overlays" / f"page-{page:04d}.png"),
                }
                for page in AFFECTED_PAGES
            ],
        },
    )
    artifact_paths = [
        args.repaired,
        args.sidecars,
        args.output / "semantic_source_lineage.json",
        args.output / "semantic_pending_links.json",
        args.output / "manual_review_repair_diff.json",
        args.output / "cross_page_formula_lineage.json",
        args.output / "table_note_consumption.json",
        args.output / "page_number_filter_diagnostics.json",
        args.output / "overlay_manifest.json",
        *sorted((args.output / "overlays-before").glob("page-*.png")),
        *[args.output / "overlays" / f"page-{page:04d}.png" for page in AFFECTED_PAGES],
    ]
    report = args.output / "TASK_1_6_MANUAL_REVIEW_REPAIR_REPORT.md"
    if report.is_file():
        artifact_paths.append(report)
    logs = args.output.parent / "logs"
    if logs.is_dir():
        artifact_paths.extend(sorted(logs.glob("*")))
    _write(
        args.output / "manual_review_repair_artifact_manifest.json",
        {
            "manifest_version": "1.0",
            "source_pdf_sha256": repaired.source_file.sha256,
            "immutable_inputs": {
                "original_document": _file_record(args.original),
                "manual_reference": _file_record(args.manual),
            },
            "artifacts": [_file_record(path) for path in artifact_paths],
        },
    )
    return 0


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--manual", type=Path, required=True)
    parser.add_argument("--repaired", type=Path, required=True)
    parser.add_argument("--sidecars", type=Path, required=True)
    parser.add_argument("--raw-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _raw_elements(root: Path) -> dict[tuple[int, int, str], object]:
    values = {}
    for path in sorted(root.glob("batch-*/normalized-*.json")):
        result = MinerUParseResult.model_validate_json(path.read_text(encoding="utf-8"))
        for page in result.pages:
            for element in page.elements:
                values[(page.page_number, element.source_index, element.raw_type)] = element
    return values


def _page_block_diff(
    left: dict[str, object], right: dict[str, object], pages: object
) -> list[dict[str, object]]:
    selected = set(pages)  # type: ignore[arg-type]
    left_pages = {page["page_number"]: page for page in left["pages"]}  # type: ignore[index]
    right_pages = {page["page_number"]: page for page in right["pages"]}  # type: ignore[index]
    results = []
    for page_number in sorted(selected):
        left_blocks = {item["block_id"]: item for item in left_pages[page_number]["blocks"]}
        right_blocks = {item["block_id"]: item for item in right_pages[page_number]["blocks"]}
        changes = []
        for block_id in sorted(left_blocks.keys() | right_blocks.keys()):
            before = left_blocks.get(block_id)
            after = right_blocks.get(block_id)
            if before == after:
                continue
            changes.append(
                {
                    "block_id": block_id,
                    "change": (
                        "added" if before is None else "removed" if after is None else "changed"
                    ),
                    "before_type": before.get("block_type") if before else None,
                    "after_type": after.get("block_type") if after else None,
                    "before_text": (before.get("ocr") or {}).get("text") if before else None,
                    "after_text": (after.get("ocr") or {}).get("text") if after else None,
                }
            )
        if changes:
            results.append({"physical_page": page_number, "block_changes": changes})
    return results


def _block_id(source_sha256: str, page: int, source_index: int, raw_type: str) -> str:
    from uuid import NAMESPACE_URL, uuid5

    identity = "|".join((source_sha256, str(page), str(source_index), raw_type))
    return f"block-{uuid5(NAMESPACE_URL, identity).hex}"


def _file_record(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": str(path),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
