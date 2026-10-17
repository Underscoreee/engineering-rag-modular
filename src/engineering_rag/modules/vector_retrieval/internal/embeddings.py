"""Injectable embedding provider and lazy Sentence-Transformers adapter."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from .config import VectorRetrievalConfig
from .errors import EmbeddingModelError, InvalidEmbeddingError, VectorDependencyError


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def model_revision(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class SentenceTransformerEmbeddingProvider:
    """Lazy local adapter; one loaded model instance is reused for all calls."""

    def __init__(self, config: VectorRetrievalConfig) -> None:
        self._config = config
        self._model: object | None = None
        self._dimension: int | None = None

    @property
    def model_id(self) -> str:
        return self._config.embedding_model_id

    @property
    def model_revision(self) -> str:
        return self._config.embedding_model_revision

    @property
    def dimension(self) -> int:
        self._ensure_model()
        assert self._dimension is not None
        return self._dimension

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if any(not text.strip() for text in texts):
            raise InvalidEmbeddingError("document embedding text must not be blank")
        if not texts:
            return []
        return self._encode(list(texts))

    def embed_query(self, text: str) -> list[float]:
        if not text.strip():
            raise InvalidEmbeddingError("query text must not be blank")
        prefixed = (
            f"{self._config.query_instruction}{text}" if self._config.query_instruction else text
        )
        return self._encode([prefixed])[0]

    def _ensure_model(self) -> object:
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise VectorDependencyError(
                "sentence-transformers is required; install .[vector-retrieval]"
            ) from exc
        try:
            self._model = SentenceTransformer(
                self.model_id,
                revision=self.model_revision,
                device=self._config.embedding_device,
                cache_folder=(
                    str(self._config.embedding_cache_dir)
                    if self._config.embedding_cache_dir is not None
                    else None
                ),
                trust_remote_code=False,
            )
            dimension = self._model.get_sentence_embedding_dimension()  # type: ignore[attr-defined]
        except Exception as exc:
            raise EmbeddingModelError(f"failed to load embedding model {self.model_id!r}") from exc
        if not isinstance(dimension, int) or dimension <= 0:
            raise EmbeddingModelError("embedding model returned an invalid dimension")
        if (
            self._config.expected_dimension is not None
            and dimension != self._config.expected_dimension
        ):
            raise InvalidEmbeddingError(
                f"model dimension {dimension} differs from configured "
                f"{self._config.expected_dimension}"
            )
        self._dimension = dimension
        return self._model

    def _encode(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure_model()
        try:
            raw = model.encode(  # type: ignore[attr-defined]
                texts,
                batch_size=self._config.embedding_batch_size,
                normalize_embeddings=self._config.normalize_embeddings,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            vectors = raw.tolist()
        except Exception as exc:
            raise EmbeddingModelError("embedding model failed to encode input") from exc
        return validate_vectors(vectors, expected_count=len(texts), dimension=self.dimension)


def validate_vectors(
    vectors: Sequence[Sequence[float]], *, expected_count: int, dimension: int
) -> list[list[float]]:
    """Return Milvus-compatible floats after strict count/dimension/finite validation."""

    if len(vectors) != expected_count:
        raise InvalidEmbeddingError(
            f"embedding count {len(vectors)} differs from input count {expected_count}"
        )
    validated: list[list[float]] = []
    for position, vector in enumerate(vectors):
        if len(vector) != dimension:
            raise InvalidEmbeddingError(
                f"embedding {position} has dimension {len(vector)}; expected {dimension}"
            )
        converted = [float(value) for value in vector]
        if not converted or not all(math.isfinite(value) for value in converted):
            raise InvalidEmbeddingError(f"embedding {position} contains no finite vector")
        validated.append(converted)
    return validated
