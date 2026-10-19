"""Read-only, snapshot-bound Query golden data validation.

These are evaluation-private annotation models, not replacements for the
canonical Query, Chunk or retrieval contracts. A reviewer attestation records a
human decision; the loader cannot establish that the person actually reviewed it.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal, TypeVar

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from engineering_rag.contracts.chunks import Chunk, ChunkBatch
from engineering_rag.contracts.queries import (
    ConversationTurn,
    ProcessingIntent,
    QueryOptions,
    QueryRequest,
)
from engineering_rag.contracts.retrieval import SearchFilters

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
AnnotationStatus = Literal["draft", "pending", "verified", "disputed"]
DATASET_FILES = frozenset(
    {"queries.jsonl", "qrels.jsonl", "review_log.jsonl", "annotation_guidelines.md"}
)


class DatasetValidationError(ValueError):
    """An invalid target or annotation prevents trustworthy evaluation."""


class _AnnotationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class DatasetManifest(_AnnotationModel):
    schema_version: Literal["1.0"] = "1.0"
    dataset_id: Text
    dataset_version: Text
    description: Text
    created_at: AwareDatetime
    corpus_snapshot_id: Text
    corpus_sha256: Digest
    chunking_version: Text
    document_schema_version: Literal["2.4"]
    annotation_guidelines_version: Text
    query_count: Annotated[StrictInt, Field(ge=0)]
    qrels_count: Annotated[StrictInt, Field(ge=0)]
    files_sha256: dict[str, Digest]
    query_schema_version: Literal["2.0"] = "2.0"
    chunk_schema_version: Literal["1.0"] = "1.0"
    is_test_fixture: bool = False
    source_document_id: Text | None = None
    source_document_sha256: Digest | None = None
    source_pdf_sha256: Digest | None = None

    @field_validator("created_at")
    @classmethod
    def require_utc(cls, value: AwareDatetime) -> AwareDatetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("created_at must use UTC")
        return value

    @field_validator("files_sha256")
    @classmethod
    def exact_dataset_files(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) != DATASET_FILES:
            raise ValueError(f"files_sha256 must contain exactly {sorted(DATASET_FILES)}")
        return value


class ProtectedSpan(_AnnotationModel):
    start: Annotated[StrictInt, Field(ge=0)]
    end: Annotated[StrictInt, Field(gt=0)]
    text: Text
    kind: Text

    @model_validator(mode="after")
    def ordered(self) -> ProtectedSpan:
        if self.end <= self.start:
            raise ValueError("protected span uses a nonempty [start, end) interval")
        return self


class AnnotatedQuery(_AnnotationModel):
    query_id: Text
    query: Text
    history: list[ConversationTurn] = Field(default_factory=list)
    caller_filters: SearchFilters = Field(default_factory=SearchFilters)
    expected_outcome: Literal["retrieve", "reject"]
    expected_error_code: Text | None = None
    processing_intent: ProcessingIntent | None = None
    expected_filters: SearchFilters | None = None
    protected_spans: list[ProtectedSpan] = Field(default_factory=list)
    annotation_status: AnnotationStatus
    review_id: Text | None = None
    categories: list[Text] = Field(default_factory=list)
    notes: Text | None = None

    @model_validator(mode="after")
    def check_annotations(self) -> AnnotatedQuery:
        if self.expected_outcome == "reject":
            if self.expected_error_code is None:
                raise ValueError("reject query requires expected_error_code")
        elif self.expected_error_code is not None:
            raise ValueError("retrieve query cannot have expected_error_code")
        if self.annotation_status == "verified":
            if self.review_id is None:
                raise ValueError("verified query requires review_id")
            if self.expected_outcome == "retrieve" and (
                self.processing_intent is None or self.expected_filters is None
            ):
                raise ValueError("verified retrieve query requires intent and expected_filters")
        span_identities: set[tuple[int, int, str]] = set()
        for span in self.protected_spans:
            if span.end > len(self.query) or self.query[span.start : span.end] != span.text:
                raise ValueError("protected span does not match exact original query coordinates")
            identity = (span.start, span.end, span.kind)
            if identity in span_identities:
                raise ValueError("duplicate protected span (start, end, kind)")
            span_identities.add(identity)
        return self

    def to_request(self, *, top_k: int = 10) -> QueryRequest:
        """Build the real request without using human expected filters as input."""
        return QueryRequest(
            question=self.query,
            history=[turn.model_copy(deep=True) for turn in self.history],
            filters=self.caller_filters.model_copy(deep=True),
            options=QueryOptions(mode="hybrid", top_k=top_k),
        )


class Qrel(_AnnotationModel):
    query_id: Text
    chunk_id: Text
    relevance: Annotated[StrictInt, Field(ge=0, le=3)]
    annotation_status: AnnotationStatus
    review_id: Text | None = None

    @model_validator(mode="after")
    def require_review(self) -> Qrel:
        if self.annotation_status == "verified" and self.review_id is None:
            raise ValueError("verified qrel requires review_id")
        return self


class ReviewRecord(_AnnotationModel):
    review_id: Text
    query_id: Text
    chunk_id: Text | None = None
    reviewer: Text
    human_verified: Literal[True]
    reviewed_at: AwareDatetime
    decision: Literal["verified", "disputed"]
    rationale: Text

    @field_validator("human_verified", mode="before")
    @classmethod
    def explicit_boolean_attestation(cls, value: object) -> object:
        if value is not True:
            raise ValueError("human_verified must be the boolean true, not a generated label")
        return value


@dataclass(frozen=True)
class LoadedDataset:
    manifest: DatasetManifest
    queries: list[AnnotatedQuery]
    qrels: list[Qrel]
    chunks: dict[str, Chunk]
    corpus_sha256: str
    formal_ready: bool
    issues: list[str]
    batch: ChunkBatch
    corpus_path: Path

    @property
    def document_ids(self) -> list[str]:
        return [self.batch.document_id]


def _read_file(path: Path) -> bytes:
    """Reject links in any path component and do not follow a final symlink."""
    absolute = path.absolute()
    for component in (*reversed(absolute.parents), absolute):
        if component.is_symlink():
            raise DatasetValidationError(f"{path}: symbolic links are not allowed ({component})")
    try:
        descriptor = os.open(
            absolute,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise DatasetValidationError(f"{path}: expected a regular file")
            return stream.read()
    except OSError as exc:
        raise DatasetValidationError(f"{path}: cannot read dataset input: {exc.strerror}") from exc


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value}")


Model = TypeVar("Model", bound=BaseModel)


def safe_read_json(path: Path) -> object:
    """Read JSON without links, duplicate keys, non-finite numbers or mutations."""
    raw = _read_file(path)
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_no_duplicates,
            parse_constant=_reject_constant,
        )
    except (ValueError, TypeError) as exc:
        raise DatasetValidationError(f"{path}: invalid JSON: {exc}") from exc


def _parse_model(raw: bytes | str, model: type[Model], location: str) -> Model:
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        decoded = json.loads(
            text, object_pairs_hook=_no_duplicates, parse_constant=_reject_constant
        )
        # Strict JSON validation supports canonical Enum/date representations but
        # rejects coercion of strings, floats or booleans into annotation grades.
        return model.model_validate_json(
            json.dumps(decoded, ensure_ascii=False, allow_nan=False), strict=True
        )
    except (ValueError, TypeError) as exc:
        raise DatasetValidationError(f"{location}: invalid {model.__name__}: {exc}") from exc


def _jsonl(raw: bytes, model: type[Model], path: Path) -> list[Model]:
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise DatasetValidationError(f"{path}: expected UTF-8 JSONL") from exc
    records: list[Model] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise DatasetValidationError(f"{path}:{number}: blank JSONL row is not allowed")
        records.append(_parse_model(line, model, f"{path}:{number}"))
    return records


def _unique(records: list[Model], attribute: str, path: Path) -> dict[str, Model]:
    found: dict[str, Model] = {}
    for line, record in enumerate(records, start=1):
        identity = getattr(record, attribute)
        if identity in found:
            raise DatasetValidationError(f"{path}:{line}: duplicate {attribute}={identity!r}")
        found[identity] = record
    return found


def _check_review(
    record: AnnotatedQuery | Qrel,
    reviews: dict[str, ReviewRecord],
    location: str,
) -> None:
    if record.review_id is None:
        if record.annotation_status == "disputed":
            raise DatasetValidationError(f"{location}: disputed annotation requires review_id")
        return
    review = reviews.get(record.review_id)
    expected_chunk = record.chunk_id if isinstance(record, Qrel) else None
    if review is None:
        raise DatasetValidationError(f"{location}: missing review_id={record.review_id!r}")
    if (
        review.query_id != record.query_id
        or review.chunk_id != expected_chunk
        or review.decision != record.annotation_status
    ):
        raise DatasetValidationError(
            f"{location}: review identity/decision does not match annotation"
        )


def chunk_matches_filters(chunk: Chunk, filters: SearchFilters) -> bool:
    """Canonical OR-within/AND-across filters; unknown is not false.

    Qrels may include out-of-scope negative candidates, but a reviewed positive
    target cannot be counted as an attainable retrieval goal outside its scope.
    The same predicate can validate returned corpus Chunk identities in a run.
    """
    values = (
        (filters.document_ids, chunk.document_id),
        (filters.standard_codes, chunk.standard.standard_code),
        (filters.editions, chunk.standard.edition),
        (filters.clause_numbers, chunk.clause_number),
        (filters.content_types, chunk.content_type),
    )
    if any(allowed and value not in allowed for allowed, value in values):
        return False
    if filters.is_explanation is not None and chunk.is_explanation is not filters.is_explanation:
        return False
    return filters.is_mandatory is None or chunk.is_mandatory is filters.is_mandatory


def _validate_relations(
    dataset_dir: Path,
    queries: list[AnnotatedQuery],
    qrels: list[Qrel],
    reviews: list[ReviewRecord],
    chunks: dict[str, Chunk],
) -> list[str]:
    query_map = _unique(queries, "query_id", dataset_dir / "queries.jsonl")
    review_map = _unique(reviews, "review_id", dataset_dir / "review_log.jsonl")
    pairs: set[tuple[str, str]] = set()
    grouped: dict[str, list[Qrel]] = {query.query_id: [] for query in queries}
    for line, qrel in enumerate(qrels, start=1):
        location = f"{dataset_dir / 'qrels.jsonl'}:{line} ({qrel.query_id}, {qrel.chunk_id})"
        if qrel.query_id not in query_map:
            raise DatasetValidationError(f"{location}: unknown query_id")
        if qrel.chunk_id not in chunks:
            raise DatasetValidationError(f"{location}: chunk_id absent from target corpus snapshot")
        if query_map[qrel.query_id].expected_outcome == "reject":
            raise DatasetValidationError(f"{location}: reject query must not have qrels")
        expected = query_map[qrel.query_id].expected_filters
        if (
            qrel.relevance > 0
            and expected is not None
            and not chunk_matches_filters(chunks[qrel.chunk_id], expected)
        ):
            raise DatasetValidationError(f"{location}: positive qrel violates expected_filters")
        pair = (qrel.query_id, qrel.chunk_id)
        if pair in pairs:
            raise DatasetValidationError(f"{location}: duplicate qrel pair")
        pairs.add(pair)
        grouped[qrel.query_id].append(qrel)
        _check_review(qrel, review_map, location)
    for line, review in enumerate(reviews, start=1):
        location = f"{dataset_dir / 'review_log.jsonl'}:{line} ({review.review_id})"
        if review.query_id not in query_map:
            raise DatasetValidationError(f"{location}: unknown query_id")
        if review.chunk_id is not None and (review.query_id, review.chunk_id) not in pairs:
            raise DatasetValidationError(f"{location}: review targets no existing qrel")
    issues = [] if queries else ["empty_dataset"]
    for line, query in enumerate(queries, start=1):
        location = f"{dataset_dir / 'queries.jsonl'}:{line} ({query.query_id})"
        _check_review(query, review_map, location)
        if query.annotation_status != "verified":
            issues.append(f"unverified_query:{query.query_id}")
        if query.expected_outcome == "retrieve":
            if not grouped[query.query_id]:
                issues.append(f"missing_qrels:{query.query_id}")
            elif not any(
                qrel.relevance >= 2 and qrel.annotation_status == "verified"
                for qrel in grouped[query.query_id]
            ):
                issues.append(f"no_verified_relevant_targets:{query.query_id}")
    issues.extend(
        f"unverified_qrel:{qrel.query_id}:{qrel.chunk_id}"
        for qrel in qrels
        if qrel.annotation_status != "verified"
    )
    return issues


def load_dataset(
    dataset_dir: Path,
    *,
    corpus_path: Path,
    snapshot_id: str,
    formal: bool = False,
) -> LoadedDataset:
    """Validate a fixed ChunkBatch and annotations without altering any input.

    Non-formal loading may inspect a pending/empty dataset, but all identities,
    bytes, references and existing review attestations must still be valid.
    Formal loading additionally requires reviewed query/qrel labels and at least
    one reviewed relevance >= 2 target per retrieval query.
    """
    manifest_path = dataset_dir / "manifest.json"
    manifest = _parse_model(_read_file(manifest_path), DatasetManifest, str(manifest_path))
    if snapshot_id != manifest.corpus_snapshot_id:
        raise DatasetValidationError(
            f"{manifest_path}: corpus_snapshot_id mismatch: {snapshot_id!r} != "
            f"{manifest.corpus_snapshot_id!r}"
        )
    corpus_bytes = _read_file(corpus_path)
    corpus_sha256 = hashlib.sha256(corpus_bytes).hexdigest()
    if corpus_sha256 != manifest.corpus_sha256:
        raise DatasetValidationError(f"{corpus_path}: corpus_sha256 mismatch against manifest")
    batch = _parse_model(corpus_bytes, ChunkBatch, str(corpus_path))
    if batch.schema_version != manifest.chunk_schema_version:
        raise DatasetValidationError(f"{corpus_path}: chunk_schema_version mismatch")
    if batch.chunking_version != manifest.chunking_version:
        raise DatasetValidationError(f"{corpus_path}: chunking_version mismatch against manifest")
    if manifest.source_document_id is not None and batch.document_id != manifest.source_document_id:
        raise DatasetValidationError(f"{corpus_path}: source_document_id mismatch against manifest")
    artifact = batch.source_document_artifact
    if artifact is not None and artifact.schema_version != manifest.document_schema_version:
        raise DatasetValidationError(f"{corpus_path}: source Document schema version mismatch")
    if (
        artifact is not None
        and manifest.source_document_sha256 is not None
        and artifact.sha256 != manifest.source_document_sha256
    ):
        raise DatasetValidationError(
            f"{corpus_path}: source Document SHA-256 mismatch against artifact"
        )
    files = {name: _read_file(dataset_dir / name) for name in sorted(DATASET_FILES)}
    for name, raw in files.items():
        if hashlib.sha256(raw).hexdigest() != manifest.files_sha256[name]:
            raise DatasetValidationError(f"{dataset_dir / name}: SHA-256 mismatch against manifest")
    try:
        if not files["annotation_guidelines.md"].decode("utf-8").strip():
            raise DatasetValidationError(
                f"{dataset_dir / 'annotation_guidelines.md'}: empty guidelines"
            )
    except UnicodeError as exc:
        raise DatasetValidationError("annotation_guidelines.md: expected UTF-8") from exc
    queries = _jsonl(files["queries.jsonl"], AnnotatedQuery, dataset_dir / "queries.jsonl")
    qrels = _jsonl(files["qrels.jsonl"], Qrel, dataset_dir / "qrels.jsonl")
    reviews = _jsonl(files["review_log.jsonl"], ReviewRecord, dataset_dir / "review_log.jsonl")
    if len(queries) != manifest.query_count or len(qrels) != manifest.qrels_count:
        raise DatasetValidationError(f"{manifest_path}: query_count/qrels_count do not match JSONL")
    chunks = {chunk.chunk_id: chunk for chunk in batch.chunks}
    issues = _validate_relations(dataset_dir, queries, qrels, reviews, chunks)
    if formal and issues:
        raise DatasetValidationError(f"{dataset_dir}: not eligible for formal evaluation: {issues}")
    return LoadedDataset(
        manifest=manifest,
        queries=queries,
        qrels=qrels,
        chunks=chunks,
        corpus_sha256=corpus_sha256,
        formal_ready=not issues,
        issues=issues,
        batch=batch,
        corpus_path=corpus_path.absolute(),
    )
