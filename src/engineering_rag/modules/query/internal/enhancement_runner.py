"""Independent bounded stage calls; failures remain typed optional-stage outcomes."""

from dataclasses import dataclass, field
from time import monotonic

from pydantic import JsonValue, ValidationError

from engineering_rag.contracts.llm import StructuredLLMRequest
from engineering_rag.contracts.protocols import StructuredLLMClient

from .enhancement_models import (
    EnhancementAttempt,
    EnhancementConfig,
    EnhancementInput,
    ExpansionOutput,
    FailureCode,
    HyDEOutput,
    Stage,
    StageReport,
    StageStatus,
)
from .enhancement_prompts import (
    EXPANSION_INSTRUCTIONS,
    EXPANSION_PROMPT_VERSION,
    EXPANSION_SEPARATOR,
    HYDE_CONTEXT_SEPARATOR,
    HYDE_FOOTER,
    HYDE_HEADER,
    HYDE_INSTRUCTIONS,
    HYDE_PROMPT_VERSION,
)
from .enhancement_validation import available_contexts, validate_expansions, validate_hypothesis


@dataclass
class StageOutcome:
    status: StageStatus
    report: StageReport
    queries: list[str] = field(default_factory=list)
    hypothesis: str | None = None


def stage_report(stage: Stage, config: EnhancementConfig) -> StageReport:
    model = config.expansion_llm if stage == "query_expansion" else config.hyde_llm
    return StageReport(
        stage=stage,
        model_config_id=model.config_id,
        model_id=model.model_id,
        model_revision=model.model_revision,
        prompt_version=EXPANSION_PROMPT_VERSION
        if stage == "query_expansion"
        else HYDE_PROMPT_VERSION,
    )


def _request(
    inputs: EnhancementInput,
    config: EnhancementConfig,
    report: StageReport,
    request_id: str,
    previous_error: FailureCode | None,
) -> StructuredLLMRequest:
    expansion = report.stage == "query_expansion"
    payload: dict[str, JsonValue] = {
        "instructions": EXPANSION_INSTRUCTIONS if expansion else HYDE_INSTRUCTIONS,
        "prompt_version": report.prompt_version,
        "original_question": inputs.original_question,
        "rewritten_query": inputs.rewritten_query,
        "processing_intent": inputs.processing_intent.value,
        "verified_filters": inputs.filters.model_dump(mode="json"),
        "protected_values": list(inputs.protected_values),
        "available_contexts": [
            item.model_dump(mode="json")
            for item in available_contexts(config, inputs.rewritten_query)
        ],
        "max_output_chars": config.max_expanded_query_chars if expansion else config.max_hyde_chars,
        "previous_error": previous_error,
    }
    if expansion:
        payload.update(
            keyword_synonyms=list(inputs.keyword_synonyms),
            max_items=config.max_expansions,
            expansion_separator=EXPANSION_SEPARATOR,
        )
    else:
        payload.update(
            max_contexts=config.max_hyde_contexts,
            hyde_header=HYDE_HEADER,
            hyde_context_separator=HYDE_CONTEXT_SEPARATOR,
            hyde_footer=HYDE_FOOTER,
        )
    return StructuredLLMRequest(
        request_id=request_id,
        stage=report.stage,
        input=payload,
        output_schema=ExpansionOutput.model_json_schema()
        if expansion
        else HyDEOutput.model_json_schema(),
        config=(config.expansion_llm if expansion else config.hyde_llm).model_copy(deep=True),
        trace=inputs.trace,
    )


def run_stage(
    llm: StructuredLLMClient,
    config: EnhancementConfig,
    inputs: EnhancementInput,
    stage: Stage,
    run_id: str,
    correction_limit: int,
) -> StageOutcome:
    report = stage_report(stage, config)
    previous_error: FailureCode | None = None
    for index in range(1 + correction_limit):
        request = _request(inputs, config, report, f"{run_id}-{stage}-{index}", previous_error)
        started = monotonic()
        usage = None
        try:
            response = llm.generate(request.model_copy(deep=True))
            parsed = response.validate_output(
                request, ExpansionOutput if stage == "query_expansion" else HyDEOutput
            )
            usage = response.usage
        except (ValidationError, ValueError):
            code: FailureCode = "invalid_output"
            retry = True
        except TimeoutError:
            code, retry = "timeout", True
        except ConnectionError:
            code, retry = "connection", True
        except Exception:
            code, retry = "model_failure", False
        else:
            try:
                queries: list[str] = []
                hypothesis: str | None = None
                if isinstance(parsed, ExpansionOutput):
                    queries, decisions = validate_expansions(
                        parsed.expanded_queries, inputs.rewritten_query, config, index + 1
                    )
                    report.decisions.extend(decisions)
                    if not queries and any(
                        item.reason in {"length_budget", "unsafe_candidate"} for item in decisions
                    ):
                        raise ValueError("all substantive Expansion candidates were rejected")
                else:
                    validate_hypothesis(
                        parsed.hypothetical_document, inputs.rewritten_query, config
                    )
                    hypothesis = parsed.hypothetical_document
            except ValueError:
                code, retry = "unsafe_output", True
            else:
                report.attempts.append(
                    EnhancementAttempt(
                        request_id=request.request_id,
                        status="completed",
                        elapsed_seconds=monotonic() - started,
                        usage=usage,
                    )
                )
                return StageOutcome(
                    status=StageStatus.COMPLETED,
                    report=report,
                    queries=queries,
                    hypothesis=hypothesis,
                )
        report.attempts.append(
            EnhancementAttempt(
                request_id=request.request_id,
                status="failed",
                error_code=code,
                elapsed_seconds=monotonic() - started,
                usage=usage,
            )
        )
        if not retry or index == correction_limit:
            report.error_code = code
            return StageOutcome(status=StageStatus.FAILED, report=report)
        previous_error = code
    raise AssertionError("stage attempt budget must include one normal call")
