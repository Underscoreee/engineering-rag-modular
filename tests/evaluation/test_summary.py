"""Summary calculations retain failures and distinguish unmeasured quality."""

import json

import pytest

from engineering_rag.infrastructure.evaluation.internal.summary import summarize_rows


def row(query_id: str = "q1", variant: str = "raw", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "query_id": query_id,
        "variant": variant,
        "status": "success",
        "expected_outcome": "retrieve",
        "expected_intent": "acquisition",
        "predicted_intent": "acquisition",
        "expected_filters": {"document_ids": ["a"]},
        "predicted_filters": {"document_ids": ["a"]},
        "metrics": {"recall@5": 0.5, "precision@5": 0.2},
        "rewrite_preservation": None,
        "expansion": {"accepted_count": 0, "valid": None, "protected_preservation": []},
        "hyde": {"valid": None, "protected_preservation": None},
        "stage_attempts": [],
        "retrieval_seconds": 0.2,
        "elapsed_seconds": 0.3,
        "scope_violation": False,
        "error": None,
    }
    return payload | overrides


def test_summary_retains_failed_queries_and_explicit_metric_coverage() -> None:
    result = summarize_rows(
        [
            row(variant="full"),
            row(
                "q2",
                variant="full",
                status="failed",
                metrics=None,
                predicted_intent=None,
                predicted_filters=None,
                error={"code": "backend_failure"},
            ),
        ],
        ["full"],
        [5],
    )["per_variant"]["full"]
    assert result["counts"]["failed"] == 1
    assert result["query_failure_rate"] == 0.5
    assert result["retrieval_metrics"]["recall@5"]["mean"] == 0.5
    assert result["retrieval_metrics"]["recall@5"]["sample_count"] == 1
    assert result["retrieval_metrics"]["recall@5"]["null_count"] == 1
    assert result["processing_intent"]["missing_prediction_count"] == 1
    assert result["processing_intent"]["accuracy_including_missing"] == 0.5
    assert result["filters"]["missing_prediction_count"] == 1
    assert result["filters"]["exact_match_rate_including_missing"] == 0.5


def test_not_run_has_null_scores_not_fake_zero() -> None:
    result = summarize_rows(
        [
            row(
                status="not_run",
                metrics=None,
                predicted_intent=None,
                predicted_filters=None,
                retrieval_seconds=None,
                elapsed_seconds=None,
            )
        ],
        ["raw"],
        [5],
    )["per_variant"]["raw"]
    assert result["counts"]["not_run"] == 1
    assert result["query_failure_rate"] is None
    assert result["retrieval_metrics"]["recall@5"]["mean"] is None
    assert result["scope_safety"]["violation_rate"] is None
    assert result["latency"]["retrieval_seconds"]["mean"] is None


def test_all_wrong_intent_f1_and_false_filter_are_preserved() -> None:
    result = summarize_rows(
        [
            row(
                variant="full",
                expected_intent="acquisition",
                predicted_intent="exploratory",
                expected_filters={"is_mandatory": False},
                predicted_filters={},
            ),
            row(
                "q2", variant="full", expected_intent="exploratory", predicted_intent="acquisition"
            ),
        ],
        ["full"],
        [5],
    )["per_variant"]["full"]
    assert result["processing_intent"]["macro_f1"] == 0.0
    assert result["filters"]["fields"]["is_mandatory"]["missed_constraint_count"] == 1


def test_query_means_do_not_weight_protected_span_rich_queries_more() -> None:
    result = summarize_rows(
        [
            row(
                rewrite_preservation={
                    "preservation_rate": 1.0,
                    "per_kind": {
                        "number": {"count": 4, "preserved_count": 4, "preservation_rate": 1.0}
                    },
                    "items": [],
                }
            ),
            row(
                "q2",
                rewrite_preservation={
                    "preservation_rate": 0.0,
                    "per_kind": {
                        "number": {"count": 1, "preserved_count": 0, "preservation_rate": 0.0}
                    },
                    "items": [{"kind": "number", "text": "20", "preserved": False}],
                },
            ),
        ],
        ["raw"],
        [5],
    )["per_variant"]["raw"]["rewrite"]
    assert result["preservation_rate"]["mean"] == 0.5
    assert result["per_kind"]["number"]["mean"] == 0.5
    assert result["failed_items"][0]["query_id"] == "q2"
    assert result["semantic_equivalence"] is None


def test_valid_empty_expansion_and_failed_hyde_are_separate() -> None:
    result = summarize_rows(
        [
            row(
                expansion={"valid": True, "accepted_count": 0, "protected_preservation": []},
                hyde={"valid": False, "protected_preservation": None},
            ),
            row("q2"),
        ],
        ["raw"],
        [5],
    )["per_variant"]["raw"]
    assert result["expansion"]["valid_output_rate"] == 1.0
    assert result["expansion"]["legal_empty_count"] == 1
    assert result["expansion"]["not_measured_or_not_applicable_count"] == 1
    assert result["hyde"]["valid_output_rate"] == 0.0
    assert result["hyde"]["failed_count"] == 1
    assert result["hyde"]["human_factual_review"] is None


def test_model_call_latency_tokens_and_cost_are_honest() -> None:
    attempts = [
        {
            "stage": "query_understanding",
            "elapsed_seconds": 0.1,
            "status": "success",
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        },
        {"stage": "query_rewrite", "elapsed_seconds": 0.2, "status": "failure", "usage": None},
    ]
    result = summarize_rows([row(stage_attempts=attempts)], ["raw"], [5])["per_variant"]["raw"]
    assert result["latency"]["model_call_latency"]["query_understanding"]["mean"] == 0.1
    assert result["token_usage"]["input_tokens"] is None
    assert result["token_usage"]["attempt_count"] == 2
    assert result["cost"] is None
    assert result["cost_reason"]
    json.dumps(result, allow_nan=False)


def test_paired_comparison_includes_failed_queries_without_zero_imputation() -> None:
    result = summarize_rows(
        [
            row(),
            row("q2", metrics={"recall@5": 1.0}),
            row(variant="full", metrics={"recall@5": 1.0}),
            row("q2", variant="full", status="failed", metrics=None),
        ],
        ["raw", "full"],
        [5],
    )
    comparison = result["paired_vs_raw"]["full"]["recall@5"]
    assert comparison["improved"] == 1
    assert comparison["paired_count"] == 1
    assert comparison["excluded_count"] == 1


def test_expected_rejection_is_not_an_empty_hit_failure() -> None:
    result = summarize_rows(
        [
            row(
                expected_outcome="reject",
                status="expected_rejection",
                metrics=None,
                predicted_intent=None,
                expected_intent=None,
                expected_filters=None,
                predicted_filters=None,
            ),
        ],
        ["raw"],
        [5],
    )["per_variant"]["raw"]
    assert result["counts"]["expected_rejection"] == 1
    assert result["query_failure_rate"] == 0.0
    assert result["expected_outcome_accuracy"] == 1.0
    assert result["retrieval_metrics"]["recall@5"]["sample_count"] == 0


def test_raw_oracle_filters_do_not_claim_understanding_quality() -> None:
    result = summarize_rows([row(predicted_intent=None)], ["raw"], [5])["per_variant"]["raw"]
    intents = result["processing_intent"]
    assert intents["applicable"] is False
    assert intents["reason"] == "raw_baseline_has_no_understanding"
    assert intents["accuracy"] is None
    assert intents["accuracy_including_missing"] is None
    assert intents["expected_labeled_count"] == 0
    filters = result["filters"]
    assert filters["applicable"] is False
    assert filters["exact_match_rate"] is None
    assert filters["exact_match_rate_including_missing"] is None
    assert filters["expected_labeled_count"] == 0
    assert result["scope_safety"]["violation_rate"] == 0.0
    assert result["retrieval_metrics"]["recall@5"]["mean"] == 0.5


def test_reject_query_retrieved_by_mistake_is_a_scope_violation() -> None:
    result = summarize_rows(
        [
            row(
                expected_outcome="reject",
                status="failed",
                scope_violation=True,
                metrics=None,
                expected_intent=None,
                predicted_intent=None,
                expected_filters=None,
                predicted_filters=None,
                error={"code": "unexpected_retrieval"},
            ),
            row("q2"),
        ],
        ["raw"],
        [5],
    )["per_variant"]["raw"]["scope_safety"]
    assert result["violation_count"] == 1
    assert result["violation_rate"] == 0.5
    assert result["attempted_query_count"] == 2
    assert result["retrieve_scope_violation_count"] == 0
    assert result["reject_scope_violation_count"] == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "imaginary_success"},
        {"elapsed_seconds": float("nan")},
        {"metrics": {"recall@5": float("inf")}},
    ],
)
def test_invalid_rows_are_not_silently_aggregated(overrides) -> None:
    with pytest.raises(ValueError):
        summarize_rows([row(**overrides)], ["raw"], [5])


def test_duplicate_rows_and_different_variant_query_populations_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        summarize_rows([row(), row()], ["raw"], [5])
    with pytest.raises(ValueError, match="same query"):
        summarize_rows([row(), row("q2", variant="full")], ["raw", "full"], [5])


def test_empty_summaries_are_explicit() -> None:
    result = summarize_rows([], ["full"], [5])
    assert result["per_variant"]["full"]["total_queries"] == 0
    assert result["paired_comparison_reason"] == "raw_variant_not_requested"
