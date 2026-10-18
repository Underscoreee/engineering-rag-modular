"""Stable query API exports."""

from engineering_rag.contracts.protocols import (
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

__all__ = [
    "ProcessingIntent",
    "QueryIntent",
    "QueryRequest",
    "QueryResult",
    "QueryService",
    "RetrievalPlan",
    "StandardMetadataCatalog",
    "StructuredLLMClient",
    "migrate_query_result_v1",
    "migrate_retrieval_plan_v1",
]
