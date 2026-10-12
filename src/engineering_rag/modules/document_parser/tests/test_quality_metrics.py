"""Task 1.6 verified-gold safeguards."""

import pytest

from engineering_rag.modules.document_parser.internal.e2e.quality import (
    evaluate_verified_records,
)


def test_no_verified_gold_is_not_evaluated() -> None:
    result = evaluate_verified_records([])
    assert result["golden_dataset_status"] == "not_evaluated"
    for name, metric in result["metrics"].items():
        if name == "page_type_per_class":
            assert metric == {
                "status": "not_evaluated",
                "classes": {},
                "macro_f1": None,
            }
            continue
        assert metric == {
            "status": "not_evaluated",
            "numerator": 0,
            "denominator": 0,
            "value": None,
        }


def test_verified_label_requires_auditable_review_metadata() -> None:
    with pytest.raises(ValueError, match="review metadata"):
        evaluate_verified_records([{"golden_status": "verified"}])


def test_verified_page_type_metric_has_explicit_counts() -> None:
    result = evaluate_verified_records(
        [
            {
                "golden_status": "verified",
                "reviewer": "reviewer-1",
                "reviewed_at": "2026-10-12T08:00:00Z",
                "dataset_version": "1",
                "provenance": "PDF p16 + overlay",
                "verified_labels": {"page_types": {"16": "body"}},
                "machine_predictions": {"page_types": {"16": "body"}},
            }
        ]
    )
    metric = result["metrics"]["page_type_accuracy"]
    assert metric == {"status": "evaluated", "numerator": 1, "denominator": 1, "value": 1.0}


def test_verified_ocr_and_reviewed_observations_use_real_denominators() -> None:
    result = evaluate_verified_records(
        [
            {
                "golden_status": "verified",
                "reviewer": "reviewer-1",
                "reviewed_at": "2026-10-12T08:00:00Z",
                "dataset_version": "1",
                "provenance": "PDF crop",
                "verified_labels": {
                    "ocr_text_pairs": [{"reference": "混凝土", "prediction": "混疑土"}],
                    "metric_observations": {
                        "formula_accuracy": [True, False, True],
                        "bbox_iou": [0.8, 0.6],
                    },
                },
                "machine_predictions": {},
            }
        ]
    )
    assert result["metrics"]["ocr_cer"]["numerator"] == 1
    assert result["metrics"]["ocr_cer"]["denominator"] == 3
    assert result["metrics"]["formula_accuracy"]["value"] == pytest.approx(2 / 3)
    assert result["metrics"]["bbox_iou"]["value"] == pytest.approx(0.7)
