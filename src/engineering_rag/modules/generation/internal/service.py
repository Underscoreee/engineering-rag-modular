"""Evidence-only answer orchestration; no retrieval, SDK creation or hidden fallback."""

from __future__ import annotations

from copy import deepcopy
from logging import getLogger
from threading import RLock
from time import monotonic
from uuid import uuid4

from engineering_rag.contracts.answers import (
    AnswerResult,
    GenerationRequest,
    GroundingStatus,
    ModelMetadata,
)
from engineering_rag.contracts.common import ContractError
from engineering_rag.contracts.llm import StructuredLLMRequest
from engineering_rag.contracts.protocols import StructuredLLMClient

from .answer_validator import AnswerValidator
from .citation_mapper import CitationMapper
from .context import ContextBuilder, GenerationContext
from .models import INSUFFICIENT_ANSWER, GenerationError, GenerationOutput, GenerationSettings

_LOGGER = getLogger(__name__)
_FAILURE_CODES = frozenset(
    {
        "authentication",
        "permission",
        "quota",
        "rate_limit",
        "server_error",
        "timeout",
        "connection",
        "refused",
        "truncated_output",
        "model_mismatch",
        "invalid_json",
    }
)


def _warning(message: str) -> ContractError:
    return ContractError(code="unsupported", message=message)


class DefaultGenerationService:
    def __init__(self, *, llm: StructuredLLMClient, settings: GenerationSettings) -> None:
        self._llm = llm
        self._settings = GenerationSettings.model_validate_json(settings.model_dump_json())
        self._builder = ContextBuilder(self._settings)
        self._mapper = CitationMapper()
        self._validator = AnswerValidator(max_answer_chars=self._settings.max_answer_chars)
        self._calls: list[dict[str, object]] = []
        self._lock = RLock()

    @property
    def calls(self) -> list[dict[str, object]]:
        """Bounded, sanitized attempt diagnostics; no questions, evidence or answers."""
        with self._lock:
            return deepcopy(self._calls)

    def generate(self, request: GenerationRequest) -> AnswerResult:
        context = self._builder.build(request)
        # ContextBuilder validates a fresh copy; retain no mutable caller state.
        request = GenerationRequest.model_validate_json(request.model_dump_json())
        warnings = [
            _warning(f"Evidence omitted: {item.chunk_id}; {item.reason}")
            for item in context.omitted
        ]
        if context.history_omitted:
            warnings.append(_warning(f"History turns omitted: {context.history_omitted}"))
        if not context.registry:
            warnings.append(_warning("No complete evidence available; LLM was not called"))
            result = AnswerResult(
                answer=INSUFFICIENT_ANSWER,
                grounding_status="insufficient_evidence",
                warnings=warnings,
            )
            mapping = self._mapper.map(
                GenerationOutput(
                    answer=INSUFFICIENT_ANSWER,
                    evidence_ids=[],
                    grounding_status="insufficient_evidence",
                    limitations=[],
                ),
                context,
            )
            return self._validator.validate(result, context=context, mapping=mapping)
        config = self._settings.llm.model_copy(deep=True)
        if request.config is not None:
            config = config.model_copy(
                update={
                    "config_id": request.config.config_id,
                    "temperature": request.config.temperature,
                    "max_output_tokens": request.config.max_output_tokens,
                }
            )
        run_id = uuid4().hex
        for attempt in range(self._settings.max_attempts):
            llm_request = StructuredLLMRequest(
                request_id=f"{run_id}-{attempt}",
                stage="generation",
                input=deepcopy(context.payload),
                output_schema=GenerationOutput.model_json_schema(),
                config=config,
                trace=request.trace,
            )
            started = monotonic()
            usage = None
            code = "success"
            try:
                response = self._llm.generate(llm_request.model_copy(deep=True))
                usage = response.usage.model_dump(mode="json") if response.usage else None
                output = response.validate_output(llm_request, GenerationOutput)
                result = self._assemble(output, context, warnings, response.model_revision)
            except Exception as exc:
                # Provider types remain behind Protocol: existing TimeoutError /
                # ConnectionError and ValueError categories determine bounded retry.
                supplied_code = getattr(exc, "code", None)
                if isinstance(exc, GenerationError):
                    code = exc.code
                elif isinstance(supplied_code, str) and supplied_code in _FAILURE_CODES:
                    code = supplied_code
                elif isinstance(exc, TimeoutError):
                    code = "timeout"
                elif isinstance(exc, ConnectionError):
                    code = "connection"
                elif isinstance(exc, ValueError):
                    code = "invalid_output"
                else:
                    code = "model_failure"
                retry = isinstance(exc, (TimeoutError, ConnectionError, ValueError))
                if not retry or attempt + 1 == self._settings.max_attempts:
                    raise GenerationError(code) from None
            else:
                if attempt:
                    result.warnings.append(
                        _warning("Model recovered within bounded attempt budget")
                    )
                return result
            finally:
                observation = {
                    "request_id": llm_request.request_id,
                    "trace_id": request.trace.trace_id if request.trace else None,
                    "model_id": config.model_id,
                    "evidence_count": len(request.evidence),
                    "included_count": len(context.registry),
                    "estimated_context_chars": context.estimated_chars,
                    "elapsed_seconds": monotonic() - started,
                    "usage": usage,
                    "status": code,
                    "grounding_status": result.grounding_status.value
                    if code == "success"
                    else None,
                }
                with self._lock:
                    self._calls.append(observation)
                    del self._calls[:-100]
                _LOGGER.info("generation_attempt", extra={"generation": observation})
        raise AssertionError("positive attempt budget was not enforced")

    def _assemble(
        self,
        output: GenerationOutput,
        context: GenerationContext,
        warnings: list[ContractError],
        revision: str | None,
    ) -> AnswerResult:
        if (
            len(output.answer)
            + sum(map(len, output.limitations))
            + sum(len(quote.quoted_text) for quote in output.quotes)
            > self._settings.max_answer_chars
        ) or any(not item.strip() for item in output.limitations):
            raise GenerationError("output_budget")
        mapping = self._mapper.map(output, context)
        result = AnswerResult(
            answer=INSUFFICIENT_ANSWER
            if output.grounding_status == GroundingStatus.INSUFFICIENT_EVIDENCE
            else output.answer,
            citations=list(mapping.citations),
            grounding_status=output.grounding_status,
            model=ModelMetadata(
                provider=self._settings.provider,
                model_id=self._settings.llm.model_id,
                model_version=revision,
            ),
            warnings=list(warnings),
        )
        return self._validator.validate(
            result,
            context=context,
            mapping=mapping,
            limitations=output.limitations,
        )
