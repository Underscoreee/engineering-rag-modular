"""Actual Query stages + actual Hybrid, injected offline LLM/catalog/retrieval doubles.

This verifies module composition, NOT Elasticsearch, Milvus, real LLM or relevance quality.
"""

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.llm import (
    StructuredLLMConfig,
    StructuredLLMRequest,
    StructuredLLMResponse,
)
from engineering_rag.contracts.queries import QueryRequest
from engineering_rag.contracts.retrieval import (
    FusionStrategy,
    KeywordSearchRequest,
    RetrievalResult,
    RetrievalSource,
    VectorSearchRequest,
)
from engineering_rag.modules.hybrid_retrieval.api import create_hybrid_retrieval_service
from engineering_rag.modules.query.api import (
    EnhancementConfig,
    EquivalentTerm,
    PlanningConfig,
    QueryConfig,
    RewriteConfig,
    UnderstandingConfig,
    create_query_service,
)
from engineering_rag.modules.query.internal.errors import UnderstandingError

from .test_enhancement import CONTEXTS, QUESTION, expanded, hypothesis
from .test_planning import FakeHybrid, retrieval_result
from .test_understanding import CODE_A, SCOPE, FixtureCatalog, output, record, standard, value


class RoutingLLM:
    def __init__(self, question=QUESTION, intent="exploratory", **payloads):
        self.requests: list[StructuredLLMRequest] = []
        self.payloads = {
            "query_understanding": output(intent),
            "query_rewrite": dict(rewritten_query=question, keyword_synonyms=[]),
            "query_expansion": dict(expanded_queries=[expanded(question)]),
            "query_hyde": dict(hypothetical_document=hypothesis(question)),
            **payloads,
        }

    def generate(self, request: StructuredLLMRequest) -> StructuredLLMResponse:
        self.requests.append(request.model_copy(deep=True))
        payload = self.payloads[request.stage]
        if isinstance(payload, Exception):
            raise payload
        return StructuredLLMResponse(
            request_id=request.request_id,
            model_id=request.config.model_id,
            model_revision=request.config.model_revision,
            data=deepcopy(payload),
        )


class FakeBackend:
    def __init__(self, results: list[RetrievalResult], error: Exception | None = None):
        self.requests: list[KeywordSearchRequest | VectorSearchRequest] = []
        self.results, self.error = results, error

    def search(self, request: KeywordSearchRequest | VectorSearchRequest) -> list[RetrievalResult]:
        self.requests.append(request.model_copy(deep=True))
        if self.error:
            raise self.error
        return [item.model_copy(deep=True) for item in self.results]


def config(**planning) -> QueryConfig:
    llm = StructuredLLMConfig(
        config_id="offline",
        model_id="fixture-model",
        model_revision="fixture-v1",
        timeout_seconds=2,
        max_output_tokens=2048,
    )
    return QueryConfig(
        understanding=UnderstandingConfig(
            llm=llm, scope=SCOPE.model_copy(deep=True), allow_test_catalog=True
        ),
        rewrite=RewriteConfig(llm=llm),
        enhancement=EnhancementConfig(expansion_llm=llm, hyde_llm=llm, related_contexts=CONTEXTS),
        planning=PlanningConfig(scope=SCOPE.model_copy(deep=True), **planning),
    )


@pytest.mark.parametrize("intent", ["acquisition", "exploratory"])
@pytest.mark.parametrize("strategy", list(FusionStrategy))
def test_actual_stage_pipeline_and_hybrid_public_api_offline(intent, strategy):
    keyword = FakeBackend(
        [
            retrieval_result("shared", RetrievalSource.KEYWORD, 6.0),
            retrieval_result("keyword-only", RetrievalSource.KEYWORD, 3.0, 2),
        ]
    )
    vector = FakeBackend(
        [
            retrieval_result("shared", RetrievalSource.VECTOR, 0.9),
            retrieval_result("vector-only", RetrievalSource.VECTOR, 0.8, 2),
        ]
    )
    llm, catalog = RoutingLLM(intent=intent), FixtureCatalog()
    query = create_query_service(
        llm=llm,
        catalog=catalog,
        hybrid_service=create_hybrid_retrieval_service(keyword, vector),
        config=config(fusion_strategy=strategy),
    )
    request = QueryRequest(question=QUESTION)
    request.options.top_k = 2
    result = query.execute(request)
    stages = ["query_understanding", "query_rewrite"]
    if intent == "exploratory":
        stages.extend(["query_expansion", "query_hyde"])
    assert [item.stage for item in llm.requests] == stages
    assert len(keyword.requests) == len(vector.requests) == 1
    assert len(result.evidence) == 2
    assert result.evidence[0].chunk_id == "shared"
    assert all(item.retrieval_source == "hybrid" for item in result.evidence)
    assert [item.rank for item in result.evidence] == [1, 2]
    expected_score_type = (
        "rrf" if strategy == FusionStrategy.RECIPROCAL_RANK_FUSION else "min_max_weighted_sum"
    )
    assert all(item.score_type == expected_score_type for item in result.evidence)
    assert keyword.requests[0].top_k == vector.requests[0].top_k == 50
    assert keyword.requests[0].query == QUESTION
    assert vector.requests[0].query == (QUESTION if intent == "acquisition" else hypothesis())
    assert result.evidence[0].page_start == 3 and result.evidence[0].page_end == 4


def test_verified_standard_clause_negation_numbers_survive_both_queries_and_filters():
    question = f"比较{CODE_A}第1.2.3条在20 mm条件下不应采用的方法？"
    understanding = output("exploratory")
    understanding["standards"] = [standard(question)]
    understanding["clause_numbers"] = [value(question, "1.2.3")]
    llm, hybrid = RoutingLLM(question, query_understanding=understanding), FakeHybrid()
    query = create_query_service(
        llm=llm, catalog=FixtureCatalog(), hybrid_service=hybrid, config=config()
    )
    result = query.execute(QueryRequest(question=question))
    request = result.plan.hybrid_request
    for token in [CODE_A, "1.2.3", "20 mm", "不应"]:
        assert token in request.keyword.query and token in request.vector.query
    assert request.keyword.filters == request.vector.filters
    assert request.keyword.filters.document_ids == ["document-a"]
    assert request.keyword.filters.standard_codes == [CODE_A]
    assert request.keyword.filters.clause_numbers == ["1.2.3"]
    assert hybrid.requests == [request]


def test_only_reviewed_rewrite_synonyms_enter_keyword_not_hyde_or_expansion():
    question = "比较混凝土构件的设计要求？"
    cfg = config()
    cfg.rewrite.equivalent_terms = [
        EquivalentTerm(term="混凝土", equivalent="砼", evidence_id="fixture-review")
    ]
    llm = RoutingLLM(
        question, query_rewrite=dict(rewritten_query=question, keyword_synonyms=["砼", "未验证词"])
    )
    hybrid = FakeHybrid()
    query = create_query_service(
        llm=llm, catalog=FixtureCatalog(), hybrid_service=hybrid, config=cfg
    )
    result = query.execute(QueryRequest(question=question))
    assert result.plan.hybrid_request.keyword.query == question + "\n砼"
    assert result.plan.hybrid_request.vector.query == hypothesis(question)
    assert "砼" not in result.plan.hybrid_request.vector.query
    assert "未验证词" not in result.model_dump_json()


@pytest.mark.parametrize(
    ("expansion", "hyde", "expected"),
    [
        (dict(expanded_queries=[expanded()]), TimeoutError(), expanded()),
        (TimeoutError(), ConnectionError(), QUESTION),
    ],
)
def test_real_enhancement_failure_safely_falls_back_with_no_extra_calls(expansion, hyde, expected):
    llm = RoutingLLM(query_expansion=expansion, query_hyde=hyde)
    hybrid = FakeHybrid()
    query = create_query_service(
        llm=llm, catalog=FixtureCatalog(), hybrid_service=hybrid, config=config()
    )
    result = query.execute(QueryRequest(question=QUESTION))
    assert len(llm.requests) == 4 and len(hybrid.requests) == 1
    assert result.plan.hybrid_request.vector.query == expected
    assert result.evidence == []


@pytest.mark.parametrize("status", ["not_found", "ambiguous", "unavailable"])
def test_real_scope_validation_failure_stops_before_rewrite_or_search(status):
    question = f"查询{CODE_A}的要求？"
    und = output()
    und["standards"] = [standard(question)]
    catalog = FixtureCatalog(status=status)
    if status == "ambiguous":
        catalog.records.append(record(edition="2025", suffix="other"))
    llm, hybrid = RoutingLLM(question, query_understanding=und), FakeHybrid()
    query = create_query_service(llm=llm, catalog=catalog, hybrid_service=hybrid, config=config())
    with pytest.raises(UnderstandingError):
        query.execute(QueryRequest(question=question))
    assert [item.stage for item in llm.requests] == ["query_understanding"]
    assert hybrid.requests == []


def test_factory_rejects_mismatched_catalog_and_deployment_scope():
    cfg = config()
    payload = cfg.model_dump(mode="json")
    payload["planning"]["scope"]["keyword_index"] = "wrong-index"
    with pytest.raises(ValidationError, match="scope"):
        QueryConfig.model_validate_json(json.dumps(payload))


def test_factory_uses_independent_copies_of_caller_configuration():
    cfg, llm, hybrid = config(), RoutingLLM(), FakeHybrid()
    query = create_query_service(
        llm=llm, catalog=FixtureCatalog(), hybrid_service=hybrid, config=cfg
    )
    cfg.planning.scope.keyword_index = "later-mutated"
    cfg.enhancement.enable_hyde = False
    plan = query.plan(QueryRequest(question=QUESTION))
    assert plan.hybrid_request.keyword.index_name == SCOPE.keyword_index
    assert plan.hybrid_request.vector.query == hypothesis()


def test_actual_hybrid_backend_failure_is_not_an_empty_query_result():
    error = TimeoutError("offline injected vector timeout")
    keyword, vector = FakeBackend([]), FakeBackend([], error)
    query = create_query_service(
        llm=RoutingLLM(),
        catalog=FixtureCatalog(),
        hybrid_service=create_hybrid_retrieval_service(keyword, vector),
        config=config(),
    )
    with pytest.raises(TimeoutError) as caught:
        query.execute(QueryRequest(question=QUESTION))
    assert caught.value is error
    assert len(keyword.requests) == len(vector.requests) == 1
