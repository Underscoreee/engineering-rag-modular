"""Test composition and observations, not a production API or another evaluator."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from time import monotonic

from scripts._query_smoke_runtime import SmokeError, safe_error_code

from engineering_rag.contracts.answers import (
    AnswerResult,
    GenerationRequest,
    validate_answer_citations,
)
from engineering_rag.contracts.chunks import ChunkBatch
from engineering_rag.contracts.llm import StructuredLLMRequest, StructuredLLMResponse
from engineering_rag.contracts.protocols import GenerationService, QueryService, StructuredLLMClient
from engineering_rag.contracts.queries import QueryRequest
from engineering_rag.contracts.retrieval import RetrievalResult


class ObservedLLM:
    """Forward unchanged requests; observe actual generation input, never reconstruct it.

    Full rows stay only in process for assertions. Persisted reports store IDs,
    source properties, counters and digests, not full prompts or provider bodies.
    """

    def __init__(self, client: StructuredLLMClient) -> None:
        self.client = client
        self.requests: list[StructuredLLMRequest] = []

    def generate(self, request: StructuredLLMRequest) -> StructuredLLMResponse:
        self.requests.append(request.model_copy(deep=True))
        return self.client.generate(request)


@dataclass(frozen=True)
class SmokeCase:
    case_id: str
    category: str
    request: QueryRequest
    expected_empty_from_inventory: bool = False


def _assert_source(hit: RetrievalResult, batch: ChunkBatch) -> None:
    chunk = next((chunk for chunk in batch.chunks if chunk.chunk_id == hit.chunk_id), None)
    if chunk is None:
        raise SmokeError("retrieval_unknown_chunk")
    for field in (
        "logical_chunk_id",
        "document_id",
        "content",
        "standard",
        "clause_id",
        "clause_number",
        "page_start",
        "page_end",
        "is_explanation",
        "is_mandatory",
        "content_type",
    ):
        if getattr(hit, field) != getattr(chunk, field):
            raise SmokeError("retrieval_source_mismatch")


def verify_answer(
    result: AnswerResult,
    evidence: list[RetrievalResult],
    generation_calls: list[StructuredLLMRequest],
) -> dict[str, object]:
    """Inspect actual prompt evidence and server output; no semantic gold is inferred."""
    checked = AnswerResult.model_validate_json(result.model_dump_json())
    if checked != result or not result.answer.strip():
        raise SmokeError("answer_schema_or_round_trip")
    if not evidence:
        if (
            generation_calls
            or result.citations
            or result.grounding_status != "insufficient_evidence"
        ):
            raise SmokeError("empty_evidence_policy")
        return {
            "included_chunk_ids": [],
            "citation_count": 0,
            "valid_citations": 0,
            "identity_matches": 0,
            "raw_quotes": 0,
            "quote_count": 0,
            "source_rows": 0,
            "source_rows_matching": 0,
        }
    if not generation_calls:
        # A whole-context budget skip may legitimately avoid the model. This
        # corpus uses default budgets; do not pretend to have observed its IDs.
        raise SmokeError("generation_context_not_observed")
    rows = generation_calls[-1].input.get("evidence")
    if not isinstance(rows, list):
        raise SmokeError("generation_context_missing_rows")
    returned = {item.chunk_id: item for item in evidence}
    included = {}
    source_matches = 0
    for row in rows:
        if not isinstance(row, dict) or row.get("chunk_id") not in returned:
            raise SmokeError("generation_context_not_retrieved")
        item = returned[row["chunk_id"]]
        if item.chunk_id in included:
            raise SmokeError("generation_context_duplicate")
        expected = {
            name: getattr(item, name)
            for name in (
                "chunk_id",
                "logical_chunk_id",
                "document_id",
                "clause_id",
                "clause_number",
                "page_start",
                "page_end",
                "is_explanation",
                "is_mandatory",
                "content",
            )
        }
        expected.update(
            standard=item.standard.model_dump(mode="json"),
            content_type=item.content_type.value if item.content_type else None,
        )
        if any(
            name not in row
            or json.dumps(row[name], sort_keys=True) != json.dumps(value, sort_keys=True)
            for name, value in expected.items()
        ):
            raise SmokeError("generation_source_metadata_mismatch")
        included[item.chunk_id] = item
        source_matches += 1
    if validate_answer_citations(result, list(included.values())):
        raise SmokeError("citation_outside_actual_context")
    seen = set()
    raw_quotes = quote_count = 0
    for citation in result.citations:
        if citation.citation_id in seen or citation.evidence_chunk_id not in included:
            raise SmokeError("citation_identity_invalid")
        seen.add(citation.citation_id)
        item = included[citation.evidence_chunk_id]
        if (citation.page_start, citation.page_end) != (item.page_start, item.page_end):
            raise SmokeError("citation_page_range_changed")
        if citation.quoted_text is not None:
            quote_count += 1
            raw_quotes += int(citation.quoted_text in item.content)
    return {
        "included_chunk_ids": list(included),
        "citation_count": len(result.citations),
        "valid_citations": len(result.citations),
        "identity_matches": len(result.citations),
        "raw_quotes": raw_quotes,
        "quote_count": quote_count,
        "source_rows": len(rows),
        "source_rows_matching": source_matches,
        "prompt_version": generation_calls[-1].input.get("prompt_version"),
        "source_properties": [
            {
                name: row.get(name)
                for name in (
                    "evidence_id",
                    "chunk_id",
                    "is_explanation",
                    "is_mandatory",
                    "content_type",
                )
            }
            for row in rows
        ],
    }


def run_case(
    case: SmokeCase,
    *,
    query: QueryService,
    generation: GenerationService,
    observed_llm: ObservedLLM,
    batch: ChunkBatch,
) -> tuple[dict[str, object], AnswerResult | None]:
    """Run Query.execute exactly once; failures remain failures with stage evidence."""
    started = monotonic()
    offset = len(observed_llm.requests)
    row: dict[str, object] = {
        "test_case_id": case.case_id,
        "category": case.category,
        "trace_id": case.request.trace.trace_id if case.request.trace else None,
        "question": case.request.question,
        "is_human_gold": False,
        "expected_evidence": "NOT AVAILABLE: no verified qrels",
        "question_sha256": hashlib.sha256(case.request.question.encode()).hexdigest(),
        "status": "FAIL",
        "failure_stage": "query",
        "retrieved_chunk_ids": [],
        "included_chunk_ids": [],
        "citations": [],
        "grounding_status": None,
    }
    answer = None
    try:
        query_result = query.execute(case.request)
        for hit in query_result.evidence:
            _assert_source(hit, batch)
        row["retrieved_chunk_ids"] = [hit.chunk_id for hit in query_result.evidence]
        row["query_plan"] = query_result.plan.model_dump(mode="json")
        if case.expected_empty_from_inventory and query_result.evidence:
            raise SmokeError("expected_empty_inventory_scope")
        generation_request = GenerationRequest(
            question=case.request.question,
            evidence=query_result.evidence,
            history=case.request.history,
            trace=case.request.trace,
        )
        before = generation_request.model_dump_json()
        row["failure_stage"] = "generation"
        answer = generation.generate(generation_request)
        if generation_request.model_dump_json() != before:
            raise SmokeError("generation_mutated_input")
        row["failure_stage"] = "post_validation"
        calls = [
            request for request in observed_llm.requests[offset:] if request.stage == "generation"
        ]
        row.update(verify_answer(answer, query_result.evidence, calls))
        row.update(
            status="PASS",
            failure_stage=None,
            grounding_status=answer.grounding_status.value,
            citations=[citation.model_dump(mode="json") for citation in answer.citations],
        )
    except Exception as error:
        row["error_code"] = safe_error_code(error)
        # Preserve IDs actually sent before failure, without asserting they were accepted.
        calls = [
            request for request in observed_llm.requests[offset:] if request.stage == "generation"
        ]
        if calls:
            row["included_chunk_ids"] = [
                item.get("chunk_id")
                for item in calls[-1].input.get("evidence", [])
                if isinstance(item, dict)
            ]
        answer = None
    row["elapsed_seconds"] = monotonic() - started
    row["llm_stages"] = [request.stage for request in observed_llm.requests[offset:]]
    return row, answer


def structural_metrics(rows: list[dict[str, object]]) -> dict[str, object]:
    successful = [row for row in rows if row["status"] == "PASS"]

    def fraction(numerator: str, denominator: str) -> dict[str, int | float | None]:
        top = sum(int(row.get(numerator, 0)) for row in successful)
        bottom = sum(int(row.get(denominator, 0)) for row in successful)
        return {"numerator": top, "denominator": bottom, "value": top / bottom if bottom else None}

    return {
        "scope": "machine_source_consistency_only_not_human_quality",
        "successful_cases_only": True,
        "citation_authorization": fraction("valid_citations", "citation_count"),
        "citation_identity": fraction("identity_matches", "citation_count"),
        "prompt_source_passthrough": fraction("source_rows_matching", "source_rows"),
        "raw_quote_substring": fraction("raw_quotes", "quote_count"),
        "claim_coverage": None,
        "explanation_classification_accuracy": None,
        "human_answer_quality": None,
        "limitations": (
            "Failed cases are separately reported, not counted as valid citations; "
            "raw quote substring is not full semantic accuracy"
        ),
    }
