"""Request-scoped citation mapping and literal quote checks, with no I/O."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from engineering_rag.contracts.answers import Citation
from engineering_rag.contracts.retrieval import RetrievalResult

from .context import GenerationContext, evidence_payload
from .models import GenerationError, GenerationOutput

_ASCII_WHITESPACE = re.compile(r"[ \t\r\n]+")
_QUOTE_TOKENS = re.compile(r"\\[A-Za-z]+|[+\-−]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+\-]?\d+)?")


def normalize_quote_whitespace(text: str) -> str:
    """Collapse ASCII whitespace runs to ONE space, never delete token boundaries.

    No Unicode, punctuation, sign, comparison, number, LaTeX or JSON decoding.
    Retain the original proposed quoted_text in the public Citation.
    """
    return _ASCII_WHITESPACE.sub(" ", text).strip(" \t\r\n")


def quote_is_present(quote: str, content: str) -> bool:
    if not quote.strip():
        return False
    normalized = normalize_quote_whitespace(quote)
    return bool(normalized) and (
        _literal_match(quote, content)
        or _literal_match(normalized, normalize_quote_whitespace(content))
    )


def _literal_match(quote: str, content: str) -> bool:
    """A substring must not truncate a number, sign or LaTeX command/escape run."""
    tokens = tuple(_QUOTE_TOKENS.finditer(content))
    start = content.find(quote)
    while start >= 0:
        end = start + len(quote)
        cuts_token = any(
            token.start() < start < token.end() or token.start() < end < token.end()
            for token in tokens
        )
        cuts_escape = start > 0 and quote.startswith("\\") and content[start - 1] == "\\"
        if not cuts_token and not cuts_escape:
            return True
        start = content.find(quote, start + 1)
    return False


def validate_registry(context: GenerationContext) -> None:
    """Recheck the SAME context registry against its actual serialized prompt rows.

    MappingProxyType protects keys, not mutable Pydantic values. Revalidation also
    catches corruption via model_copy/construct and same-chunk source ambiguity.
    No new evidence registry or guessed source is created.
    """
    rows = context.payload.get("evidence")
    if not isinstance(rows, list) or len(rows) != len(context.registry):
        raise GenerationError("invalid_registry")
    seen_ids: set[str] = set()
    seen_chunks: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("evidence_id"), str):
            raise GenerationError("invalid_registry")
        evidence_id = row["evidence_id"]
        if not evidence_id.strip() or evidence_id in seen_ids:
            raise GenerationError("invalid_registry")
        seen_ids.add(evidence_id)
        item = context.registry.get(evidence_id)
        if not isinstance(item, RetrievalResult):
            raise GenerationError("invalid_registry")
        try:
            validated = RetrievalResult.model_validate(
                item.model_dump(mode="python", warnings=False), strict=True
            )
        except (TypeError, ValueError):
            raise GenerationError("invalid_evidence") from None
        if not all(
            text.strip()
            for text in (
                validated.chunk_id,
                validated.document_id,
                validated.standard.standard_name,
                validated.standard.standard_code,
                validated.content,
            )
        ):
            raise GenerationError("invalid_evidence")
        if validated.chunk_id in seen_chunks:
            raise GenerationError("evidence_conflict")
        seen_chunks.add(validated.chunk_id)
        expected = evidence_payload(evidence_id, validated)
        try:
            actual_json = json.dumps(row, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError):
            raise GenerationError("invalid_registry") from None
        if actual_json != json.dumps(expected, sort_keys=True, allow_nan=False):
            raise GenerationError("source_metadata_conflict")
    if seen_ids != set(context.registry):
        raise GenerationError("invalid_registry")


@dataclass(frozen=True)
class CitationMapping:
    """Ordered bindings to the original context, not a second source registry."""

    context: GenerationContext
    evidence_ids: tuple[str, ...]
    citations: tuple[Citation, ...]


class CitationMapper:
    def map(self, output: GenerationOutput, context: GenerationContext) -> CitationMapping:
        validate_registry(context)
        try:
            output = GenerationOutput.model_validate(
                output.model_dump(mode="python", warnings=False), strict=True
            )
        except (TypeError, ValueError):
            raise GenerationError("invalid_output") from None
        ids = tuple(dict.fromkeys(output.evidence_ids))
        if any(evidence_id not in context.registry for evidence_id in ids):
            raise GenerationError("unknown_evidence_id")
        quotes: dict[str, str] = {}
        for proposed in output.quotes:
            if proposed.evidence_id not in context.registry:
                raise GenerationError("unknown_evidence_id")
            if proposed.evidence_id not in ids:
                raise GenerationError("orphan_quote")
            prior = quotes.get(proposed.evidence_id)
            if prior is not None and prior != proposed.quoted_text:
                raise GenerationError("quote_conflict")
            item = context.registry[proposed.evidence_id]
            if not quote_is_present(proposed.quoted_text, item.content):
                raise GenerationError("quote_mismatch")
            quotes[proposed.evidence_id] = proposed.quoted_text
        citations = tuple(
            Citation(
                citation_id=f"C{index}",
                evidence_chunk_id=item.chunk_id,
                document_id=item.document_id,
                clause_id=item.clause_id,
                page_start=item.page_start,
                page_end=item.page_end,
                quoted_text=quotes.get(evidence_id),
            )
            for index, evidence_id in enumerate(ids, 1)
            for item in (context.registry[evidence_id],)
        )
        return CitationMapping(context=context, evidence_ids=ids, citations=citations)
