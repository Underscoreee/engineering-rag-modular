"""Aggregate recorded observations without promoting simulations to real quality.

The runner owns execution provenance and decides where these descriptive results
may be published. This module neither runs retrieval nor infers human judgments.
Failed queries remain in counts and coverage; missing scores are never silently
imputed as zero or treated as successful predictions.
"""

from collections.abc import Sequence
from math import isfinite
from statistics import mean

from engineering_rag.contracts.retrieval import SearchFilters

from .metrics import (
    filter_metrics,
    paired_metric_comparison,
    processing_intent_metrics,
)
from .telemetry import model_usage

STATUSES = ("success", "expected_rejection", "failed", "not_run", "skipped")
RANKING_NAMES = ("recall", "precision", "mrr", "ndcg", "hit_rate")


def _number(value: object, *, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number or null")
    return float(value)


def _average(values: Sequence[object]) -> dict[str, object]:
    valid = [_number(value, name="metric or timing") for value in values]
    measured = [value for value in valid if value is not None]
    return {
        "mean": mean(measured) if measured else None,
        "sample_count": len(measured),
        "null_count": len(values) - len(measured),
        "undefined_reason": None if measured else "no_valid_measured_samples",
    }


def _fraction(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _mapping(value: object, *, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be an object with string keys")
    return value


def _intent_and_filter_summary(
    rows: Sequence[dict[str, object]], *, applicable: bool
) -> dict[str, object]:
    intent_pairs: list[tuple[str, str]] = []
    filter_pairs: list[tuple[SearchFilters, SearchFilters]] = []
    intent_expected_count = filter_expected_count = 0
    # Raw retrieval uses the common gold scope but does not run Understanding.
    # Scoring oracle filters would invent perfect model quality; an absent
    # prediction from a deliberately bypassed stage is not a model failure.
    for row in rows if applicable else []:
        expected, predicted = row.get("expected_intent"), row.get("predicted_intent")
        if expected is not None:
            if not isinstance(expected, str):
                raise ValueError("expected_intent must be a string or null")
            intent_expected_count += 1
            if predicted is not None:
                if not isinstance(predicted, str):
                    raise ValueError("predicted_intent must be a string or null")
                intent_pairs.append((expected, predicted))
        expected, predicted = row.get("expected_filters"), row.get("predicted_filters")
        if expected is not None:
            expected_filter = SearchFilters.model_validate(expected)
            filter_expected_count += 1
            if predicted is not None:
                filter_pairs.append((expected_filter, SearchFilters.model_validate(predicted)))
    intents = processing_intent_metrics(intent_pairs)
    correct_intents = sum(expected == predicted for expected, predicted in intent_pairs)
    intents.update(
        {
            "applicable": applicable,
            "reason": None if applicable else "raw_baseline_has_no_understanding",
            "expected_labeled_count": intent_expected_count,
            "missing_prediction_count": intent_expected_count - len(intent_pairs),
            "accuracy_including_missing": _fraction(correct_intents, intent_expected_count),
            "conditional_score_note": (
                "classification_rates_use_valid_pairs; missing_predictions_reported"
            ),
        }
    )
    filters = filter_metrics(filter_pairs)
    conditional_exact = filters["exact_match_rate"]
    exact_count = (
        round(conditional_exact * len(filter_pairs)) if conditional_exact is not None else 0
    )
    filters.update(
        {
            "applicable": applicable,
            "reason": None if applicable else "raw_baseline_has_no_understanding",
            "expected_labeled_count": filter_expected_count,
            "missing_prediction_count": filter_expected_count - len(filter_pairs),
            "exact_match_rate_including_missing": _fraction(exact_count, filter_expected_count),
            "conditional_score_note": "field_rates_use_valid_pairs; missing_predictions_reported",
        }
    )
    return {"processing_intent": intents, "filters": filters}


def _rewrite_summary(rows: Sequence[dict[str, object]]) -> dict[str, object]:
    rates: list[object] = []
    kinds: dict[str, list[object]] = {}
    failed_items: list[dict[str, object]] = []
    for row in rows:
        raw = row.get("rewrite_preservation")
        if raw is None:
            rates.append(None)
            continue
        preservation = _mapping(raw, name="rewrite_preservation")
        rates.append(preservation.get("preservation_rate"))
        for kind, measurements in _mapping(
            preservation.get("per_kind", {}), name="per_kind"
        ).items():
            item = _mapping(measurements, name="protected kind")
            kinds.setdefault(kind, []).append(item.get("preservation_rate"))
        items = preservation.get("items", [])
        if not isinstance(items, list):
            raise ValueError("protected span items must be a list")
        for raw_item in items:
            item = _mapping(raw_item, name="protected span item")
            if item.get("preserved") is False:
                failed_items.append({"query_id": row["query_id"], **item})
    return {
        "preservation_rate": _average(rates),
        "per_kind": {kind: _average(values) for kind, values in kinds.items()},
        "failed_items": failed_items,
        "aggregation": "mean_of_query_rates_not_pooled_span_counts",
        "semantic_equivalence": None,
        "semantic_equivalence_reason": "requires_separate_human_review",
        "scope_change_rate": None,
        "scope_change_reason": "exact_literal_retention_alone_cannot_establish_unchanged_scope",
    }


def _enhancement_summary(rows: Sequence[dict[str, object]], stage: str) -> dict[str, object]:
    valid_count = failed_count = unmeasured_count = legal_empty_count = 0
    accepted_counts: list[object] = []
    preservation_rates: list[object] = []
    empty_flags: list[bool] = []
    overlong_flags: list[bool] = []
    for row in rows:
        payload = _mapping(row.get(stage, {}), name=stage)
        validity = payload.get("valid")
        if validity is not None and type(validity) is not bool:
            raise ValueError(f"{stage}.valid must be Boolean or null")
        if validity is True:
            valid_count += 1
        elif validity is False:
            failed_count += 1
        else:
            unmeasured_count += 1
        if stage == "expansion":
            accepted = payload.get("accepted_count", 0)
            if type(accepted) is not int or accepted < 0:
                raise ValueError("expansion accepted_count must be a nonnegative integer")
            if validity is not None:
                accepted_counts.append(accepted)
            legal_empty_count += validity is True and accepted == 0
            raw_preservations = payload.get("protected_preservation", [])
            if not isinstance(raw_preservations, list):
                raise ValueError("expansion protected_preservation must be a list")
        else:
            raw_preservation = payload.get("protected_preservation")
            raw_preservations = [] if raw_preservation is None else [raw_preservation]
        for raw in raw_preservations:
            preservation_rates.append(
                _mapping(raw, name=f"{stage} protected_preservation").get("preservation_rate")
            )
        for name, flags in (("empty", empty_flags), ("overlong", overlong_flags)):
            flag = payload.get(name)
            if flag is not None:
                if type(flag) is not bool:
                    raise ValueError(f"{stage}.{name} must be Boolean or null")
                flags.append(flag)
    measured_count = valid_count + failed_count
    known_preservation = [
        value
        for value in preservation_rates
        if _number(value, name="protected preservation") is not None
    ]
    return {
        "valid_count": valid_count,
        "failed_count": failed_count,
        "not_measured_or_not_applicable_count": unmeasured_count,
        "valid_output_rate": _fraction(valid_count, measured_count),
        "valid_output_rate_denominator": measured_count,
        "legal_empty_count": legal_empty_count if stage == "expansion" else None,
        "accepted_query_count": _average(accepted_counts) if stage == "expansion" else None,
        "protected_preservation": _average(preservation_rates),
        "protected_violation_rate": _fraction(
            sum(value < 1 for value in known_preservation), len(known_preservation)
        ),
        "protected_violation_sample_count": len(known_preservation),
        "empty_output_rate": _fraction(sum(empty_flags), len(empty_flags)),
        "overlong_output_rate": _fraction(sum(overlong_flags), len(overlong_flags)),
        "human_semantic_review": None,
        "human_factual_review": None,
        "unrelated_output_rate": None,
        "fabricated_fact_rate": None,
        "human_review_reason": "requires_separate_human_semantic_and_factual_annotations",
    }


def _latency_and_usage(rows: Sequence[dict[str, object]]) -> dict[str, object]:
    attempts: list[dict[str, object]] = []
    stage_times: dict[str, list[object]] = {}
    for row in rows:
        raw_attempts = row.get("stage_attempts", [])
        if not isinstance(raw_attempts, list):
            raise ValueError("stage_attempts must be a list")
        for raw in raw_attempts:
            attempt = _mapping(raw, name="stage attempt")
            stage = attempt.get("stage")
            if not isinstance(stage, str) or not stage.strip():
                raise ValueError("model attempt must name its stage")
            elapsed = _number(attempt.get("elapsed_seconds"), name="model call elapsed_seconds")
            if elapsed is not None and elapsed < 0:
                raise ValueError("model call elapsed_seconds cannot be negative")
            stage_times.setdefault(stage, []).append(elapsed)
            attempts.append(attempt)
    usage = model_usage(attempts)
    return {
        "latency": {
            "elapsed_seconds": _average([row.get("elapsed_seconds") for row in rows]),
            "retrieval_seconds": _average([row.get("retrieval_seconds") for row in rows]),
            "model_call_latency": {stage: _average(times) for stage, times in stage_times.items()},
            "model_timing_definition": "model_call_wall_time_only_not_complete_business_stage",
        },
        "token_usage": usage,
        "cost": None,
        "cost_reason": "no_verified_provider_pricing_and_billing_information",
    }


def _variant_summary(
    rows: Sequence[dict[str, object]], metric_keys: Sequence[str], *, variant: str
) -> dict[str, object]:
    counts = {status: sum(row["status"] == status for row in rows) for status in STATUSES}
    attempted = [row for row in rows if row["status"] not in {"not_run", "skipped"}]
    retrieve_rows = [row for row in rows if row["expected_outcome"] == "retrieve"]
    attempted_retrieve = [row for row in attempted if row["expected_outcome"] == "retrieve"]
    correct_outcomes = sum(
        (row["expected_outcome"] == "retrieve" and row["status"] == "success")
        or (row["expected_outcome"] == "reject" and row["status"] == "expected_rejection")
        for row in attempted
    )
    scope_violations = sum(row.get("scope_violation") is True for row in attempted)
    retrieve_scope_violations = sum(
        row.get("scope_violation") is True for row in attempted_retrieve
    )
    reject_scope_violations = sum(
        row.get("scope_violation") is True
        for row in attempted
        if row["expected_outcome"] == "reject"
    )
    rank_metrics: dict[str, dict[str, object]] = {}
    for key in metric_keys:
        values: list[object] = []
        for row in retrieve_rows:
            raw_metrics = row.get("metrics")
            metrics = _mapping(raw_metrics, name="metrics") if raw_metrics is not None else {}
            values.append(metrics.get(key) if row["status"] == "success" else None)
        rank_metrics[key] = _average(values)
    failures = [
        {"query_id": row["query_id"], "status": row["status"], "error": row.get("error")}
        for row in rows
        if row["status"] in {"failed", "not_run"}
    ]
    return {
        "total_queries": len(rows),
        "counts": counts,
        "attempted_query_count": len(attempted),
        "query_failure_rate": _fraction(counts["failed"], len(attempted)),
        "expected_outcome_accuracy": _fraction(correct_outcomes, len(attempted)),
        "retrieval_metrics": rank_metrics,
        "metric_coverage_note": (
            "mean_over_valid_scores; failures_and_missing_scores_counted_as_null"
        ),
        "scope_safety": {
            "violation_count": scope_violations,
            "attempted_query_count": len(attempted),
            "attempted_retrieve_count": len(attempted_retrieve),
            "retrieve_scope_violation_count": retrieve_scope_violations,
            "reject_scope_violation_count": reject_scope_violations,
            "violation_rate": _fraction(scope_violations, len(attempted)),
            "rate_denominator": "all_attempted_queries_including_expected_rejections",
            "definition": "runner_recorded_scope_audit_flags_not_inferred_from_average_quality",
        },
        **_intent_and_filter_summary(rows, applicable=variant != "raw"),
        "rewrite": _rewrite_summary(rows),
        "expansion": _enhancement_summary(rows, "expansion"),
        "hyde": _enhancement_summary(rows, "hyde"),
        **_latency_and_usage(rows),
        "failures": failures,
    }


def summarize_rows(
    rows: Sequence[dict[str, object]], variants: Sequence[str], ks: Sequence[int]
) -> dict[str, object]:
    """Summarize immutable row observations, including every requested variant.

    Every query/variant pair must be unique. Raw-vs-variant comparisons require
    unchanged retrieve-query populations and retain null pairs explicitly. A
    failed variant cannot improve its score by silently dropping hard queries.
    """
    if not variants or len(set(variants)) != len(variants):
        raise ValueError("variants must be nonempty and unique")
    if not ks or len(set(ks)) != len(ks) or any(type(k) is not int or k <= 0 for k in ks):
        raise ValueError("K values must be nonempty, positive and unique")
    metric_keys = [f"{name}@{k}" for k in ks for name in RANKING_NAMES]
    grouped: dict[str, list[dict[str, object]]] = {variant: [] for variant in variants}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        query_id, variant = row.get("query_id"), row.get("variant")
        if not isinstance(query_id, str) or not query_id.strip() or variant not in grouped:
            raise ValueError("rows require a nonblank query_id and requested variant")
        identity = (query_id, variant)
        if identity in seen:
            raise ValueError(f"duplicate query/variant observation {identity}")
        seen.add(identity)
        if row.get("status") not in STATUSES:
            raise ValueError("unknown query run status")
        if row.get("expected_outcome") not in {"retrieve", "reject"}:
            raise ValueError("expected_outcome must be retrieve or reject")
        for key in ("elapsed_seconds", "retrieval_seconds"):
            value = _number(row.get(key), name=key)
            if value is not None and value < 0:
                raise ValueError(f"{key} cannot be negative")
        grouped[variant].append(row)
    summaries = {
        variant: _variant_summary(items, metric_keys, variant=variant)
        for variant, items in grouped.items()
    }
    comparisons: dict[str, dict[str, object]] = {}
    if "raw" in grouped:
        for variant in variants:
            if variant == "raw":
                continue
            comparisons[variant] = {}
            for key in metric_keys:
                by_variant: list[dict[str, float | None]] = []
                for name in ("raw", variant):
                    scores: dict[str, float | None] = {}
                    for row in grouped[name]:
                        if row["expected_outcome"] != "retrieve":
                            continue
                        metrics = row.get("metrics")
                        value = metrics.get(key) if isinstance(metrics, dict) else None
                        scores[row["query_id"]] = (
                            _number(value, name=key) if row["status"] == "success" else None
                        )
                    by_variant.append(scores)
                comparisons[variant][key] = paired_metric_comparison(*by_variant)
    return {
        "per_variant": summaries,
        "paired_vs_raw": comparisons,
        "paired_comparison_reason": None if "raw" in grouped else "raw_variant_not_requested",
        "quality_provenance_note": "execution_mode_and_human_label_validation_owned_by_runner",
    }
