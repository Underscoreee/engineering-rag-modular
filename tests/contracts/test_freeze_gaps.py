"""Independent negative tests against Task 0.2 candidate.

These tests are intentionally expected to FAIL on the uploaded candidate. They
specify extra invariants proposed for remediation, not existing repository tests.
Run from repository root: PYTHONPATH=src python -m pytest -q /path/to/test_freeze_gaps.py
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.artifacts import ArtifactManifest, DocumentArtifact
from engineering_rag.contracts.documents import Document, derive_clause_plain_text


def _repo_root() -> Path:
    for candidate in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "examples" / "document.example.json"
        ).is_file():
            return candidate
    raise RuntimeError("Run these regression tests inside the Engineering RAG project root")


EXAMPLES = _repo_root() / "examples"


def load(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def without_cache(clause):
    content = clause["clause_content"]
    content["plain_text"] = None
    content.pop("plain_text_renderer_version", None)
    content.pop("plain_text_source_digest", None)


def test_normative_clause_must_source_body_pages():
    obj = load("document.example.json")
    obj["pages"][0]["page_type"] = "explanation_body"
    with pytest.raises(ValidationError, match="page_type|normative|body"):
        Document.model_validate(obj)


def test_complete_ocr_must_not_contain_nonprocessed_block():
    obj = load("document.example.json")
    obj["pages"][0]["blocks"][0]["recognition_status"] = "not_processed"
    obj["pages"][0]["blocks"][0]["ocr"] = None
    without_cache(obj["clauses"]["normative"][0])
    with pytest.raises(ValidationError, match="complete|not_processed|OCR"):
        Document.model_validate(obj)


def test_clause_plain_text_contains_formula_symbol_explanations():
    doc = Document.model_validate(load("document.example.json"))
    clause = doc.clauses.normative[0]
    rendered = derive_clause_plain_text(doc, clause)
    assert rendered is not None
    assert "虚构量" in rendered[0], (
        "The FormulaGroup has a symbol explanation that vanished in plain_text"
    )


def test_manifest_parser_version_matches_document():
    doc = Document.model_validate(load("document.partial.example.json"))
    manifest_data = load("artifact_manifest.example.json")
    assert manifest_data["parser_version"] == doc.processing.parser_version
    manifest_data["parser_version"] = "conflicting-parser-version"
    manifest = ArtifactManifest.model_validate(manifest_data)
    with pytest.raises(ValidationError, match="parser_version"):
        DocumentArtifact(manifest=manifest, document=doc)


def test_manifest_asset_declared_digest_and_size_match_document():
    obj = load("document.partial.example.json")
    for page in obj["pages"]:
        for block in page["blocks"]:
            if block.get("asset"):
                block["asset"]["sha256"] = "c" * 64
                block["asset"]["size_bytes"] = 3
    doc = Document.model_validate(obj)
    manifest = ArtifactManifest.model_validate(load("artifact_manifest.example.json"))
    with pytest.raises(ValidationError, match="sha256|size_bytes|digest"):
        DocumentArtifact(manifest=manifest, document=doc)


def test_section_structure_path_consistent_with_number():
    obj = load("document.example.json")
    obj["sections"][0]["structure_path"] = ["999"]
    obj["sections"][1]["structure_path"] = ["999", "4.2"]
    with pytest.raises(ValidationError, match="structure_path|section"):
        Document.model_validate(obj)
