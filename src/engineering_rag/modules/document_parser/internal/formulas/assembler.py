"""Build conservative formula groups from observed MinerU 4.x elements."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from uuid import NAMESPACE_URL, uuid5

from engineering_rag.contracts.documents import (
    Equation,
    FormulaGroup,
    RecognitionStatus,
)
from engineering_rag.modules.document_parser.internal.mineru.models import (
    MinerUBbox,
    MinerUElement,
    MinerUParseResult,
)

from .models import (
    FormulaAssemblyResult,
    FormulaEquationCandidate,
    FormulaPlacement,
    FormulaSidecar,
)
from .number_matcher import evidence_from_latex, match_number
from .symbol_explanations import collect_symbol_explanations, is_symbol_start

FORMULA_ASSEMBLER_VERSION = "1.4.0"
MAX_LATEX_BYTES = 64 * 1024
MAX_FORMULAS_PER_PAGE = 128


def assemble_mineru_formulas(result: MinerUParseResult) -> FormulaAssemblyResult:
    placements: dict[tuple[int, int], FormulaPlacement] = {}
    consumed: set[tuple[int, int]] = set()
    sidecars: list[FormulaSidecar] = []
    omitted: list[dict[str, object]] = []
    for page in result.pages:
        formula_count = sum(element.raw_type == "equation" for element in page.elements)
        if formula_count > MAX_FORMULAS_PER_PAGE:
            omitted.append(
                {
                    "page_number": page.page_number,
                    "reason": "formula_candidate_limit_exceeded",
                    "count": formula_count,
                }
            )
            continue
        groups = _page_groups(page.elements)
        for indexes, symbol_start in groups:
            candidates: list[FormulaEquationCandidate] = []
            for position in indexes:
                element = page.elements[position]
                candidate, reason = _candidate(result, element)
                if candidate is None:
                    omitted.append(
                        {
                            "page_number": page.page_number,
                            "source_index": element.source_index,
                            "raw_type": "equation",
                            "reason": reason,
                        }
                    )
                else:
                    candidates.append(candidate)
            if not candidates:
                continue
            symbols = None
            symbol_evidence = None
            if symbol_start is not None:
                symbols, symbol_evidence, _ = collect_symbol_explanations(
                    page.elements, symbol_start
                )
            anchor = candidates[0]
            block_id = anchor.source_block_id
            group_id = _stable_id("formula-group", block_id)
            equations: list[Equation] = []
            group_diagnostics: list[str] = []
            for candidate in candidates:
                number, number_status, number_diagnostics = match_number(candidate.number_evidence)
                candidate.diagnostics.extend(number_diagnostics)
                equations.append(
                    Equation(
                        formula_id=candidate.formula_id,
                        equation_number=number,
                        equation_number_status=number_status,
                        latex=candidate.raw_latex,
                        text=None,
                        recognition_status=candidate.recognition_status,
                    )
                )
                group_diagnostics.extend(candidate.diagnostics)
            bbox = _union_bbox([candidate.bbox for candidate in candidates])
            recognition = (
                RecognitionStatus.NOT_TRANSCRIBED
                if all(
                    candidate.recognition_status == RecognitionStatus.NOT_TRANSCRIBED
                    for candidate in candidates
                )
                else RecognitionStatus.UNVERIFIED
            )
            placement = FormulaPlacement(
                block_id=block_id,
                formula_group_id=group_id,
                anchor_source_index=anchor.source_index,
                source_indices=[candidate.source_index for candidate in candidates],
                bbox=bbox,
                formula_group=FormulaGroup(
                    equations=equations,
                    symbol_explanations=symbols,
                ),
                recognition_status=recognition,
            )
            placements[(page.page_number, anchor.source_index)] = placement
            consumed.update((page.page_number, candidate.source_index) for candidate in candidates)
            sidecars.append(
                FormulaSidecar(
                    block_id=block_id,
                    formula_group_id=group_id,
                    page_number=page.page_number,
                    source_indices=placement.source_indices,
                    equations=candidates,
                    symbol_evidence=symbol_evidence,
                    grouping_basis=(
                        "shared_following_symbol_explanations"
                        if len(candidates) > 1 and symbols is not None
                        else "conservative_single_equation_group"
                    ),
                    diagnostics=list(dict.fromkeys(group_diagnostics)),
                )
            )
    return FormulaAssemblyResult(
        placements=placements,
        consumed=consumed,
        sidecars=sidecars,
        omitted=omitted,
    )


def _page_groups(elements: list[MinerUElement]) -> list[tuple[list[int], int | None]]:
    formula_positions = [
        position for position, element in enumerate(elements) if element.raw_type == "equation"
    ]
    claimed: set[int] = set()
    grouped: list[tuple[list[int], int | None]] = []
    for symbol_position, element in enumerate(elements):
        if not is_symbol_start(element):
            continue
        run: list[int] = []
        cursor = symbol_position - 1
        while cursor >= 0:
            if elements[cursor].raw_type == "equation":
                if cursor in claimed:
                    break
                run.append(cursor)
                cursor -= 1
                continue
            if run and _is_formula_connector(elements[cursor]):
                earlier = cursor - 1
                if earlier >= 0 and elements[earlier].raw_type == "equation":
                    cursor = earlier
                    continue
            break
        if run:
            ordered = sorted(run)
            claimed.update(ordered)
            grouped.append((ordered, symbol_position))
    grouped.extend(([position], None) for position in formula_positions if position not in claimed)
    return sorted(grouped, key=lambda item: item[0][0])


def _is_formula_connector(element: MinerUElement) -> bool:
    text = (element.text or "").strip()
    return element.raw_type == "text" and text.startswith("当") and text.endswith("时")


def _candidate(
    result: MinerUParseResult, element: MinerUElement
) -> tuple[FormulaEquationCandidate | None, str]:
    if element.bbox is None:
        return None, "missing_or_invalid_bbox"
    latex = element.latex
    if latex is not None and len(latex.encode("utf-8")) > MAX_LATEX_BYTES:
        return None, "latex_size_limit_exceeded"
    block_id = stable_formula_block_id(
        result.source_sha256, element.page_number, element.source_index
    )
    diagnostics = _latex_diagnostics(latex)
    number_evidence = evidence_from_latex(latex)
    if number_evidence and all(item.bbox is None for item in number_evidence):
        diagnostics.append(
            "printed number comes from the MinerU equation tag; "
            "no separate number bbox is available"
        )
    raw_asset_ref, source_asset_path, asset_diagnostics = _source_asset(result, element)
    diagnostics.extend(asset_diagnostics)
    return (
        FormulaEquationCandidate(
            page_number=element.page_number,
            source_index=element.source_index,
            source_block_id=block_id,
            formula_id=_stable_id("formula", block_id, "0"),
            raw_latex=latex,
            bbox=element.bbox,
            number_evidence=number_evidence,
            raw_asset_ref=raw_asset_ref,
            source_asset_path=source_asset_path,
            recognition_status=(
                RecognitionStatus.UNVERIFIED
                if latex is not None
                else RecognitionStatus.NOT_TRANSCRIBED
            ),
            diagnostics=diagnostics,
        ),
        "",
    )


def stable_formula_block_id(source_sha256: str, page_number: int, source_index: int) -> str:
    return _stable_id("block", source_sha256, str(page_number), str(source_index), "equation")


def _source_asset(
    result: MinerUParseResult, element: MinerUElement
) -> tuple[str | None, str | None, list[str]]:
    raw = element.raw.get("image_path")
    if raw is None:
        return None, None, ["formula has no source image reference"]
    if not isinstance(raw, str) or not raw:
        return str(raw), None, ["formula image reference is not a non-empty string"]
    reference = PurePosixPath(raw)
    if reference.is_absolute() or ".." in reference.parts or "://" in raw:
        return raw, None, ["rejected unsafe formula image path"]
    root = result.raw_middle_json.parent.resolve()
    candidate = (root / Path(*reference.parts)).resolve()
    if not candidate.is_relative_to(root):
        return raw, None, ["rejected formula image path outside raw bundle"]
    if not candidate.is_file():
        return raw, None, ["formula source image is missing"]
    if candidate.is_symlink():
        return raw, None, ["rejected formula image symlink"]
    return raw, str(candidate), []


def _latex_diagnostics(latex: str | None) -> list[str]:
    if latex is None:
        return ["formula image has no LaTeX transcription"]
    diagnostics: list[str] = []
    if latex.count("{") != latex.count("}"):
        diagnostics.append("unbalanced LaTeX braces retained without correction")
    if "O." in latex or "0O" in latex or "O0" in latex:
        diagnostics.append("possible O/0 OCR ambiguity retained without correction")
    if "l_" in latex or "1_" in latex:
        diagnostics.append("possible l/1 OCR ambiguity retained without correction")
    return diagnostics


def _union_bbox(values: list[MinerUBbox]) -> MinerUBbox:
    return MinerUBbox(
        x_min=min(item.x_min for item in values),
        y_min=min(item.y_min for item in values),
        x_max=max(item.x_max for item in values),
        y_max=max(item.y_max for item in values),
    )


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{uuid5(NAMESPACE_URL, '|'.join(parts)).hex}"
