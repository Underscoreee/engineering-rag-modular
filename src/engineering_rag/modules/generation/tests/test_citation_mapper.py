"""Request authorization, source fidelity and conservative literal quote matching."""

import json
from dataclasses import replace
from types import MappingProxyType

import pytest

from engineering_rag.contracts.chunks import ChunkContentType
from engineering_rag.modules.generation.internal.citation_mapper import CitationMapper
from engineering_rag.modules.generation.internal.context import ContextBuilder
from engineering_rag.modules.generation.internal.models import GenerationError, GenerationOutput

from .helpers import evidence, request, settings


def output(ids=None, quotes=None, **updates):
    return GenerationOutput(
        answer="虚构演示回答。",
        evidence_ids=["E1"] if ids is None else ids,
        grounding_status="grounded",
        limitations=[],
        quotes=quotes or [],
        **updates,
    )


def context(*items):
    return ContextBuilder(settings()).build(
        request(evidence=list(items) if items else [evidence()])
    )


@pytest.mark.parametrize("explanation", [None, False, True])
@pytest.mark.parametrize("mandatory", [None, False, True])
@pytest.mark.parametrize("kind", [None, *ChunkContentType])
def test_exact_authorized_source_and_metadata_retained(explanation, mandatory, kind):
    value = context(evidence(is_explanation=explanation, is_mandatory=mandatory, content_type=kind))
    before = value.registry["E1"].model_dump_json()
    result = CitationMapper().map(output(), value)
    assert result.context is value
    assert result.citations[0].evidence_chunk_id == value.registry["E1"].chunk_id
    assert result.citations[0].document_id == value.registry["E1"].document_id
    assert result.citations[0].clause_id == value.registry["E1"].clause_id
    assert (result.citations[0].page_start, result.citations[0].page_end) == (2, 3)
    assert value.registry["E1"].is_explanation is explanation
    assert value.registry["E1"].is_mandatory is mandatory
    assert value.registry["E1"].content_type == kind
    assert value.registry["E1"].model_dump_json() == before


def test_multi_chunk_dedup_order_determinism_and_optional_clause_number():
    value = context(
        evidence(), evidence(chunk_id="second", rank=2, clause_id=None, clause_number=None)
    )
    mapped = CitationMapper().map(output(ids=["E2", "E1", "E2"]), value)
    assert mapped.evidence_ids == ("E2", "E1")
    assert [c.evidence_chunk_id for c in mapped.citations] == ["second", "fictional-chunk-1"]
    assert mapped.citations[0].clause_id is None
    assert CitationMapper().map(output(ids=["E2", "E1", "E2"]), value) == mapped


@pytest.mark.parametrize("reference", ["unknown", "E2", "fictional-chunk-1", "HyDE", "Expansion"])
def test_non_context_ids_are_rejected(reference):
    with pytest.raises(GenerationError, match="unknown_evidence_id"):
        CitationMapper().map(output(ids=[reference]), context())


def test_retrieved_but_budget_omitted_chunk_is_not_authorized():
    base = context().estimated_chars
    value = ContextBuilder(settings(max_context_chars=base + 50)).build(
        request(
            evidence=[
                evidence(content="超长" * 5000),
                evidence(chunk_id="small", rank=2),
            ]
        )
    )
    assert set(value.registry) == {"E2"}
    with pytest.raises(GenerationError, match="unknown_evidence_id"):
        CitationMapper().map(output(), value)


@pytest.mark.parametrize("field", ["standard_code", "standard_name", "page_start", "page_end"])
def test_missing_required_source_is_not_guessed(field):
    value = context()
    item = value.registry["E1"]
    target = item.standard if field.startswith("standard_") else item
    target.__dict__[field] = None
    with pytest.raises(GenerationError, match="invalid_evidence"):
        CitationMapper().map(output(), value)


def test_same_chunk_conflicting_sources_in_registry_fail():
    value = context(evidence(), evidence(chunk_id="second", document_id="another", rank=2))
    value.registry["E2"].__dict__["chunk_id"] = value.registry["E1"].chunk_id
    with pytest.raises(GenerationError, match="evidence_conflict"):
        CitationMapper().map(output(), value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("document_id", "forged"),
        ("clause_number", "9.9.9"),
        ("is_explanation", True),
        ("is_mandatory", False),
        ("content_type", ChunkContentType.FORMULA),
    ],
)
def test_registry_source_changes_after_prompt_are_detected(field, value):
    original = context()
    setattr(original.registry["E1"], field, value)
    with pytest.raises(GenerationError, match="source_metadata_conflict"):
        CitationMapper().map(output(), original)


def test_extra_registry_items_not_in_prompt_are_rejected():
    value = context()
    forged = replace(
        value, registry=MappingProxyType({**value.registry, "E2": evidence(chunk_id="extra")})
    )
    with pytest.raises(GenerationError, match="invalid_registry"):
        CitationMapper().map(output(ids=["E2"]), forged)


@pytest.mark.parametrize(
    ("source", "quote"),
    [
        ("检查间隔不应超过7天。", "不应超过7天"),
        ("荷载\n  不应\t超过 7 天。", "荷载 不应 超过 7 天"),
        (r"x \le -1，按式 (1.1-1)。", r"x \le -1"),
        (
            json.dumps(
                {"columns": ["类别", "限值"], "data": [["一级", "0.10"]]}, ensure_ascii=False
            ),
            '"0.10"',
        ),
        (
            json.dumps({"equations": [{"latex": r"\gamma_0 S \le R"}]}, ensure_ascii=False),
            r"\\gamma_0 S \\le R",
        ),
    ],
)
def test_verbatim_formula_table_and_safe_whitespace_quotes(source, quote):
    value = context(evidence(content=source))
    mapped = CitationMapper().map(
        output(quotes=[{"evidence_id": "E1", "quoted_text": quote}]), value
    )
    assert mapped.citations[0].quoted_text == quote  # Never silently rewrite the model quote.


@pytest.mark.parametrize(
    ("source", "quote"),
    [
        ("不应超过7天", "不应超过8天"),
        ("x <= -1", "x <= 1"),
        ("x <= -1", "x >= -1"),
        ("不适用于水下", "适用于全部构件"),
        ("1 2", "12"),
        ("0.10", "0.1"),
        ("荷载", "荷\n载"),
        ("x ≤ 1", "x <= 1"),
        (r"x\le y", r"x\leq y"),
        ("7天", " \n\t"),
        (json.dumps({"latex": r"\gamma_0"}), r"\gamma_0"),
    ],
)
def test_mismatches_are_not_fuzzy_fixed_or_semantically_normalized(source, quote):
    with pytest.raises(GenerationError, match="quote_mismatch"):
        CitationMapper().map(
            output(quotes=[{"evidence_id": "E1", "quoted_text": quote}]),
            context(evidence(content=source)),
        )


def test_quote_duplicates_conflicts_and_orphan_references():
    quote = {"evidence_id": "E1", "quoted_text": "检查间隔"}
    assert len(CitationMapper().map(output(quotes=[quote, quote]), context()).citations) == 1
    with pytest.raises(GenerationError, match="quote_conflict"):
        CitationMapper().map(output(quotes=[quote, {**quote, "quoted_text": "7天"}]), context())
    with pytest.raises(GenerationError, match="orphan_quote"):
        CitationMapper().map(output(ids=[], quotes=[quote]), context())


@pytest.mark.parametrize(
    "field", ["standard_code", "standard_name", "clause_number", "page_start", "is_mandatory"]
)
def test_model_cannot_supply_free_source_fields(field):
    with pytest.raises(ValueError):
        GenerationOutput.model_validate(
            {
                "answer": "演示",
                "evidence_ids": ["E1"],
                "grounding_status": "grounded",
                "limitations": [],
                "quotes": [{"evidence_id": "E1", "quoted_text": "7天", field: "invented"}],
            }
        )
