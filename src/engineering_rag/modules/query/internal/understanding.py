"""Bounded, dependency-injected Understanding only; no retrieval or rewriting."""

from time import monotonic
from uuid import uuid4

from pydantic import ValidationError

from engineering_rag.contracts.catalog import StandardMetadataRecord
from engineering_rag.contracts.llm import StructuredLLMRequest
from engineering_rag.contracts.protocols import StandardMetadataCatalog, StructuredLLMClient
from engineering_rag.contracts.queries import QueryRequest
from engineering_rag.contracts.retrieval import SearchFilters

from .config import UnderstandingConfig
from .errors import ErrorCode, UnderstandingError
from .evidence import (
    CLAUSE_NUMBER,
    STANDARD_CODE,
    code_key,
    verify_boolean,
    verify_content_type,
    verify_text,
)
from .filter_merger import merge_filters, record_filters, restrict_records
from .models import (
    BooleanCandidate,
    CandidateDecision,
    ContentTypeCandidate,
    ModelAttempt,
    StandardCandidate,
    TextCandidate,
    UnderstandingOutput,
    UnderstandingResult,
)
from .prompts import INSTRUCTIONS, PROMPT_VERSION
from .scope_validator import ScopeValidator


class QueryUnderstanding:
    def __init__(
        self,
        *,
        llm: StructuredLLMClient,
        catalog: StandardMetadataCatalog,
        config: UnderstandingConfig,
    ) -> None:
        self._llm = llm
        self._catalog = catalog
        self._config = UnderstandingConfig.model_validate_json(config.model_dump_json())

    @property
    def config(self) -> UnderstandingConfig:
        return self._config.model_copy(deep=True)

    def understand(self, request: QueryRequest) -> UnderstandingResult:
        """Return a fresh validated scope, or raise an audited UnderstandingError."""
        request = QueryRequest.model_validate_json(request.model_dump_json())
        self._check_input(request)
        run_id = uuid4().hex
        attempts: list[ModelAttempt] = []
        decisions: list[CandidateDecision] = []
        resolver = ScopeValidator(self._catalog, self._config, request.trace, run_id)
        try:
            output = self._generate(request, run_id, attempts)
            if not output.context_sufficient:
                raise UnderstandingError(
                    "ambiguous_scope", "model requires clarification of context"
                )
            return self._validate(request, output, resolver, decisions, attempts)
        except UnderstandingError as exc:
            for decision in decisions:
                if decision.status != "ignored":
                    decision.status = "rejected"
                    decision.reason = f"validation_aborted:{exc.code}"
            exc.decisions = tuple(item.model_copy(deep=True) for item in decisions)
            exc.attempts = tuple(item.model_copy(deep=True) for item in attempts)
            exc.catalog_matches = tuple(item.model_copy(deep=True) for item in resolver.matches)
            raise

    def _check_input(self, request: QueryRequest) -> None:
        config = self._config
        if (
            not request.question.strip()
            or len(request.question) > config.max_question_chars
            or len(request.history) > config.max_history_turns
            or sum(len(item.content) for item in request.history) > config.max_history_chars
            or any(not item.content.strip() for item in request.history)
        ):
            raise UnderstandingError(
                "input_budget", "question/history is blank or exceeds its budget"
            )
        for field in ("document_ids", "standard_codes", "editions", "clause_numbers"):
            if any(not value.strip() for value in getattr(request.filters, field)):
                raise UnderstandingError("invalid_evidence", "caller filter contains a blank value")
        if any(
            isinstance(values := getattr(request.filters, field), list)
            and len(values) > config.max_filter_values
            for field in type(request.filters).model_fields
        ):
            raise UnderstandingError("input_budget", "caller filter list exceeds its budget")
        if any(not CLAUSE_NUMBER.fullmatch(value) for value in request.filters.clause_numbers):
            raise UnderstandingError("invalid_evidence", "caller clause number format is invalid")

    def _generate(
        self, request: QueryRequest, run_id: str, attempts: list[ModelAttempt]
    ) -> UnderstandingOutput:
        previous_error: ErrorCode | None = None
        for index in range(self._config.max_attempts):
            llm_request = StructuredLLMRequest(
                request_id=f"{run_id}-llm-{index}",
                stage="query_understanding",
                input={
                    "instructions": INSTRUCTIONS,
                    "prompt_version": PROMPT_VERSION,
                    "question": request.question,
                    "history": [item.model_dump(mode="json") for item in request.history],
                    "caller_filters": request.filters.model_dump(mode="json"),
                    "previous_error": previous_error,
                },
                output_schema=UnderstandingOutput.model_json_schema(),
                config=self._config.llm.model_copy(deep=True),
                trace=request.trace,
            )
            started = monotonic()
            usage = None
            try:
                response = self._llm.generate(llm_request.model_copy(deep=True))
                parsed = response.validate_output(llm_request, UnderstandingOutput)
                usage = response.usage
            except (ValidationError, ValueError) as exc:
                code: ErrorCode = "invalid_output"
                failure: Exception = exc
                retry = True
            except Exception as exc:
                code, failure = "model_failure", exc
                retry = isinstance(exc, (TimeoutError, ConnectionError))
            else:
                attempts.append(
                    ModelAttempt(
                        request_id=llm_request.request_id,
                        status="success",
                        elapsed_seconds=monotonic() - started,
                        usage=usage,
                    )
                )
                return parsed
            attempts.append(
                ModelAttempt(
                    request_id=llm_request.request_id,
                    status=code,
                    elapsed_seconds=monotonic() - started,
                    usage=usage,
                )
            )
            if not retry or index + 1 == self._config.max_attempts:
                raise UnderstandingError(code, "Understanding model attempt failed") from failure
            previous_error = code
        raise AssertionError("positive attempt budget was not enforced")

    def _review_candidates(
        self,
        request: QueryRequest,
        output: UnderstandingOutput,
        decisions: list[CandidateDecision],
    ) -> tuple[list[StandardCandidate], SearchFilters, bool]:
        current_standards: list[StandardCandidate] = []
        candidates: list[
            tuple[str, StandardCandidate | TextCandidate | ContentTypeCandidate | BooleanCandidate]
        ] = [(f"standards[{index}]", item) for index, item in enumerate(output.standards)]
        candidates.extend(
            (f"clause_numbers[{index}]", item) for index, item in enumerate(output.clause_numbers)
        )
        candidates.extend(
            (f"content_types[{index}]", item) for index, item in enumerate(output.content_types)
        )
        candidates.extend(
            (field, item)
            for field in ("is_explanation", "is_mandatory")
            if (item := getattr(output, field)) is not None
        )
        proposed = SearchFilters()
        historical_scope = False
        for key, candidate in candidates:
            decision = CandidateDecision(
                key=key, candidate=candidate, status="rejected", reason="validation_not_completed"
            )
            decisions.append(decision)
            if isinstance(candidate, StandardCandidate):
                for selector in candidate.selectors().values():
                    verify_text(selector, request)
                evidence = next(iter(candidate.selectors().values())).evidence
            else:
                evidence = candidate.evidence
                if isinstance(candidate, TextCandidate):
                    verify_text(candidate, request)
                    if not CLAUSE_NUMBER.fullmatch(candidate.value):
                        raise UnderstandingError(
                            "invalid_evidence", "candidate clause format is invalid"
                        )
                elif isinstance(candidate, ContentTypeCandidate):
                    verify_content_type(candidate, request)
                else:
                    verify_boolean(key, candidate, request)
            if evidence.source != "question":
                decision.status = "ignored"
                decision.reason = "history_not_confirmed_in_current_question"
                historical_scope |= isinstance(candidate, StandardCandidate)
                continue
            if isinstance(candidate, StandardCandidate):
                current_standards.append(candidate)
                decision.reason = "awaiting_catalog"
            else:
                field = key.split("[")[0]
                if isinstance(getattr(proposed, field), list):
                    getattr(proposed, field).append(candidate.value)
                else:
                    setattr(proposed, field, candidate.value)
                decision.status = "adopted"
                decision.reason = "current_user_evidence"
        return current_standards, proposed, historical_scope

    def _validate(
        self,
        request: QueryRequest,
        output: UnderstandingOutput,
        resolver: ScopeValidator,
        decisions: list[CandidateDecision],
        attempts: list[ModelAttempt],
    ) -> UnderstandingResult:
        current_standards, proposed, historical_scope = self._review_candidates(
            request, output, decisions
        )
        handled = {
            code_key(item.standard_code.value)
            for item in current_standards
            if item.standard_code is not None
        }
        if any(
            code_key(match.group()) not in handled
            for match in STANDARD_CODE.finditer(request.question)
        ):
            raise UnderstandingError(
                "invalid_evidence", "explicit standard code was omitted by model"
            )
        if (
            historical_scope
            and not current_standards
            and not (request.filters.document_ids or request.filters.standard_codes)
        ):
            raise UnderstandingError(
                "ambiguous_scope", "historical standard requires current confirmation"
            )
        existing = resolver.validate_existing(request.filters)
        filters = request.filters.model_copy(deep=True)
        if existing:
            # Add only verified document IDs; do not gratuitously rewrite other caller fields.
            filters = merge_filters(
                filters,
                SearchFilters(
                    document_ids=[item.document_id for item in existing if item.document_id]
                ),
            )
        records: list[StandardMetadataRecord] = []
        for candidate in current_standards:
            selectors = {key: value.value for key, value in candidate.selectors().items()}
            scoped = [
                item
                for item in existing
                if all(
                    value in (item.standard.standard_name, *item.aliases)
                    if key == "standard_name"
                    else value == getattr(item.standard, key)
                    for key, value in selectors.items()
                )
            ]
            if len(scoped) == 1 and scoped[0].document_id is not None:
                # A previously catalog-verified caller scope may disambiguate an edition.
                selectors["document_id"] = scoped[0].document_id
            item = resolver.lookup(**selectors)
            assert item is not None
            records.append(item)
            decision = next(item for item in decisions if item.candidate is candidate)
            decision.document_ids = [item.document_id] if item.document_id else []
        if records:
            filters = merge_filters(filters, record_filters(restrict_records(records, filters)))
        filters = merge_filters(filters, proposed)
        if filters.clause_numbers and not filters.document_ids:
            raise UnderstandingError(
                "ambiguous_scope", "clause filter requires a verified document scope"
            )
        for decision in decisions:
            if decision.reason == "awaiting_catalog":
                if set(decision.document_ids) & set(filters.document_ids):
                    decision.status, decision.reason = "adopted", "catalog_verified"
                else:
                    decision.reason = "excluded_by_caller_scope"
            elif decision.status == "adopted":
                field = decision.key.split("[")[0]
                candidate = decision.candidate
                assert not isinstance(candidate, StandardCandidate)
                applied = getattr(filters, field)
                retained = (
                    candidate.value in applied
                    if isinstance(applied, list)
                    else (candidate.value == applied)
                )
                if not retained:
                    decision.status = "rejected"
                    decision.reason = "excluded_by_caller_scope"
        diagnostics = ["clause_existence_not_verified"] if filters.clause_numbers else []
        ignored = any(item.status != "adopted" for item in decisions)
        if ignored:
            diagnostics.append("some_candidates_not_adopted")
        if len(attempts) > 1:
            diagnostics.append("model_recovered_within_shared_budget")
        return UnderstandingResult(
            processing_intent=output.processing_intent,
            filters=filters,
            scope=self._config.scope.model_copy(deep=True),
            catalog_matches=resolver.matches,
            decisions=decisions,
            attempts=attempts,
            diagnostics=diagnostics,
            degraded=ignored or len(attempts) > 1,
            prompt_version=PROMPT_VERSION,
            model_config_id=self._config.llm.config_id,
            model_id=self._config.llm.model_id,
            model_revision=self._config.llm.model_revision,
        )
