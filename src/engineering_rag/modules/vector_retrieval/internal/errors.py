"""Vector retrieval implementation errors."""


class VectorRetrievalError(RuntimeError):
    """Base error for vector retrieval failures."""


class VectorConfigurationError(VectorRetrievalError):
    """Runtime configuration is missing or invalid."""


class VectorDependencyError(VectorRetrievalError):
    """An optional runtime dependency is unavailable."""


class EmbeddingModelError(VectorRetrievalError):
    """The embedding model could not be loaded or encode input."""


class InvalidEmbeddingError(VectorRetrievalError):
    """An embedding is empty, non-finite, or dimensionally invalid."""


class MilvusConnectionError(VectorRetrievalError):
    """Milvus could not be reached."""


class VectorTimeoutError(VectorRetrievalError):
    """A Milvus request exceeded its timeout."""


class CollectionNotFoundError(VectorRetrievalError):
    """The requested collection does not exist."""


class CollectionCompatibilityError(VectorRetrievalError):
    """An existing collection is incompatible with this service."""


class VectorBackendError(VectorRetrievalError):
    """Milvus rejected or failed an operation."""


class VectorResponseError(VectorRetrievalError):
    """A backend response cannot be converted safely."""
