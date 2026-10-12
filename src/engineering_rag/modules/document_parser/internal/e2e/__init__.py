"""Private Task 1.6 orchestration helpers; not part of the frozen contracts."""

from .checkpoint import CheckpointMismatchError, CheckpointStore
from .merge import DocumentMergeError, merge_documents
from .models import BatchPlan, BatchState, RunMode, RunState, SourceIdentity
from .planner import ensure_full_document_authorized, plan_batches
from .quality import build_candidate_records, evaluate_verified_records

__all__ = [
    "BatchPlan",
    "BatchState",
    "CheckpointMismatchError",
    "CheckpointStore",
    "DocumentMergeError",
    "RunMode",
    "RunState",
    "SourceIdentity",
    "build_candidate_records",
    "evaluate_verified_records",
    "ensure_full_document_authorized",
    "merge_documents",
    "plan_batches",
]
