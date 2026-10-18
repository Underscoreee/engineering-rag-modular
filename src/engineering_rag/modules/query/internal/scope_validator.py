"""Per-request catalog validation; never manufactures document identities."""

from engineering_rag.contracts.catalog import (
    StandardMetadataLookup,
    StandardMetadataMatch,
    StandardMetadataRecord,
)
from engineering_rag.contracts.common import TraceContext
from engineering_rag.contracts.protocols import StandardMetadataCatalog
from engineering_rag.contracts.retrieval import SearchFilters

from .config import UnderstandingConfig
from .errors import UnderstandingError
from .filter_merger import restrict_records


class ScopeValidator:
    def __init__(
        self,
        catalog: StandardMetadataCatalog,
        config: UnderstandingConfig,
        trace: TraceContext | None,
        run_id: str,
    ) -> None:
        self.catalog = catalog
        self.config = config
        self.trace = trace
        self.run_id = run_id
        self.matches: list[StandardMetadataMatch] = []

    def lookup(
        self, *, allow_missing: bool = False, **selectors: str
    ) -> StandardMetadataRecord | None:
        if len(self.matches) >= self.config.max_catalog_lookups:
            raise UnderstandingError("input_budget", "catalog lookup budget exceeded")
        request = StandardMetadataLookup(
            request_id=f"{self.run_id}-catalog-{len(self.matches)}",
            scope=self.config.scope.model_copy(deep=True),
            trace=self.trace,
            **selectors,
        )
        try:
            # Pass a copy so an adapter cannot change the selectors subsequently validated.
            match = self.catalog.lookup(request.model_copy(deep=True)).validate_for(request)
        except Exception as exc:
            raise UnderstandingError(
                "catalog_unavailable", "catalog lookup/binding failed"
            ) from exc
        self.matches.append(match)
        if match.is_test_fixture and not self.config.allow_test_catalog:
            raise UnderstandingError("catalog_unavailable", "test catalog is disabled")
        available = [item for item in self.matches if item.status != "unavailable"]
        if len({(item.catalog_id, item.snapshot_id) for item in available}) > 1:
            raise UnderstandingError(
                "catalog_unavailable", "catalog snapshot changed during validation"
            )
        if match.status == "unavailable":
            raise UnderstandingError("catalog_unavailable", "catalog declared unavailable")
        if match.status == "ambiguous":
            raise UnderstandingError("ambiguous_scope", "catalog scope requires disambiguation")
        if match.status == "not_found":
            if allow_missing:
                return None
            raise UnderstandingError("unmatched_scope", "explicit standard/document not found")
        return match.candidates[0]

    def validate_existing(self, filters: SearchFilters) -> list[StandardMetadataRecord]:
        """Resolve caller identities too; edition-only filters are not identity attestations."""
        records: list[StandardMetadataRecord] = []
        if filters.document_ids:
            for document_id in dict.fromkeys(filters.document_ids):
                item = self.lookup(document_id=document_id)
                assert item is not None
                records.append(item)
        elif filters.standard_codes:
            for code in dict.fromkeys(filters.standard_codes):
                selected: list[StandardMetadataRecord] = []
                for edition in dict.fromkeys(filters.editions or [None]):
                    selectors = {"standard_code": code}
                    if edition is not None:
                        selectors["edition"] = edition
                    item = self.lookup(allow_missing=bool(filters.editions), **selectors)
                    if item is not None:
                        selected.append(item)
                if not selected:
                    raise UnderstandingError(
                        "unmatched_scope", "caller standard/edition is not indexed"
                    )
                records.extend(selected)
            if filters.editions and not set(filters.editions).issubset(
                {item.standard.edition for item in records}
            ):
                raise UnderstandingError(
                    "unmatched_scope", "caller edition has no matching document"
                )
        return restrict_records(records, filters)
