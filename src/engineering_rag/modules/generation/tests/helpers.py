"""Explicitly fictional engineering evidence and an offline model dependency."""

from engineering_rag.contracts.answers import GenerationRequest
from engineering_rag.contracts.llm import (
    StructuredLLMConfig,
    StructuredLLMRequest,
    StructuredLLMResponse,
)
from engineering_rag.contracts.retrieval import RetrievalResult
from engineering_rag.modules.generation.internal.models import GenerationSettings


def evidence(**updates: object) -> RetrievalResult:
    values = {
        "chunk_id": "fictional-chunk-1",
        "logical_chunk_id": "fictional-logical-1",
        "document_id": "fictional-document",
        "content": "虚构演示：检查间隔不应超过7天；本条不适用于水下构件。",
        "standard": {
            "standard_name": "虚构检修标准（非真实规范）",
            "standard_code": "DEMO 000-2026",
        },
        "clause_id": "fictional-clause-1",
        "clause_number": "1.1.1",
        "page_start": 2,
        "page_end": 3,
        "score": 0.5,
        "rank": 1,
        "retrieval_source": "hybrid",
        "score_type": "rrf",
        "index_name": "fictional-index",
        "is_explanation": False,
        "is_mandatory": None,
        "content_type": "clause",
    }
    return RetrievalResult.model_validate({**values, **updates})


def settings(**updates: object) -> GenerationSettings:
    return GenerationSettings.model_validate(
        {
            "provider": "fictional-provider",
            "llm": StructuredLLMConfig(
                config_id="fictional-generation",
                model_id="fictional-model",
                timeout_seconds=5,
                max_output_tokens=512,
            ),
            **updates,
        }
    )


def request(**updates: object) -> GenerationRequest:
    return GenerationRequest.model_validate(
        {"question": "虚构示例的检查间隔和适用范围是什么？", "evidence": [evidence()], **updates}
    )


class FakeLLM:
    def __init__(
        self, data: dict[str, object] | None = None, failures: list[Exception] | None = None
    ) -> None:
        self.data = (
            data
            if data is not None
            else {
                "answer": "虚构示例规定：检查间隔不应超过7天，不适用于水下构件。",
                "evidence_ids": ["E1"],
                "grounding_status": "grounded",
                "limitations": [],
            }
        )
        self.failures = list(failures or [])
        self.requests: list[StructuredLLMRequest] = []

    def generate(self, value: StructuredLLMRequest) -> StructuredLLMResponse:
        self.requests.append(value.model_copy(deep=True))
        if self.failures:
            raise self.failures.pop(0)
        return StructuredLLMResponse(
            request_id=value.request_id,
            model_id=value.config.model_id,
            data=self.data,
            usage={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        )
