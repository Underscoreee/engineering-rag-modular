"""Stable query API exports."""

from engineering_rag.contracts.protocols import (
    HybridRetrievalService,
    QueryService,
    StandardMetadataCatalog,
    StructuredLLMClient,
)
from engineering_rag.contracts.queries import (
    ProcessingIntent,
    QueryIntent,
    QueryRequest,
    QueryResult,
    RetrievalPlan,
)
from engineering_rag.contracts.query_migrations import (
    migrate_query_result_v1,
    migrate_retrieval_plan_v1,
)

from .internal.config import UnderstandingConfig
from .internal.enhancement import QueryEnhancement
from .internal.enhancement_models import EnhancementConfig, RelatedContext
from .internal.planning_models import PlanningConfig, QueryConfig, QueryPlanningError
from .internal.rewrite import QueryRewrite
from .internal.rewrite_models import EquivalentTerm, LanguageRule, RewriteConfig
from .internal.service import DefaultQueryService
from .internal.understanding import QueryUnderstanding


def create_query_service(
    *,
    llm: StructuredLLMClient,
    catalog: StandardMetadataCatalog,
    hybrid_service: HybridRetrievalService,
    config: QueryConfig,
) -> DefaultQueryService:
    """Compose the existing local stages; never create SDKs or own injected resources."""
    config = QueryConfig.model_validate_json(config.model_dump_json())
    return DefaultQueryService(
        understanding=QueryUnderstanding(llm=llm, catalog=catalog, config=config.understanding),
        rewrite=QueryRewrite(llm=llm, config=config.rewrite),
        enhancement=QueryEnhancement(llm=llm, config=config.enhancement),
        hybrid_service=hybrid_service,
        config=config.planning,
    )


__all__ = [
    "DefaultQueryService",
    "EnhancementConfig",
    "EquivalentTerm",
    "LanguageRule",
    "PlanningConfig",
    "ProcessingIntent",
    "QueryIntent",
    "QueryConfig",
    "QueryPlanningError",
    "QueryRequest",
    "QueryResult",
    "QueryService",
    "RetrievalPlan",
    "RelatedContext",
    "RewriteConfig",
    "StandardMetadataCatalog",
    "StructuredLLMClient",
    "UnderstandingConfig",
    "create_query_service",
    "migrate_query_result_v1",
    "migrate_retrieval_plan_v1",
]
