"""Fictitious catalog fixtures proving lookup statuses without a production data source."""

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.catalog import (
    CatalogIndexScope,
    StandardMetadataLookup,
    StandardMetadataMatch,
    StandardMetadataRecord,
)
from engineering_rag.contracts.protocols import StandardMetadataCatalog

SCOPE = CatalogIndexScope(keyword_index="fiction_keyword", vector_collection="fiction_vector")


def record(edition: str = "演示版A", *, indexed: bool = True) -> StandardMetadataRecord:
    return StandardMetadataRecord(
        record_id=f"fixture-{edition}",
        standard={
            "standard_code": "TEST 000-2026",
            "standard_name": "虚构测试标准",
            "edition": edition,
        },
        aliases=["虚构别名"],
        document_id=f"fixture-doc-{edition}" if indexed else None,
        indexed_scopes=[SCOPE] if indexed else [],
    )


class FixtureCatalog:
    """Exact matching only, exclusively for contract tests, never a production catalog."""

    def __init__(self, records: list[StandardMetadataRecord], *, available: bool = True) -> None:
        self.records = records
        self.available = available

    def lookup(self, request: StandardMetadataLookup) -> StandardMetadataMatch:
        if not self.available:
            return StandardMetadataMatch(
                request_id=request.request_id,
                catalog_id="fixture-catalog",
                is_test_fixture=True,
                status="unavailable",
                reason="test fixture unavailable",
            )
        matches = [
            item
            for item in self.records
            if request.scope in item.indexed_scopes
            and (
                request.standard_code is None
                or request.standard_code == item.standard.standard_code
            )
            and (
                request.standard_name is None
                or request.standard_name in [item.standard.standard_name, *item.aliases]
            )
            and (request.edition is None or request.edition == item.standard.edition)
            and (request.revision is None or request.revision == item.standard.revision)
            and (request.document_id is None or request.document_id == item.document_id)
        ]
        status = "not_found" if not matches else "unique" if len(matches) == 1 else "ambiguous"
        return StandardMetadataMatch(
            request_id=request.request_id,
            catalog_id="fixture-catalog",
            snapshot_id="fiction-snapshot-1",
            is_test_fixture=True,
            status=status,
            candidates=matches,
        ).validate_for(request)


def lookup(**kwargs: object) -> StandardMetadataLookup:
    return StandardMetadataLookup(
        request_id="fixture-lookup", scope=SCOPE, standard_code="TEST 000-2026", **kwargs
    )


def test_unique_ambiguous_not_found_unavailable_and_snapshot_identity() -> None:
    catalog: StandardMetadataCatalog = FixtureCatalog([record(), record("演示版B")])
    assert isinstance(catalog, StandardMetadataCatalog)
    ambiguous = catalog.lookup(lookup())
    assert ambiguous.status == "ambiguous"
    assert len(ambiguous.candidates) == 2
    assert ambiguous.snapshot_id == "fiction-snapshot-1"
    assert ambiguous.is_test_fixture is True
    unique = catalog.lookup(lookup(edition="演示版A"))
    assert unique.status == "unique"
    assert unique.candidates[0].document_id == "fixture-doc-演示版A"
    assert catalog.lookup(lookup(edition="不存在的测试版")).status == "not_found"
    unavailable = FixtureCatalog([], available=False).lookup(lookup())
    assert unavailable.status == "unavailable"
    assert unavailable.snapshot_id is None
    assert unavailable.reason is not None


def test_global_validity_is_not_equivalent_to_ingestion() -> None:
    global_record = record(indexed=False)
    assert global_record.standard.standard_code == "TEST 000-2026"
    result = FixtureCatalog([global_record]).lookup(lookup())
    assert result.status == "not_found"
    assert result.candidates == []


def test_alias_and_document_lookup_require_exact_trusted_mapping() -> None:
    catalog = FixtureCatalog([record()])
    by_alias = StandardMetadataLookup(request_id="alias", scope=SCOPE, standard_name="虚构别名")
    assert catalog.lookup(by_alias).status == "unique"
    assert catalog.lookup(lookup(document_id="LLM-invented-id")).status == "not_found"


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "unique", "candidates": []},
        {"status": "ambiguous", "candidates": [record()]},
        {"status": "unavailable", "candidates": [record()], "reason": "offline"},
        {"status": "not_found", "candidates": [record()]},
        {"snapshot_id": None},
        {"candidates": [record(), record()], "status": "ambiguous"},
        {"candidates": [record(indexed=False)]},
    ],
)
def test_inconsistent_catalog_responses_are_rejected(changes: dict[str, object]) -> None:
    data = {
        "request_id": "fixture-lookup",
        "catalog_id": "fixture-catalog",
        "snapshot_id": "fixture-snapshot",
        "is_test_fixture": True,
        "status": "unique",
        "candidates": [record()],
    }
    with pytest.raises(ValidationError):
        StandardMetadataMatch.model_validate({**data, **changes})


def test_cross_scope_response_and_wrong_request_are_rejected() -> None:
    response = FixtureCatalog([record()]).lookup(lookup())
    other = StandardMetadataLookup(
        request_id="fixture-lookup",
        scope=CatalogIndexScope(keyword_index="other", vector_collection="other"),
        standard_code="TEST 000-2026",
    )
    with pytest.raises(ValueError, match="scope"):
        response.validate_for(other)
    other.request_id = "wrong"
    with pytest.raises(ValueError, match="request_id"):
        response.validate_for(other)


def test_no_implicit_fixture_flag_or_clause_existence_promise() -> None:
    data = FixtureCatalog([record()]).lookup(lookup()).model_dump(mode="json")
    data.pop("is_test_fixture")
    with pytest.raises(ValidationError, match="is_test_fixture"):
        StandardMetadataMatch.model_validate(data)
    with pytest.raises(ValidationError, match="extra_forbidden"):
        StandardMetadataLookup.model_validate(
            {**lookup().model_dump(mode="json"), "clause_number": "1.2.3"}
        )
    with pytest.raises(ValidationError):
        StandardMetadataLookup(request_id="x", scope=SCOPE)


@pytest.mark.parametrize(
    "changes",
    [
        {"standard_code": "TEST WRONG"},
        {"edition": "wrong"},
        {"document_id": "invented"},
        {"standard_name": "untrusted alias"},
        {"revision": "unknown-revision"},
    ],
)
def test_response_binding_rejects_wrong_metadata_selectors(changes: dict[str, object]) -> None:
    response = FixtureCatalog([record()]).lookup(lookup())
    changed = StandardMetadataLookup.model_validate({**lookup().model_dump(mode="json"), **changes})
    with pytest.raises(ValueError, match="selectors|alias"):
        response.validate_for(changed)
