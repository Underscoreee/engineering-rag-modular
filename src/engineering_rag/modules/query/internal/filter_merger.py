"""Intersection preserves the public filters' OR-within / AND-across semantics."""

from collections.abc import Sequence

from engineering_rag.contracts.catalog import StandardMetadataRecord
from engineering_rag.contracts.retrieval import SearchFilters

from .errors import UnderstandingError


def merge_filters(original: SearchFilters, candidates: SearchFilters) -> SearchFilters:
    merged = original.model_dump(mode="python")
    for field in type(original).model_fields:
        old, new = getattr(original, field), getattr(candidates, field)
        if isinstance(old, list):
            if not new:
                continue
            values = list(dict.fromkeys(item for item in new if not old or item in old))
            if not values:
                raise UnderstandingError("scope_conflict", f"empty intersection for {field}")
            merged[field] = values
        elif new is not None:
            if old is not None and old != new:
                raise UnderstandingError("scope_conflict", f"contradictory {field}")
            merged[field] = new
    return SearchFilters.model_validate(merged)


def restrict_records(
    records: Sequence[StandardMetadataRecord], filters: SearchFilters
) -> list[StandardMetadataRecord]:
    selected = [
        item
        for item in records
        if (
            (not filters.document_ids or item.document_id in filters.document_ids)
            and (
                not filters.standard_codes or item.standard.standard_code in filters.standard_codes
            )
            and (not filters.editions or item.standard.edition in filters.editions)
        )
    ]
    if records and not selected:
        raise UnderstandingError("scope_conflict", "no catalog document satisfies the caller scope")
    return selected


def record_filters(records: Sequence[StandardMetadataRecord]) -> SearchFilters:
    return SearchFilters(
        document_ids=list(dict.fromkeys(item.document_id for item in records if item.document_id)),
        standard_codes=list(dict.fromkeys(item.standard.standard_code for item in records)),
        # Missing editions must not accidentally exclude matched documents.
        editions=list(dict.fromkeys(item.standard.edition for item in records))
        if records and all(item.standard.edition is not None for item in records)
        else [],
    )
