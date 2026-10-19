"""Lossless, request-local context assembly without retrieval or tokenization."""

import json

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.chunks import ChunkContentType
from engineering_rag.modules.generation.internal.context import ContextBuilder
from engineering_rag.modules.generation.internal.models import GenerationError

from .helpers import evidence, request, settings


@pytest.mark.parametrize("explanation", [None, False, True])
@pytest.mark.parametrize("mandatory", [None, False, True])
@pytest.mark.parametrize("kind", [None, *ChunkContentType])
def test_source_attributes_are_never_inferred(explanation, mandatory, kind):
    item = evidence(is_explanation=explanation, is_mandatory=mandatory, content_type=kind)
    context = ContextBuilder(settings()).build(request(evidence=[item]))
    row = context.payload["evidence"][0]
    assert row["is_explanation"] is explanation
    assert row["is_mandatory"] is mandatory
    assert row["content_type"] == kind
    assert row["content"] == item.content
    assert context.registry["E1"] == item


def test_empty_and_duplicate_evidence_and_stable_rank():
    builder = ContextBuilder(settings())
    assert not builder.build(request(evidence=[])).registry
    first = evidence(rank=2)
    second = evidence(chunk_id="fictional-second", rank=1)
    context = builder.build(request(evidence=[first, second, first]))
    assert list(context.registry) == ["E1", "E2"]
    assert context.registry["E1"] == second
    assert context.registry["E2"] == first
    assert len(context.payload["evidence"]) == 2
    assert builder.build(request()).registry is not context.registry


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("document_id", "other-document"),
        ("content", "不同正文"),
        ("is_explanation", True),
        ("is_mandatory", False),
        ("content_type", "formula"),
        ("page_start", 1),
        ("clause_id", "different"),
    ],
)
def test_conflicting_same_chunk_identity_fails(field, value):
    with pytest.raises(GenerationError, match="evidence_conflict"):
        ContextBuilder(settings()).build(request(evidence=[evidence(), evidence(**{field: value})]))


@pytest.mark.parametrize("missing", ["standard", "page_start", "page_end"])
def test_missing_required_source_fields_cannot_be_fabricated(missing):
    values = evidence().model_dump(mode="json")
    del values[missing]
    with pytest.raises(ValidationError):
        request(evidence=[values])


def test_empty_standard_name_and_mutated_missing_page_are_rejected():
    item = evidence()
    item.standard.standard_name = "   "
    with pytest.raises(GenerationError, match="invalid_evidence"):
        ContextBuilder(settings()).build(request(evidence=[item]))
    value = request()
    value.evidence[0].__dict__["page_start"] = None
    with pytest.raises(GenerationError, match="invalid_request"):
        ContextBuilder(settings()).build(value)


@pytest.mark.parametrize("kind", ["formula", "table", "clause"])
def test_whole_semantic_content_survives_or_is_omitted(kind):
    content = json.dumps(
        {
            "equations": [{"latex": "a<=b", "condition": "x>0"}],
            "symbol_explanations": [{"latex": "a", "content": "荷载"}],
            "columns": ["一级"],
            "data": [["7天"]],
            "notes": ["不适用于水下"],
        },
        ensure_ascii=False,
    )
    item = evidence(content=content, content_type=kind)
    builder = ContextBuilder(settings())
    normal = builder.build(request(evidence=[item]))
    assert normal.payload["evidence"][0]["content"] == content
    baseline = builder.build(request(evidence=[])).estimated_chars
    tight = ContextBuilder(settings(max_context_chars=baseline + 10)).build(
        request(evidence=[item])
    )
    assert tight.payload["evidence"] == [] and not tight.registry
    assert tight.omitted[0].reason == "whole_evidence_exceeds_budget"
    assert item.content == content


def test_question_and_system_are_not_truncated_for_budget():
    with pytest.raises(GenerationError, match="context_budget"):
        ContextBuilder(settings(max_context_chars=1)).build(request())


def test_oversize_high_rank_chunk_can_be_skipped_without_losing_smaller_chunk():
    normal = ContextBuilder(settings()).build(request())
    items = [evidence(content="很长" * 5000), evidence(chunk_id="small", rank=2)]
    context = ContextBuilder(settings(max_context_chars=normal.estimated_chars + 50)).build(
        request(evidence=items)
    )
    assert list(context.registry) == ["E2"]
    assert len(context.omitted) == 1


def test_history_recent_whole_turns_after_evidence_and_deterministic():
    value = request(
        history=[
            {"role": "user", "content": "旧问题"},
            {"role": "assistant", "content": "旧回答引用不是来源"},
            {"role": "user", "content": "新对话"},
        ]
    )
    builder = ContextBuilder(settings(max_history_turns=2))
    first = builder.build(value)
    assert first.payload["history"] == [turn.model_dump(mode="json") for turn in value.history[-2:]]
    assert first.history_omitted == 1
    assert len(first.registry) == 1
    assert builder.build(value).payload == first.payload
    tight = ContextBuilder(settings(max_history_chars=1)).build(value)
    assert tight.history_omitted == 3 and not tight.payload["history"]
