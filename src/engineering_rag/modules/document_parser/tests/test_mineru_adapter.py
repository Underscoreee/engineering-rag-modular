"""Contract-focused tests for the private MinerU 4.x adapter boundary."""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from engineering_rag.contracts.common import FileRef
from engineering_rag.contracts.documents import (
    BlockType,
    FormulaNumberStatus,
    LogicalTableStatus,
    StandardMetadata,
)
from engineering_rag.modules.document_parser.internal.mineru.models import (
    MinerUElement,
    MinerUPage,
    MinerUParseResult,
)
from engineering_rag.modules.document_parser.internal.mineru.normalizer import (
    MinerUProtocolError,
    normalize_middle_json,
)
from engineering_rag.modules.document_parser.internal.mineru.runner import (
    MinerUExecutionError,
    safe_extract_zip,
)
from engineering_rag.modules.document_parser.internal.mineru.v24_adapter import adapt_to_v24
from engineering_rag.modules.document_parser.internal.parser import PyMuPdfDocumentParser
from engineering_rag.modules.document_parser.tests.support import make_text_pdf, request_for


def test_observed_middle_json_preserves_page_identity_and_payloads() -> None:
    payload = _middle_json()
    schema, version, producer, pages, diagnostics = normalize_middle_json(
        payload, expected_pages=[16]
    )
    assert (schema, version, producer) == ("docvortex.middle", "2.0", "4.0.12")
    assert diagnostics == []
    assert pages[0].page_number == 16
    assert [item.raw_type for item in pages[0].elements] == ["text", "equation", "table"]
    assert pages[0].elements[1].latex == r"x=y\tag{3.3.2-1}"
    assert pages[0].elements[2].table_html == "<table><tr><td>A</td></tr></table>"


def test_wrong_middle_json_version_is_rejected() -> None:
    payload = _middle_json()
    payload["schema_version"] = "3.0"
    with pytest.raises(MinerUProtocolError, match="unsupported MiddleJson"):
        normalize_middle_json(payload, expected_pages=[16])


def test_compacted_selected_pdf_page_maps_back_to_original_page() -> None:
    payload = _middle_json()
    payload["extensions"]["docvortex_layout"]["pages"][0]["page_idx"] = 0  # type: ignore[index]
    payload["pages"][0]["page_idx"] = 0  # type: ignore[index]
    _, _, _, pages, _ = normalize_middle_json(
        payload,
        expected_pages=[16],
        page_idx_to_original={0: 16},
    )
    assert pages[0].page_idx == 0
    assert pages[0].page_number == 16
    assert {item.page_number for item in pages[0].elements} == {16}


def test_v24_mapping_is_partial_traceable_and_does_not_invent_table_cells(
    tmp_path: Path,
) -> None:
    _, _, _, pages, _ = normalize_middle_json(_middle_json(), expected_pages=[16])
    result = MinerUParseResult(
        schema_id="docvortex.middle",
        schema_version="2.0",
        producer_version="4.0.12",
        tier="basic",
        parse_mode="ocr",
        source_sha256="a" * 64,
        pages=pages,
        raw_middle_json=tmp_path / "middle_json.json",
        stdout_log=tmp_path / "stdout.log",
        stderr_log=tmp_path / "stderr.log",
        elapsed_seconds=1,
    )
    adaptation = adapt_to_v24(
        result,
        source_file=FileRef(
            file_id="file-real-scan",
            uri="local.pdf",
            mime_type="application/pdf",
            sha256="a" * 64,
        ),
        standard=StandardMetadata(
            standard_name="本测试中的演示规范",
            standard_code="DEMO 1-2026",
            edition="演示版",
        ),
        page_count=20,
    )
    document = adaptation.document
    assert document.processing.partial is True
    assert document.sections == []
    assert document.clauses.normative == []
    assert document.pages[0].page_number == 16
    assert [block.block_type for block in document.pages[0].blocks] == [
        BlockType.BODY,
        BlockType.FORMULA,
        BlockType.TABLE,
    ]
    equation = document.pages[0].blocks[1].ocr.formula_group.equations[0]  # type: ignore[union-attr]
    assert equation.equation_number == "3.3.2-1"
    assert equation.equation_number_status == FormulaNumberStatus.PRINTED
    assert document.tables[0].extraction_status == LogicalTableStatus.STRUCTURE_ONLY
    assert document.tables[0].raw_grid is None and document.tables[0].data is None


def test_unnumbered_formula_has_unique_id_and_unknown_number_status(tmp_path: Path) -> None:
    page = MinerUPage(
        page_number=301,
        page_idx=300,
        width_points=400,
        height_points=600,
        elements=[
            MinerUElement(
                page_number=301,
                page_idx=300,
                source_index=2,
                raw_type="equation",
                bbox={"x_min": 0.1, "y_min": 0.2, "x_max": 0.9, "y_max": 0.3},
                latex=r"E_c=10^5/(2.2+34.7/f_{cu,k})",
                raw={"type": "equation"},
            )
        ],
    )
    result = _result(tmp_path, page)
    document = adapt_to_v24(
        result,
        source_file=FileRef(file_id="file", uri="local.pdf", mime_type="application/pdf"),
        standard=StandardMetadata(standard_name="演示", standard_code="DEMO"),
        page_count=441,
    ).document
    equation = document.pages[0].blocks[0].ocr.formula_group.equations[0]  # type: ignore[union-attr]
    assert equation.formula_id
    assert equation.equation_number is None
    assert equation.equation_number_status == FormulaNumberStatus.UNKNOWN


def test_zip_traversal_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape.txt", "not allowed")
    with pytest.raises(MinerUExecutionError, match="unsafe ZIP member"):
        safe_extract_zip(archive, tmp_path / "output")


def test_parser_mineru_path_returns_frozen_partial_document(tmp_path: Path) -> None:
    content = make_text_pdf(["first", "second"])
    store, request = request_for(
        content,
        pages="2",
        options={
            "document_engine": "mineru",
            "engine_output_dir": str(tmp_path),
            "mineru_tier": "basic",
        },
    )
    fake_adapter = _FakeAdapter(tmp_path)
    parser = PyMuPdfDocumentParser(store, mineru_adapter=fake_adapter)  # type: ignore[arg-type]
    document = parser.parse(request)
    assert document.schema_version == "2.4"
    assert document.page_count == 2
    assert document.pages[0].page_number == 2
    assert document.pages[0].blocks[0].ocr.text == "真实引擎候选"  # type: ignore[union-attr]
    assert document.processing.parser_id == "engineering_rag.document_parser.mineru"
    assert fake_adapter.requested_pages == [2]
    assert parser.last_mineru_result is not None


def _result(tmp_path: Path, page: MinerUPage) -> MinerUParseResult:
    return MinerUParseResult(
        schema_id="docvortex.middle",
        schema_version="2.0",
        producer_version="4.0.12",
        tier="basic",
        parse_mode="ocr",
        source_sha256="b" * 64,
        pages=[page],
        raw_middle_json=tmp_path / "middle.json",
        stdout_log=tmp_path / "stdout.log",
        stderr_log=tmp_path / "stderr.log",
        elapsed_seconds=1,
    )


class _FakeAdapter:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.requested_pages: list[int] = []

    def parse(self, request: object) -> MinerUParseResult:
        pages = request.original_pages
        self.requested_pages = list(pages)
        page_number = self.requested_pages[0]
        return _result(
            self.tmp_path,
            MinerUPage(
                page_number=page_number,
                page_idx=page_number - 1,
                width_points=360,
                height_points=240,
                elements=[
                    MinerUElement(
                        page_number=page_number,
                        page_idx=page_number - 1,
                        source_index=0,
                        raw_type="text",
                        bbox={"x_min": 0.1, "y_min": 0.1, "x_max": 0.8, "y_max": 0.2},
                        text="真实引擎候选",
                        raw={"type": "text"},
                    )
                ],
            ),
        )


def _middle_json() -> dict[str, object]:
    return json.loads(
        r"""{
          "schema": "docvortex.middle",
          "schema_version": "2.0",
          "metadata": {"producer": {"name": "mineru", "version": "4.0.12"}},
          "extensions": {
            "mineru": {"tier": "basic", "parse_mode": "ocr"},
            "docvortex_layout": {
              "version": 1,
              "pages": [{"page_idx": 15, "width_pt": 400, "height_pt": 600}]
            }
          },
          "pages": [{
            "page_idx": 15,
            "blocks": [
              {"index": 0, "type": "text", "bbox": [0.1, 0.1, 0.8, 0.2],
               "content": [{"type": "text", "content": "虚构条文"}]},
              {"index": 1, "type": "equation", "bbox": [0.2, 0.3, 0.7, 0.4],
               "content": "x=y\\tag{3.3.2-1}"},
              {"index": 2, "type": "table", "bbox": [0.1, 0.5, 0.9, 0.8],
               "content": [
                 {"type": "table_caption", "content": "演示表"},
                 {"type": "table_body",
                  "content": "<table><tr><td>A</td></tr></table>"},
                 {"type": "table_footnote", "content": "演示注"}
               ]}
            ]
          }]
        }"""
    )
