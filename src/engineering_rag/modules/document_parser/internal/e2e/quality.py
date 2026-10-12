"""Human-review candidates and denominator-safe quality evaluation."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from engineering_rag.contracts.documents import Document

REQUIRED_REVIEW_FIELDS = ("reviewer", "reviewed_at", "dataset_version", "provenance")


def build_candidate_records(
    matrix: dict[str, object], document: Document
) -> list[dict[str, object]]:
    pages = {page.page_number: page for page in document.pages}
    records = []
    for case in matrix.get("real_cases", []):
        if not isinstance(case, dict):
            continue
        physical_pages = case.get("physical_pages", [])
        predictions = {
            str(number): pages[number].page_type.value
            for number in physical_pages
            if isinstance(number, int) and number in pages
        }
        evidence = [
            {
                "physical_page": number,
                "page_type_basis": pages[number].page_type_basis,
                "blocks": [
                    {
                        "block_id": block.block_id,
                        "block_type": block.block_type.value,
                        "bbox_pdf_points": block.bbox.model_dump(mode="json"),
                    }
                    for block in pages[number].blocks
                ],
            }
            for number in physical_pages
            if isinstance(number, int) and number in pages
        ]
        records.append(
            {
                "case_id": case.get("id"),
                "kind": case.get("kind"),
                "physical_pages": physical_pages,
                "candidate_labels": case.get("candidate_labels", {}),
                "machine_predictions": {"page_types": predictions},
                "source_sha256": document.source_file.sha256,
                "source_evidence": evidence,
                "golden_status": "candidate_pending_human_review",
                "reviewer": None,
                "reviewed_at": None,
                "dataset_version": None,
                "provenance": None,
            }
        )
    return records


def evaluate_verified_records(records: Iterable[dict[str, object]]) -> dict[str, object]:
    verified = []
    for record in records:
        if record.get("golden_status") != "verified":
            continue
        missing = [name for name in REQUIRED_REVIEW_FIELDS if not record.get(name)]
        if missing:
            raise ValueError("verified record missing review metadata: " + ", ".join(missing))
        datetime.fromisoformat(str(record["reviewed_at"]).replace("Z", "+00:00"))
        verified.append(record)
    page_type_total = 0
    page_type_correct = 0
    page_confusion: dict[str, dict[str, int]] = {}
    ocr_edits = 0
    ocr_characters = 0
    generic_counts = {
        name: [0, 0]
        for name in (
            "reading_order_accuracy",
            "bbox_iou",
            "table_structure_accuracy",
            "formula_accuracy",
            "condition_link_accuracy",
            "symbol_explanation_accuracy",
            "clause_boundary_accuracy",
            "source_trace_accuracy",
        )
    }
    for record in verified:
        labels = record.get("verified_labels")
        predictions = record.get("machine_predictions")
        if not isinstance(labels, dict) or not isinstance(predictions, dict):
            continue
        expected = labels.get("page_types")
        actual = predictions.get("page_types")
        expected = expected if isinstance(expected, dict) else {}
        actual = actual if isinstance(actual, dict) else {}
        for page, expected_type in expected.items():
            page_type_total += 1
            actual_type = str(actual.get(page))
            page_type_correct += int(actual_type == expected_type)
            row = page_confusion.setdefault(str(expected_type), {})
            row[actual_type] = row.get(actual_type, 0) + 1
        for pair in labels.get("ocr_text_pairs", []):
            if not isinstance(pair, dict):
                continue
            reference = pair.get("reference")
            prediction = pair.get("prediction")
            if isinstance(reference, str) and isinstance(prediction, str) and reference:
                ocr_edits += _levenshtein(reference, prediction)
                ocr_characters += len(reference)
        observations = labels.get("metric_observations", {})
        if isinstance(observations, dict):
            for name, values in observations.items():
                if name not in generic_counts or not isinstance(values, list):
                    continue
                for value in values:
                    if isinstance(value, bool):
                        generic_counts[name][0] += int(value)
                        generic_counts[name][1] += 1
                    elif name == "bbox_iou" and isinstance(value, (int, float)):
                        generic_counts[name][0] += float(value)
                        generic_counts[name][1] += 1
    return {
        "golden_dataset_status": "verified" if verified else "not_evaluated",
        "verified_case_count": len(verified),
        "metrics": {
            "page_type_accuracy": _metric(page_type_correct, page_type_total),
            "page_type_per_class": _page_type_scores(page_confusion),
            "ocr_cer": _metric(ocr_edits, ocr_characters),
            **{name: _metric(*counts) for name, counts in generic_counts.items()},
        },
    }


def _metric(numerator: int | float, denominator: int) -> dict[str, object]:
    return {
        "status": "evaluated" if denominator else "not_evaluated",
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def _page_type_scores(confusion: dict[str, dict[str, int]]) -> dict[str, object]:
    if not confusion:
        return {"status": "not_evaluated", "classes": {}, "macro_f1": None}
    classes = sorted(set(confusion) | {item for row in confusion.values() for item in row})
    scores = {}
    f1_values = []
    for label in classes:
        true_positive = confusion.get(label, {}).get(label, 0)
        false_negative = sum(confusion.get(label, {}).values()) - true_positive
        false_positive = sum(row.get(label, 0) for key, row in confusion.items() if key != label)
        precision = (
            true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else None
        )
        recall = (
            true_positive / (true_positive + false_negative)
            if true_positive + false_negative
            else None
        )
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and precision + recall
            else None
        )
        scores[label] = {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
        if f1 is not None:
            f1_values.append(f1)
    return {
        "status": "evaluated",
        "classes": scores,
        "macro_f1": sum(f1_values) / len(f1_values) if f1_values else None,
    }


def _levenshtein(reference: str, prediction: str) -> int:
    previous = list(range(len(prediction) + 1))
    for row, expected in enumerate(reference, start=1):
        current = [row]
        for column, actual in enumerate(prediction, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + int(expected != actual),
                )
            )
        previous = current
    return previous[-1]
