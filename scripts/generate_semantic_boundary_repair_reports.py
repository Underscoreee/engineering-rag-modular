#!/usr/bin/env python3
"""Build audit artifacts from immutable before/after Parser replay outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from engineering_rag.contracts.documents import Document

AFFECTED_PAGES = (24, 25, 41, 45)


def main() -> int:
    args = _arguments()
    before = Document.model_validate_json(args.before.read_text(encoding="utf-8"))
    after = Document.model_validate_json(args.after.read_text(encoding="utf-8"))
    sidecars = json.loads(args.sidecars.read_text(encoding="utf-8"))
    pending = json.loads(args.pending.read_text(encoding="utf-8"))
    if before.source_file.sha256 != after.source_file.sha256:
        raise ValueError("before/after source PDF identity mismatch")
    args.output.mkdir(parents=True, exist_ok=True)
    authoritative = args.output / "document.v2.4.semantic-boundary-repaired.json"
    shutil.copy2(args.after, authoritative)

    formula_note = next(
        note
        for group in sidecars["formula_sidecars"]
        for note in group.get("printed_notes", [])
        if "3.3.2-1" in note.get("referenced_equation_numbers", [])
    )
    clause_332 = _clause(after, "3.3.2")
    note_text = formula_note["raw_text"]
    _write(
        args.output / "formula_note_lineage.json",
        {
            "source_pdf_sha256": after.source_file.sha256,
            "source": formula_note,
            "public_projection": {
                "policy": "retained_as_body_because_v2_4_formula_group_has_no_notes_field",
                "clause_id": clause_332.clause_id,
                "clause_number": clause_332.clause_number,
                "page_start": clause_332.page_start,
                "page_end": clause_332.page_end,
                "source_block_ids": clause_332.source_block_ids,
                "plain_text_occurrences": (clause_332.clause_content.plain_text or "").count(
                    note_text
                ),
            },
        },
    )

    old_table = _table(before, "5.2.4")
    new_table = _table(after, "5.2.4")
    clause_525 = _clause(after, "5.2.5")
    table_sidecar = next(
        item for item in sidecars["table_sidecars"] if item.get("table_number") == "5.2.4"
    )
    _write(
        args.output / "table_note_clause_split.json",
        {
            "source_pdf_sha256": after.source_file.sha256,
            "before_notes": [item.model_dump(mode="json") for item in old_table.notes or []],
            "after_notes": [item.model_dump(mode="json") for item in new_table.notes or []],
            "after_clause": clause_525.model_dump(mode="json"),
            "source_note_evidence": table_sidecar.get("note_evidence", []),
            "boundary_policy": "three_level_clause_start_precedes_sequential_table_note_matching",
        },
    )

    old_equation = _equation(before, "4.2.6-1")
    new_equation = _equation(after, "4.2.6-1")
    leadin_relation = next(
        relation
        for group in sidecars["formula_sidecars"]
        for relation in group.get("body_relations", [])
        if relation.get("source_page_number") == 41
        and "预应力筋疲劳应力比值" in relation.get("raw_text", "")
    )
    clause_426 = _clause(after, "4.2.6")
    _write(
        args.output / "formula_leadin_split.json",
        {
            "source_pdf_sha256": after.source_file.sha256,
            "before_symbol_explanations": (
                old_equation[1].symbol_explanations.model_dump(mode="json")
                if old_equation[1].symbol_explanations
                else None
            ),
            "after_symbol_explanations": (
                new_equation[1].symbol_explanations.model_dump(mode="json")
                if new_equation[1].symbol_explanations
                else None
            ),
            "retained_body_relation": leadin_relation,
            "clause_id": clause_426.clause_id,
            "plain_text_occurrences": (clause_426.clause_content.plain_text or "").count(
                leadin_relation["raw_text"]
            ),
            "boundary_policy": "formula_leadin_lexical_marker_plus_adjacent_next_equation",
        },
    )

    affected_pending = [
        item
        for item in pending.get("relations", [])
        if set(item.get("physical_pages", [])).intersection({25, 41, 45})
    ]
    _write(
        args.output / "unresolved_pending.json",
        {
            "source_pdf_sha256": after.source_file.sha256,
            "affected_pages": [25, 41, 45],
            "relations": affected_pending,
            "count": len(affected_pending),
        },
    )

    checks = {
        "formula_note_public_occurrences": (clause_332.clause_content.plain_text or "").count(
            note_text
        ),
        "table_5_2_4_note_numbers": [item.number for item in new_table.notes or []],
        "clause_5_2_5_restored": clause_525.clause_number == "5.2.5",
        "formula_leadin_public_occurrences": (clause_426.clause_content.plain_text or "").count(
            leadin_relation["raw_text"]
        ),
        "formula_leadin_absent_from_4_2_6_1_symbols": all(
            leadin_relation["raw_text"] not in item.description
            for item in (
                new_equation[1].symbol_explanations.items
                if new_equation[1].symbol_explanations
                else []
            )
        ),
        "v2_4_roundtrip": Document.model_validate_json(after.model_dump_json()) == after,
    }
    _write(
        args.output / "semantic_consumption_diff.json",
        {
            "source_pdf_sha256": after.source_file.sha256,
            "before": _file_record(args.before),
            "after": _file_record(args.after),
            "authoritative_copy": _file_record(authoritative),
            "affected_pages": list(AFFECTED_PAGES),
            "checks": checks,
            "all_checks_pass": checks
            == {
                "formula_note_public_occurrences": 1,
                "table_5_2_4_note_numbers": [1, 2, 3, 4],
                "clause_5_2_5_restored": True,
                "formula_leadin_public_occurrences": 1,
                "formula_leadin_absent_from_4_2_6_1_symbols": True,
                "v2_4_roundtrip": True,
            },
        },
    )

    overlay_records = []
    for page_number in AFFECTED_PAGES:
        before_overlay = args.before_root / "final/overlays" / f"page-{page_number:04d}.png"
        after_overlay = args.after_root / "final/overlays" / f"page-{page_number:04d}.png"
        before_target = args.output / "overlays-before" / before_overlay.name
        after_target = args.output / "overlays-after" / after_overlay.name
        before_target.parent.mkdir(parents=True, exist_ok=True)
        after_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(before_overlay, before_target)
        shutil.copy2(after_overlay, after_target)
        overlay_records.append(
            {
                "physical_page": page_number,
                "before": _file_record(before_target),
                "after": _file_record(after_target),
            }
        )
    _write(args.output / "overlay_manifest.json", {"pages": overlay_records})
    return 0


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--sidecars", type=Path, required=True)
    parser.add_argument("--pending", type=Path, required=True)
    parser.add_argument("--before-root", type=Path, required=True)
    parser.add_argument("--after-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _clause(document: Document, number: str):  # type: ignore[no-untyped-def]
    return next(item for item in document.clauses.normative if item.clause_number == number)


def _table(document: Document, number: str):  # type: ignore[no-untyped-def]
    return next(item for item in document.tables if item.table_number == number)


def _equation(document: Document, number: str):  # type: ignore[no-untyped-def]
    return next(
        (equation, block.ocr.formula_group)
        for page in document.pages
        for block in page.blocks
        if block.ocr and block.ocr.formula_group
        for equation in block.ocr.formula_group.equations
        if equation.equation_number == number
    )


def _file_record(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": str(path),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }


def _write(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
