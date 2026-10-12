"""Evidence-led page zoning for Chinese engineering standards."""

from __future__ import annotations

import re

from engineering_rag.contracts.documents import BlockType, Page, PageType

_CLAUSE_START = re.compile(r"^\s*\d+\.\d+\.\d+(?![-.\d])")
_HEADING_NUMBER = re.compile(r"^\s*(?P<number>\d+(?:\.\d+)?)\s*(?P<title>[\u4e00-\u9fff].+?)\s*$")
_CLAUSE_NUMBER = re.compile(r"^\s*(?P<number>\d+\.\d+\.\d+)(?![-.\d])")
_EXPLANATION_LANGUAGE = (
    "本次修订",
    "上一版规范",
    "原规范",
    "修订规范",
    "编制组",
)


def classify_pages(
    pages: list[Page], *, known_explanation_cover_page: int | None = None
) -> tuple[list[Page], dict[int, str]]:
    """Classify only pages supported by visible text and document-zone continuity."""

    classified: list[Page] = []
    reasons: dict[int, str] = {}
    explanation_zone = False
    previous_number: int | None = None
    previous_type = PageType.UNKNOWN
    for page in sorted(pages, key=lambda item: item.page_number):
        if (
            known_explanation_cover_page is not None
            and page.page_number > known_explanation_cover_page
        ):
            explanation_zone = True
        texts = [
            block.ocr.text.strip()
            for block in page.blocks
            if block.ocr is not None and block.ocr.text
        ]
        joined = "\n".join(texts)
        page_type = PageType.UNKNOWN
        reason = "insufficient_visible_zone_evidence"
        if "条文说明" in joined and "混凝土结构设计规范" in joined and len(joined) < 300:
            page_type = PageType.EXPLANATION_COVER
            reason = "standard_identity_and_explanation_cover_marker"
            explanation_zone = True
        elif "修订说明" in joined:
            page_type = PageType.REVISION_NOTES
            reason = "visible_revision_notes_heading"
        elif "本规范用词说明" in joined:
            page_type = PageType.WORDING_RULES
            reason = "visible_wording_rules_heading"
        elif "引用标准名录" in joined:
            page_type = PageType.NORMATIVE_REFERENCES
            reason = "visible_normative_references_heading"
        elif any(text.strip().lower() == "contents" for text in texts):
            page_type = PageType.TOC_EN
            reason = "visible_english_contents_heading"
        elif _looks_like_toc(texts):
            page_type = PageType.EXPLANATION_TOC if explanation_zone else PageType.TOC_ZH
            reason = "dense_heading_page_number_pairs"
        elif any(text.replace(" ", "") == "目次" for text in texts):
            page_type = PageType.EXPLANATION_TOC if explanation_zone else PageType.TOC_ZH
            reason = "visible_contents_heading"
        elif _looks_like_publication_notice(joined):
            page_type = PageType.PUBLICATION_NOTICE
            reason = "visible_ministry_announcement_heading"
        elif _looks_like_inner_cover(joined):
            page_type = PageType.INNER_COVER
            reason = "standard_identity_with_editor_approval_publisher_markers"
        elif _looks_like_outer_cover(joined):
            page_type = PageType.OUTER_COVER
            reason = "standard_identity_with_release_and_joint_publication_markers"
        elif explanation_zone and (
            _has_structural_candidate(texts) or previous_type == PageType.EXPLANATION_BODY
        ):
            page_type = PageType.EXPLANATION_BODY
            reason = "after_explanation_cover_with_clause_or_heading_evidence"
        elif _has_verified_normative_start(page, texts):
            page_type = PageType.BODY
            reason = "matched_title_clause_hierarchy_with_normative_page_evidence"
        elif previous_number is not None and page.page_number == previous_number + 1:
            if previous_type in {PageType.BODY, PageType.EXPLANATION_BODY} and texts:
                page_type = previous_type
                reason = "contiguous_nonempty_page_in_established_document_zone"
        classified.append(
            page.model_copy(
                update={
                    "page_type": page_type,
                    "page_type_basis": f"task1.5:{reason}",
                }
            )
        )
        reasons[page.page_number] = reason
        previous_number = page.page_number
        previous_type = page_type
    return classified, reasons


def _has_structural_candidate(texts: list[str]) -> bool:
    return any(_CLAUSE_START.match(text) or _HEADING_NUMBER.match(text) for text in texts)


def _has_verified_normative_start(page: Page, texts: list[str]) -> bool:
    """Require mutually supporting layout and hierarchy evidence for a new body zone."""

    if any(marker in text for marker in _EXPLANATION_LANGUAGE for text in texts):
        return False
    clause_numbers = [
        match.group("number") for text in texts if (match := _CLAUSE_NUMBER.match(text)) is not None
    ]
    if not clause_numbers:
        return False
    for block in page.blocks:
        if block.block_type != BlockType.TITLE or block.ocr is None or not block.ocr.text:
            continue
        heading = _HEADING_NUMBER.match(block.ocr.text)
        if heading is None or "\\" in block.ocr.text or "_{" in block.ocr.text.replace(" ", ""):
            continue
        number = heading.group("number")
        if not any(
            clause == number or clause.startswith(f"{number}.") for clause in clause_numbers
        ):
            continue
        if block.bbox.y_min > page.height * 0.35:
            continue
        return True
    return False


def _looks_like_toc(texts: list[str]) -> bool:
    if not any("目次" in text for text in texts):
        return False
    return sum(bool(re.search(r"\d+\s*$", text)) for text in texts) >= 2


def _looks_like_publication_notice(text: str) -> bool:
    return "公告" in text and "住房和城乡建设部" in text and "发布" in text


def _looks_like_inner_cover(text: str) -> bool:
    return (
        "混凝土结构设计规范" in text
        and "主编部门" in text
        and "批准部门" in text
        and "出版社" in text
    )


def _looks_like_outer_cover(text: str) -> bool:
    return (
        "混凝土结构设计规范" in text
        and "中华人民共和国国家标准" in text
        and "发布" in text
        and "实施" in text
        and "联合发布" in text
    )
