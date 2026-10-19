"""Generation remains a Protocol; only its approved evidence DTO is exercised."""

import pytest

from engineering_rag.contracts.answers import GenerationRequest
from engineering_rag.contracts.retrieval import RetrievalResult


@pytest.mark.parametrize("explanation", [None, False, True])
@pytest.mark.parametrize("mandatory", [None, False, True])
def test_generation_input_retains_approved_source_metadata(explanation, mandatory) -> None:
    evidence = RetrievalResult(
        chunk_id="fiction-chunk",
        logical_chunk_id="fiction-logical",
        document_id="fiction-doc",
        content="虚构的接口测试文字。",
        standard={"standard_name": "虚构标准", "standard_code": "DEMO 1"},
        page_start=1,
        page_end=1,
        score=1.0,
        rank=1,
        retrieval_source="hybrid",
        score_type="rrf",
        index_name="fiction-hybrid",
        is_explanation=explanation,
        is_mandatory=mandatory,
        content_type="table",
    )
    request = GenerationRequest(question="虚构问题", evidence=[evidence])
    restored = GenerationRequest.model_validate_json(request.model_dump_json())
    assert restored.evidence == [evidence]
    assert set(restored.model_dump()) == {"question", "evidence", "history", "config", "trace"}
