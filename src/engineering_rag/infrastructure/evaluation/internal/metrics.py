"""Pure metrics: callers must validate human labels and corpus identity first.

Ranking assumes unique Chunk identities in returned rank order. Unjudged hits have
gain zero; this conventional policy is not proof that incomplete judgments are
exhaustive. Undefined denominators return ``None``, never fabricated zero scores.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from math import isfinite, log2

from engineering_rag.contracts.retrieval import SearchFilters

PROCESSING_INTENTS = ("acquisition", "exploratory")


def _ratio(numerator: int | float, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _identifier(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def ranking_metrics(
    retrieved_ids: Sequence[str],
    qrels: Mapping[str, int],
    ks: Sequence[int],
    relevance_threshold: int = 2,
) -> dict[str, float | None]:
    """Compute fixed-K precision, binary recall/MRR/hit rate and graded nDCG.

    Binary relevance is grade >= ``relevance_threshold``. nDCG uses every grade
    with gain ``2**grade - 1`` and discount ``log2(rank + 1)``. Precision always
    divides by K, including short/empty results. Recall/MRR/hit rate need at least
    one binary-relevant judgment; nDCG needs positive ideal DCG. Missing qrels
    targets and snapshot mismatches must be rejected by the dataset validator,
    not counted as retrieval failures here.
    """
    if isinstance(retrieved_ids, str) or any(not _identifier(x) for x in retrieved_ids):
        raise ValueError("retrieved IDs must be nonblank strings")
    if len(set(retrieved_ids)) != len(retrieved_ids):
        raise ValueError("duplicate retrieved IDs invalidate rank metrics")
    if any(
        not _identifier(key) or type(grade) is not int or not 0 <= grade <= 3
        for key, grade in qrels.items()
    ):
        raise ValueError("qrels require nonblank Chunk IDs and integer grades 0..3")
    if not ks or any(type(k) is not int or k <= 0 for k in ks):
        raise ValueError("K values must be positive integers")
    if len(set(ks)) != len(ks):
        raise ValueError("duplicate K values are not allowed")
    if type(relevance_threshold) is not int or not 1 <= relevance_threshold <= 3:
        raise ValueError("relevance threshold must be an integer in 1..3")
    relevant_count = sum(grade >= relevance_threshold for grade in qrels.values())
    ideal_grades = sorted(qrels.values(), reverse=True)
    scores: dict[str, float | None] = {}
    for k in ks:
        grades = [qrels.get(chunk_id, 0) for chunk_id in retrieved_ids[:k]]
        relevant_ranks = [
            rank for rank, grade in enumerate(grades, 1) if grade >= relevance_threshold
        ]
        ideal_dcg = sum(
            (2**grade - 1) / log2(rank + 1) for rank, grade in enumerate(ideal_grades[:k], 1)
        )
        dcg = sum((2**grade - 1) / log2(rank + 1) for rank, grade in enumerate(grades, 1))
        scores[f"recall@{k}"] = _ratio(len(relevant_ranks), relevant_count)
        scores[f"precision@{k}"] = len(relevant_ranks) / k
        scores[f"mrr@{k}"] = (
            (1 / relevant_ranks[0] if relevant_ranks else 0.0) if relevant_count else None
        )
        scores[f"ndcg@{k}"] = dcg / ideal_dcg if ideal_dcg else None
        scores[f"hit_rate@{k}"] = float(bool(relevant_ranks)) if relevant_count else None
    return scores


def processing_intent_metrics(pairs: Sequence[tuple[str, str]]) -> dict[str, object]:
    """Evaluate ``(expected, predicted)`` ProcessingIntent pairs, not QueryIntent.

    The fixed two-class macro average uses zero division = 0 on nonempty input,
    so valid but entirely wrong predictions correctly yield macro-F1 = 0. An
    empty experiment has null score rates, rather than a misleading perfect/zero
    score. Confusion rows are expected labels, columns are predictions.
    """
    confusion = {label: dict.fromkeys(PROCESSING_INTENTS, 0) for label in PROCESSING_INTENTS}
    for expected, predicted in pairs:
        if expected not in confusion or predicted not in confusion:
            raise ValueError("unknown processing intent; expected acquisition or exploratory")
        confusion[expected][predicted] += 1
    per_class: dict[str, dict[str, int | float | None]] = {}
    f1s: list[float] = []
    for label in PROCESSING_INTENTS:
        true_positive = confusion[label][label]
        support = sum(confusion[label].values())
        predicted_count = sum(confusion[other][label] for other in PROCESSING_INTENTS)
        precision = true_positive / predicted_count if predicted_count else 0.0
        recall = true_positive / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1s.append(f1)
        per_class[label] = {
            "support": support,
            "predicted_count": predicted_count,
            "precision": precision if pairs else None,
            "recall": recall if pairs else None,
            "f1": f1 if pairs else None,
        }
    return {
        "query_count": len(pairs),
        "accuracy": _ratio(
            sum(confusion[label][label] for label in PROCESSING_INTENTS), len(pairs)
        ),
        "macro_f1": sum(f1s) / len(f1s) if pairs else None,
        "per_class": per_class,
        "confusion_matrix": confusion,
        "undefined_reason": None if pairs else "no_valid_labeled_predictions",
    }


def _filter_atoms(value: list[str] | bool | None) -> set[str | bool]:
    if isinstance(value, list):
        return set(value)
    return set() if value is None else {value}


def filter_metrics(pairs: Sequence[tuple[SearchFilters, SearchFilters]]) -> dict[str, object]:
    """Compare trusted ``(expected, predicted)`` filters, list fields as sets.

    False is an explicit Boolean constraint; None and empty lists mean absent.
    Precision/recall are micro counts of exact constraint atoms per field.
    Missing constraints are FN/expected atoms; unexpected constraints are
    FP/predicted atoms. The latter is a gold mismatch, not evidence that a model
    invented an identity: that separate rate requires source/catalog audit.
    """
    fields: dict[str, dict[str, int | float | str | None]] = {}
    for name in SearchFilters.model_fields:
        exact = true_positive = expected_count = predicted_count = 0
        for expected, predicted in pairs:
            if not isinstance(expected, SearchFilters) or not isinstance(predicted, SearchFilters):
                raise ValueError("filter pairs must contain canonical SearchFilters")
            expected_atoms = _filter_atoms(getattr(expected, name))
            predicted_atoms = _filter_atoms(getattr(predicted, name))
            exact += expected_atoms == predicted_atoms
            true_positive += len(expected_atoms & predicted_atoms)
            expected_count += len(expected_atoms)
            predicted_count += len(predicted_atoms)
        fields[name] = {
            "exact_match_rate": _ratio(exact, len(pairs)),
            "precision": _ratio(true_positive, predicted_count),
            "recall": _ratio(true_positive, expected_count),
            "missed_constraint_rate": _ratio(expected_count - true_positive, expected_count),
            "unexpected_constraint_rate": _ratio(predicted_count - true_positive, predicted_count),
            "expected_constraint_count": expected_count,
            "predicted_constraint_count": predicted_count,
            "matched_constraint_count": true_positive,
            "missed_constraint_count": expected_count - true_positive,
            "false_accept_count": predicted_count - true_positive,
            "undefined_reason": "rate_denominator_zero_returns_null",
        }
    exact_pairs = sum(
        all(
            _filter_atoms(getattr(expected, name)) == _filter_atoms(getattr(predicted, name))
            for name in SearchFilters.model_fields
        )
        for expected, predicted in pairs
    )
    return {
        "query_count": len(pairs),
        "exact_match_rate": _ratio(exact_pairs, len(pairs)),
        "fields": fields,
        "unverified_identity_acceptance_rate": None,
        "unverified_identity_acceptance_reason": "requires_source_and_catalog_audit",
    }


def protected_span_metrics(
    original: str, rewritten: str, spans: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    """Check exact literals using gold ``{start, end, text, kind}`` mappings.

    Original coordinates are zero-based Python character half-open intervals.
    Repeated equal literals require repeated occurrences in the output; matching
    is deterministic in source order. Overlap between different gold literals is
    allowed (e.g. a quantity and its number). This necessary-only lexical check
    cannot establish semantic equivalence, fact correctness or unchanged scope.
    """
    validated: list[tuple[int, int, str, str, int]] = []
    seen: set[tuple[int, int, str]] = set()
    for index, span in enumerate(spans):
        start, end, text, kind = (span.get(key) for key in ("start", "end", "text", "kind"))
        if (
            type(start) is not int
            or type(end) is not int
            or not _identifier(text)
            or not _identifier(kind)
            or not 0 <= start < end <= len(original)
            or original[start:end] != text
        ):
            raise ValueError(f"protected span {index} must match an exact original text interval")
        identity = (start, end, kind)
        if identity in seen:
            raise ValueError(f"duplicate protected span at original interval {start}:{end}")
        seen.add(identity)
        validated.append((start, end, text, kind, index))
    # One source occurrence may carry multiple kinds without requiring duplicate
    # text in the rewrite. Separate source occurrences cannot share one match.
    occurrences: dict[str, set[tuple[int, int]]] = {}
    preserved_by_source: dict[tuple[int, int, str], bool] = {}
    for start, end, text, _kind, _index in sorted(validated):
        source_key = (start, end, text)
        if source_key not in preserved_by_source:
            positions = occurrences.setdefault(text, set())
            positions.add((start, end))
            preserved_by_source[source_key] = rewritten.count(text) >= len(positions)
    per_kind: dict[str, dict[str, int | float | None]] = {}
    items: list[dict[str, object]] = []
    for start, end, text, kind, index in sorted(validated, key=lambda entry: entry[4]):
        preserved = preserved_by_source[(start, end, text)]
        counts = per_kind.setdefault(kind, {"count": 0, "preserved_count": 0})
        counts["count"] += 1
        counts["preserved_count"] += preserved
        items.append({"index": index, "kind": kind, "text": text, "preserved": preserved})
    for counts in per_kind.values():
        counts["preservation_rate"] = _ratio(counts["preserved_count"], counts["count"])
    preserved_count = sum(bool(item["preserved"]) for item in items)
    return {
        "count": len(items),
        "preserved_count": preserved_count,
        "preservation_rate": _ratio(preserved_count, len(items)),
        "per_kind": per_kind,
        "items": items,
        "undefined_reason": None if items else "no_human_annotated_protected_spans",
        "semantic_equivalence": None,
    }


def paired_metric_comparison(
    baseline: Mapping[str, float | None], variant: Mapping[str, float | None]
) -> dict[str, object]:
    """Compare valid scores from an unchanged query population; no fake CI.

    Failed/undefined pairs are counted and excluded explicitly. A changed query
    population is an error, not an invitation to select favorable queries.
    """
    if baseline.keys() != variant.keys():
        raise ValueError("paired variants must use the same query population")
    deltas: list[float] = []
    for query_id in baseline:
        before, after = baseline[query_id], variant[query_id]
        for score in (before, after):
            if score is not None and (
                isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not isfinite(score)
            ):
                raise ValueError("paired scores must be finite numbers or null")
        if before is not None and after is not None:
            deltas.append(after - before)
    counts = Counter(
        "improved" if delta > 0 else "degraded" if delta < 0 else "tied" for delta in deltas
    )
    return {
        "paired_count": len(deltas),
        "excluded_count": len(baseline) - len(deltas),
        "improved": counts["improved"],
        "degraded": counts["degraded"],
        "tied": counts["tied"],
        "mean_delta": sum(deltas) / len(deltas) if deltas else None,
        "bootstrap_ci": None,
        "uncertainty_note": "descriptive_paired_comparison_only_no_statistical_significance_claim",
    }
