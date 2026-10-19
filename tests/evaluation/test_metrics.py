"""Hand-calculated metric checks; these are not real retrieval quality scores."""

from math import log2

import pytest

from engineering_rag.contracts.retrieval import SearchFilters
from engineering_rag.infrastructure.evaluation.internal.metrics import (
    filter_metrics,
    paired_metric_comparison,
    processing_intent_metrics,
    protected_span_metrics,
    ranking_metrics,
)


def test_ranking_hand_calculation_and_fixed_precision_denominator() -> None:
    scores = ranking_metrics(
        ["weak", "core", "unknown", "related"], {"core": 3, "related": 2, "weak": 1}, [1, 2, 5]
    )
    assert scores["recall@1"] == 0.0
    assert scores["precision@1"] == 0.0
    assert scores["mrr@2"] == 0.5
    assert scores["hit_rate@2"] == 1.0
    assert scores["recall@2"] == 0.5
    assert scores["precision@5"] == 2 / 5
    expected_dcg = 1 + 7 / log2(3) + 3 / log2(5)
    expected_idcg = 7 + 3 / log2(3) + 1 / log2(4)
    assert scores["ndcg@5"] == pytest.approx(expected_dcg / expected_idcg)


def test_ranking_first_hit_and_empty_retrieval() -> None:
    assert ranking_metrics(["a"], {"a": 3}, [5])["mrr@5"] == 1.0
    scores = ranking_metrics([], {"a": 3}, [5])
    assert scores == {
        "recall@5": 0.0,
        "precision@5": 0.0,
        "mrr@5": 0.0,
        "ndcg@5": 0.0,
        "hit_rate@5": 0.0,
    }


def test_no_relevant_denominator_is_not_reported_as_failure() -> None:
    scores = ranking_metrics(["a"], {"a": 1}, [1])
    assert scores["recall@1"] is None
    assert scores["mrr@1"] is None
    assert scores["hit_rate@1"] is None
    assert scores["ndcg@1"] == 1.0  # nDCG uses all nonzero graded labels.
    assert scores["precision@1"] == 0.0
    assert ranking_metrics([], {}, [1])["ndcg@1"] is None


@pytest.mark.parametrize(
    ("ids", "qrels", "ks", "threshold"),
    [
        (["a", "a"], {"a": 3}, [1], 2),
        ([""], {"a": 3}, [1], 2),
        (["a"], {"a": True}, [1], 2),
        (["a"], {"a": 4}, [1], 2),
        (["a"], {"a": -1}, [1], 2),
        (["a"], {"": 3}, [1], 2),
        (["a"], {"a": 3}, [0], 2),
        (["a"], {"a": 3}, [True], 2),
        (["a"], {"a": 3}, [1, 1], 2),
        (["a"], {"a": 3}, [], 2),
        (["a"], {"a": 3}, [1], 0),
    ],
)
def test_invalid_ranking_input_rejected(ids, qrels, ks, threshold) -> None:
    with pytest.raises(ValueError):
        ranking_metrics(ids, qrels, ks, threshold)


def test_processing_intent_all_wrong_f1_is_zero_not_null() -> None:
    scores = processing_intent_metrics(
        [("acquisition", "exploratory"), ("exploratory", "acquisition")]
    )
    assert scores["accuracy"] == 0.0
    assert scores["macro_f1"] == 0.0
    assert scores["confusion_matrix"] == {
        "acquisition": {"acquisition": 0, "exploratory": 1},
        "exploratory": {"acquisition": 1, "exploratory": 0},
    }


def test_processing_intent_hand_calculation() -> None:
    scores = processing_intent_metrics(
        [
            ("acquisition", "acquisition"),
            ("acquisition", "exploratory"),
            ("exploratory", "exploratory"),
        ]
    )
    assert scores["accuracy"] == pytest.approx(2 / 3)
    assert scores["per_class"]["acquisition"]["precision"] == 1
    assert scores["per_class"]["acquisition"]["recall"] == 0.5
    assert scores["macro_f1"] == pytest.approx(2 / 3)


def test_processing_intent_empty_and_invalid_labels() -> None:
    scores = processing_intent_metrics([])
    assert scores["accuracy"] is None
    assert scores["macro_f1"] is None
    with pytest.raises(ValueError, match="processing intent"):
        processing_intent_metrics([("requirement", "acquisition")])


def test_filters_compare_sets_and_false_is_a_real_constraint() -> None:
    scores = filter_metrics(
        [
            (
                SearchFilters(document_ids=["b", "a"], is_mandatory=False),
                SearchFilters(document_ids=["a", "b"], is_mandatory=None),
            ),
            (SearchFilters(is_explanation=False), SearchFilters(is_explanation=True)),
        ]
    )
    assert scores["exact_match_rate"] == 0.0
    documents = scores["fields"]["document_ids"]
    assert documents["exact_match_rate"] == 1.0
    assert documents["precision"] == 1.0
    assert documents["recall"] == 1.0
    mandatory = scores["fields"]["is_mandatory"]
    assert mandatory["missed_constraint_rate"] == 1.0
    assert mandatory["recall"] == 0.0
    assert mandatory["precision"] is None
    explanation = scores["fields"]["is_explanation"]
    assert explanation["false_accept_count"] == 1
    assert explanation["missed_constraint_count"] == 1
    assert scores["unverified_identity_acceptance_rate"] is None


def test_filter_empty_and_no_constraint_denominators() -> None:
    assert filter_metrics([])["exact_match_rate"] is None
    scores = filter_metrics([(SearchFilters(), SearchFilters())])
    assert scores["exact_match_rate"] == 1.0
    assert scores["fields"]["document_ids"]["recall"] is None


def test_protected_spans_preserve_exact_literals_and_multiplicity() -> None:
    original = "不少于20 mm；20 mm。"
    spans = [
        {"kind": "logic", "text": "不少于", "start": 0, "end": 3},
        {"kind": "quantity", "text": "20 mm", "start": 3, "end": 8},
        {"kind": "quantity", "text": "20 mm", "start": 9, "end": 14},
    ]
    scores = protected_span_metrics(original, "不少于20 mm。", spans)
    assert scores["preservation_rate"] == pytest.approx(2 / 3)
    assert scores["per_kind"]["quantity"]["preservation_rate"] == 0.5
    assert scores["items"][2]["preserved"] is False
    assert protected_span_metrics(original, original, spans)["preservation_rate"] == 1.0


def test_protected_span_invalid_offsets_rejected() -> None:
    with pytest.raises(ValueError, match="original"):
        protected_span_metrics(
            "20 mm", "20 mm", [{"kind": "quantity", "text": "30 mm", "start": 0, "end": 5}]
        )
    assert protected_span_metrics("问题", "问题", [])["preservation_rate"] is None


def test_paired_comparison_only_uses_same_query_valid_scores() -> None:
    result = paired_metric_comparison(
        {"a": 0.5, "b": 1.0, "c": 0.0, "d": None},
        {"a": 1.0, "b": 0.0, "c": 0.0, "d": 1.0},
    )
    assert result["paired_count"] == 3
    assert result["improved"] == 1
    assert result["degraded"] == 1
    assert result["tied"] == 1
    assert result["mean_delta"] == pytest.approx(-1 / 6)
    assert result["bootstrap_ci"] is None


def test_paired_comparison_rejects_changing_query_population() -> None:
    with pytest.raises(ValueError, match="same query"):
        paired_metric_comparison({"a": 1.0}, {"b": 1.0})
