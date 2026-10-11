from copy import deepcopy

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.documents import Document, collect_document_diagnostics


def _disable_plain_text_cache(data: dict[str, object]) -> None:
    content = data["clauses"]["normative"][0]["clause_content"]
    content["plain_text"] = None
    content.pop("plain_text_renderer_version", None)
    content.pop("plain_text_source_digest", None)


def test_true_unknown_and_verified_false_states(document_data: dict[str, object]) -> None:
    document = Document.model_validate(document_data)
    assert document.clauses.normative[0].is_mandatory is True
    assert document.clauses.normative[1].is_mandatory is None
    data = deepcopy(document_data)
    evidence = data["clauses"]["normative"][0]["mandatory_evidence"][0]
    evidence["conclusion"] = False
    data["clauses"]["normative"][0]["is_mandatory"] = False
    assert Document.model_validate(data).clauses.normative[0].is_mandatory is False


def test_definite_state_rejects_pending_or_absent_evidence(
    document_data: dict[str, object],
) -> None:
    for evidence in (
        [],
        [
            {
                "evidence_id": "pending",
                "source_type": "reviewed_record",
                "verification_status": "pending",
                "conclusion": None,
            }
        ],
    ):
        data = deepcopy(document_data)
        data["clauses"]["normative"][0]["mandatory_evidence"] = evidence
        with pytest.raises(ValidationError, match="lacks verified evidence"):
            Document.model_validate(data)


def test_conflicting_verified_evidence_requires_unknown_and_is_diagnosed(
    document_data: dict[str, object],
) -> None:
    data = deepcopy(document_data)
    first = data["clauses"]["normative"][0]["mandatory_evidence"][0]
    second = deepcopy(first)
    second["evidence_id"] = "mandatory-evidence-conflict"
    second["conclusion"] = False
    data["clauses"]["normative"][0]["mandatory_evidence"].append(second)
    with pytest.raises(ValidationError, match="conflicting evidence"):
        Document.model_validate(data)
    data["clauses"]["normative"][0]["is_mandatory"] = None
    document = Document.model_validate(data)
    assert collect_document_diagnostics(document)[0].code.value == "conflict"


def test_verified_evidence_requires_location_and_utc(document_data: dict[str, object]) -> None:
    data = deepcopy(document_data)
    evidence = data["clauses"]["normative"][0]["mandatory_evidence"][0]
    evidence["source_document_id"] = None
    evidence["source_page"] = None
    with pytest.raises(ValidationError, match="document page or external URI"):
        Document.model_validate(data)
    data = deepcopy(document_data)
    data["clauses"]["normative"][0]["mandatory_evidence"][0]["verified_at"] = (
        "2026-01-01T08:00:00+08:00"
    )
    with pytest.raises(ValidationError, match="UTC"):
        Document.model_validate(data)
