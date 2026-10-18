"""Snapshot-scoped standard metadata lookup contracts, without a production catalog."""

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr, TraceContext
from .documents import StandardMetadata


class CatalogIndexScope(ContractModel):
    """A declared pair of indexes containing a document at the catalog snapshot."""

    keyword_index: NonEmptyStr
    vector_collection: NonEmptyStr


class StandardMetadataRecord(ContractModel):
    record_id: NonEmptyStr
    standard: StandardMetadata
    aliases: list[NonEmptyStr] = Field(default_factory=list)
    document_id: NonEmptyStr | None = None
    indexed_scopes: list[CatalogIndexScope] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_indexed_identity(self) -> "StandardMetadataRecord":
        if self.indexed_scopes and self.document_id is None:
            raise ValueError("indexed records require a trusted document_id")
        scopes = [(scope.keyword_index, scope.vector_collection) for scope in self.indexed_scopes]
        if len(scopes) != len(set(scopes)):
            raise ValueError("indexed_scopes must be unique")
        return self


class StandardMetadataLookup(ContractModel):
    request_id: NonEmptyStr
    scope: CatalogIndexScope
    standard_code: NonEmptyStr | None = None
    standard_name: NonEmptyStr | None = None
    edition: NonEmptyStr | None = None
    revision: NonEmptyStr | None = None
    document_id: NonEmptyStr | None = None
    trace: TraceContext | None = None

    @model_validator(mode="after")
    def validate_selector(self) -> "StandardMetadataLookup":
        if not any((self.standard_code, self.standard_name, self.document_id)):
            raise ValueError("lookup requires standard_code, standard_name or explicit document_id")
        return self


class StandardMetadataMatchStatus(StrEnum):
    UNIQUE = "unique"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"


class StandardMetadataMatch(ContractModel):
    """Availability and candidates are declared by a trusted catalog adapter."""

    schema_version: Literal["1.0"] = "1.0"
    request_id: NonEmptyStr
    catalog_id: NonEmptyStr
    snapshot_id: NonEmptyStr | None = None
    is_test_fixture: bool
    status: StandardMetadataMatchStatus
    candidates: list[StandardMetadataRecord] = Field(default_factory=list)
    reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_status(self) -> "StandardMetadataMatch":
        size = len(self.candidates)
        if self.status == StandardMetadataMatchStatus.UNIQUE and size != 1:
            raise ValueError("unique match requires exactly one candidate")
        if self.status == StandardMetadataMatchStatus.AMBIGUOUS and size < 2:
            raise ValueError("ambiguous match requires at least two candidates")
        if (
            self.status
            in {
                StandardMetadataMatchStatus.NOT_FOUND,
                StandardMetadataMatchStatus.UNAVAILABLE,
            }
            and size
        ):
            raise ValueError("not_found/unavailable must not carry candidates")
        if self.status != StandardMetadataMatchStatus.UNAVAILABLE and self.snapshot_id is None:
            raise ValueError("available catalog results require snapshot_id")
        if self.status == StandardMetadataMatchStatus.UNAVAILABLE and self.reason is None:
            raise ValueError("unavailable catalog results require a reason")
        ids = [item.record_id for item in self.candidates]
        documents = [item.document_id for item in self.candidates]
        if len(ids) != len(set(ids)) or len(documents) != len(set(documents)):
            raise ValueError("catalog candidates must have unique record and document identities")
        if any(item.document_id is None or not item.indexed_scopes for item in self.candidates):
            raise ValueError("match candidates must identify indexed documents")
        return self

    def validate_for(self, request: StandardMetadataLookup) -> "StandardMetadataMatch":
        """Revalidate the response and bind it to the requested knowledge-base scope."""

        validated = type(self).model_validate_json(self.model_dump_json())
        if validated.request_id != request.request_id:
            raise ValueError("catalog response request_id mismatch")
        if any(request.scope not in item.indexed_scopes for item in validated.candidates):
            raise ValueError("catalog candidate is not indexed in the requested scope")
        for item in validated.candidates:
            checks = (
                (request.standard_code, item.standard.standard_code),
                (request.edition, item.standard.edition),
                (request.revision, item.standard.revision),
                (request.document_id, item.document_id),
            )
            if any(expected is not None and expected != actual for expected, actual in checks):
                raise ValueError("catalog candidate does not match the requested selectors")
            if request.standard_name is not None and request.standard_name not in (
                item.standard.standard_name,
                *item.aliases,
            ):
                raise ValueError("catalog candidate lacks an exact name or trusted alias mapping")
        return validated
