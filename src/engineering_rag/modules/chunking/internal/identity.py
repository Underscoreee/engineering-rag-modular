"""Deterministic Chunk V1 identity helpers."""

import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

from engineering_rag.contracts.chunks import ChunkingConfig

CHUNKING_VERSION = "clause-first-1.0.0"


def config_digest(config: ChunkingConfig) -> str:
    payload = json.dumps(
        config.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{uuid5(NAMESPACE_URL, '|'.join(parts)).hex}"
