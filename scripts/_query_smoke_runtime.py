"""Small composition-root utilities; no alternate Query or retrieval implementation."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from engineering_rag.contracts.chunks import ChunkBatch
from engineering_rag.contracts.queries import QueryResult
from engineering_rag.contracts.retrieval import RetrievalResult, SearchFilters

CheckStatus = Literal["PASS", "FAIL", "NOT RUN", "BLOCKED"]
ENV_PREFIXES = ("ERAG_LLM_", "ENGINEERING_RAG_")
ENV_NAMES = {"ELASTICSEARCH_URL", "ELASTICSEARCH_API_KEY", "MILVUS_URI", "MILVUS_TOKEN"}
EVENT_FIELDS = (
    "stage",
    "status",
    "error_code",
    "elapsed_seconds",
    "processing_intent",
    "expansion_status",
    "hyde_status",
    "degraded",
    "vector_strategy",
    "candidate_k",
    "top_k",
    "result_count",
    "attempt_count",
    "prompt_version",
    "policy_fingerprint",
)


class SmokeError(RuntimeError):
    """Only safe, closed error codes are displayed by the CLI."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def load_env_file(path: Path, environ: Mapping[str, str]) -> dict[str, str]:
    """Explicit literal KEY=value loader; no sourcing, expansion, or credential scanning."""
    if path.is_symlink() or not path.is_file():
        raise SmokeError("env_file_missing_or_symlink")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
            raise SmokeError("invalid_env_assignment")
        if name not in ENV_NAMES and not name.startswith(ENV_PREFIXES):
            raise SmokeError("unsupported_env_variable")
        if name in values:
            raise SmokeError("duplicate_env_variable")
        if value[:1] in {"'", '"'}:
            if len(value) < 2 or value[-1] != value[0]:
                raise SmokeError("invalid_env_quote")
            value = value[1:-1]
        # Empty placeholders are not configuration. Existing process values win.
        values[name] = value
    return {**{key: value for key, value in values.items() if value}, **environ}


@contextmanager
def environment(values: Mapping[str, str]) -> Iterator[None]:
    """CLI-scoped environment for existing from_env factories; restore on every exit."""
    previous = dict(os.environ)
    os.environ.update(values)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


def read_corpus(path: Path) -> tuple[ChunkBatch, str]:
    if path.is_symlink() or not path.is_file():
        raise SmokeError("corpus_missing_or_symlink")
    raw = path.read_bytes()
    batch = ChunkBatch.model_validate_json(raw)
    if not batch.chunks:
        raise SmokeError("empty_corpus")
    return batch, hashlib.sha256(raw).hexdigest()


def safe_error_code(error: Exception) -> str:
    """Never print SDK messages, URLs, response bodies, headers or exception chains."""
    code = getattr(error, "code", None)
    if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code):
        return code
    return "runtime_failure"


def check(
    status: CheckStatus, *, code: str | None = None, details: object = None
) -> dict[str, object]:
    return {"status": status, "code": code, "details": details}


def assert_safe_text(text: str, secrets: list[str]) -> None:
    for secret in filter(None, secrets):
        # JSON escaping must not let a quoted/backslashed/non-ASCII key evade
        # the final output guard. Neither the raw value nor encodings are logged.
        variants = (
            secret,
            json.dumps(secret, ensure_ascii=False)[1:-1],
            json.dumps(secret, ensure_ascii=True)[1:-1],
        )
        if any(value in text for value in variants):
            raise SmokeError("sensitive_output_rejected")


def write_json(path: Path, data: object, secrets: list[str]) -> None:
    """Create a NEW artifact, never overwrite a historical smoke report."""
    text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    assert_safe_text(text, secrets)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(text)


class TraceEvents(logging.Handler):
    """Capture existing public logging events, not business-private stage objects.

    This single-request CLI restores logger state. Missing events stay missing;
    they are not inferred from unvalidated model candidates.
    """

    def __init__(self, trace_id: str) -> None:
        super().__init__(logging.INFO)
        self.trace_id = trace_id
        self.events: list[dict[str, object]] = []
        self.logger = logging.getLogger("engineering_rag.modules.query")

    def __enter__(self) -> TraceEvents:
        self.previous_level = self.logger.level
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(self)
        return self

    def __exit__(self, *args: object) -> None:
        self.logger.removeHandler(self)
        self.logger.setLevel(self.previous_level)
        self.close()

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "trace_id", None) == self.trace_id:
            self.events.append(
                {name: getattr(record, name) for name in EVENT_FIELDS if hasattr(record, name)}
            )


def validate_hits(hits: list[RetrievalResult], batch: ChunkBatch, filters: SearchFilters) -> None:
    """Bind returned evidence to the verified corpus without changing scores/content."""
    chunks = {chunk.chunk_id: chunk for chunk in batch.chunks}
    seen: set[str] = set()
    for rank, hit in enumerate(hits, 1):
        chunk = chunks.get(hit.chunk_id)
        if chunk is None or hit.chunk_id in seen or hit.rank != rank:
            raise SmokeError("invalid_hit_identity_or_rank")
        seen.add(hit.chunk_id)
        for field in (
            "logical_chunk_id",
            "document_id",
            "content",
            "standard",
            "clause_id",
            "clause_number",
            "page_start",
            "page_end",
        ):
            if getattr(hit, field) != getattr(chunk, field):
                raise SmokeError("hit_corpus_mismatch")
        for field, actual in (
            ("document_ids", chunk.document_id),
            ("standard_codes", chunk.standard.standard_code),
            ("editions", chunk.standard.edition),
            ("clause_numbers", chunk.clause_number),
            ("content_types", chunk.content_type),
        ):
            expected = getattr(filters, field)
            if expected and actual not in expected:
                raise SmokeError("hit_filter_mismatch")
        for field in ("is_explanation", "is_mandatory"):
            expected = getattr(filters, field)
            if expected is not None and expected != getattr(chunk, field):
                raise SmokeError("hit_filter_mismatch")


def result_summary(result: QueryResult, *, full_content: bool = False) -> dict[str, object]:
    request = result.plan.hybrid_request
    return {
        "original_question": result.plan.original_question,
        "processing_intent": result.plan.processing_intent.value,
        "rewritten_queries": result.plan.rewritten_queries,
        "keyword_query": request.keyword.query if request else None,
        "vector_query": request.vector.query if request else None,
        "filters": request.keyword.filters.model_dump(mode="json") if request else None,
        "hybrid_parameters": {
            "candidate_k": request.candidate_k,
            "top_k": request.top_k,
            "fusion_strategy": request.fusion_strategy.value,
            "keyword_weight": request.keyword_weight,
            "vector_weight": request.vector_weight,
        }
        if request
        else None,
        "result_count": len(result.evidence),
        "hits": [
            {
                **hit.model_dump(mode="json", exclude={"content"}),
                "content": hit.content if full_content else hit.content[:240],
            }
            for hit in result.evidence
        ],
        "source_note": "RetrievalResult has no source_refs/bbox; chunk IDs bind to the corpus",
    }
