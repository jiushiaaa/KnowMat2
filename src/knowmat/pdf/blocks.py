"""Block adaptation helpers for PaddleOCR-VL outputs."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .doi_extractor import DOI_URL_RE, extract_first_doi
from .html_cleaner import _has_complex_cell_attributes, convert_html_to_markdown, html_table_to_structured


def _get_block_attr(block: Any, name: str, default: Any = None) -> Any:
    if hasattr(block, name):
        return getattr(block, name)
    if isinstance(block, dict):
        return block.get(name, default)
    return default


_TABLE_LABELS = frozenset({"table", "chart"})
_IMAGE_LABELS = frozenset({"image", "figure", "seal", "figure_title"})
_FORMULA_LABELS = frozenset({"display_formula", "formula", "inline_formula"})

# PaddleOCR-VL sometimes prepends the rendered page image path (e.g. temp dir +
# source-page-0007.png when the working PDF stem is "source") and journal sidebar
# noise ("min" / "general") before real block text.
_PAGE_RENDER_PNG_FIRST_LINE_RE = re.compile(
    r"^[^\n]*[/\\][^\n]*-page-\d+\.png\s*$",
    re.IGNORECASE,
)
_VL_LEADING_SIDEBAR_LINES = frozenset({"min", "general"})


def strip_paddle_vl_block_artifacts(text: str) -> str:
    """Remove leading local page-PNG path and common sidebar OCR lines from VL block text."""
    if not text or not isinstance(text, str):
        return text
    lines = text.split("\n")
    i = 0
    if lines and _PAGE_RENDER_PNG_FIRST_LINE_RE.match(lines[0]):
        i = 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    while i < len(lines) and lines[i].strip().lower() in _VL_LEADING_SIDEBAR_LINES:
        i += 1
    return "\n".join(lines[i:]).lstrip("\n")


def sanitize_ocr_items_vl_artifacts(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Apply :func:`strip_paddle_vl_block_artifacts` to text fields in cached or legacy items."""
    for it in items:
        if not isinstance(it, dict):
            continue
        typer = it.get("typer")
        if typer == "paragraph":
            t = it.get("text")
            if isinstance(t, str):
                it["text"] = strip_paddle_vl_block_artifacts(t.strip())
        elif typer == "table":
            data = it.get("data")
            if isinstance(data, dict):
                raw = data.get("text")
                if isinstance(raw, str):
                    data["text"] = strip_paddle_vl_block_artifacts(raw.strip())
        elif typer == "formula":
            data = it.get("data")
            if isinstance(data, dict):
                for key in ("text", "latex"):
                    v = data.get(key)
                    if isinstance(v, str):
                        data[key] = strip_paddle_vl_block_artifacts(v.strip())
    return items

# Figure/Table caption patterns
# Matches: "Fig. 1. Description", "Figure 1.1: Description", "Fig.1 Description"
_FIGURE_CAPTION_RE = re.compile(
    r"^(Fig\.?|Figure)\s*(\d+(?:\.\d+)?)\.?\s*[:\uff1a]?\s*(.+)$",
    re.IGNORECASE
)
# Matches: "Table 1. Description", "Table 1: Description"
_TABLE_CAPTION_RE = re.compile(
    r"^(Table|Tab\.?)\s*(\d+(?:\.\d+)?)\.?\s*[:\uff1a]?\s*(.+)$",
    re.IGNORECASE
)
# Combined pattern for extracting captions from text
# Note: Uses greedy match to capture caption text up to the next period or end
_CAPTION_IN_TEXT_RE = re.compile(
    r"(Fig\.?|Figure|Table|Tab\.?)\s*(\d+(?:\.\d+)?)\.?\s*[:\uff1a]?\s*([A-Z][^.]*(?:\.|$))",
    re.IGNORECASE
)


def extract_figure_caption(text: str) -> Optional[Dict[str, Any]]:
    """Extract figure caption information from text.
    
    Parameters
    ----------
    text : str
        Text to parse for figure caption.
        
    Returns
    -------
    Optional[Dict[str, Any]]
        Dictionary with keys: figure_type, figure_num, caption.
        Returns None if no figure caption pattern is found.
        
    Examples
    --------
    >>> extract_figure_caption("Fig. 1. Microstructure of the alloy")
    {'figure_type': 'Fig.', 'figure_num': '1', 'caption': 'Microstructure of the alloy'}
    >>> extract_figure_caption("Figure 2.1: SEM image of precipitates")
    {'figure_type': 'Figure', 'figure_num': '2.1', 'caption': 'SEM image of precipitates'}
    """
    if not text:
        return None
    text = text.strip()
    match = _FIGURE_CAPTION_RE.match(text)
    if match:
        return {
            "figure_type": match.group(1),
            "figure_num": match.group(2),
            "caption": match.group(3).strip(),
        }
    return None


def extract_table_caption(text: str) -> Optional[Dict[str, Any]]:
    """Extract table caption information from text.
    
    Parameters
    ----------
    text : str
        Text to parse for table caption.
        
    Returns
    -------
    Optional[Dict[str, Any]]
        Dictionary with keys: table_type, table_num, caption.
        Returns None if no table caption pattern is found.
    """
    if not text:
        return None
    text = text.strip()
    match = _TABLE_CAPTION_RE.match(text)
    if match:
        return {
            "table_type": match.group(1),
            "table_num": match.group(2),
            "caption": match.group(3).strip(),
        }
    return None


def find_captions_in_text(text: str) -> List[Tuple[str, str, str, int, int]]:
    """Find all figure/table captions within a larger text block.
    
    Parameters
    ----------
    text : str
        Text to search for captions.
        
    Returns
    -------
    List[Tuple[str, str, str, int, int]]
        List of tuples: (type, number, caption, start_pos, end_pos)
    """
    results: List[Tuple[str, str, str, int, int]] = []
    for match in _CAPTION_IN_TEXT_RE.finditer(text):
        cap_type = match.group(1)
        cap_num = match.group(2)
        caption = match.group(3).strip()
        results.append((cap_type, cap_num, caption, match.start(), match.end()))
    return results


def _make_table_item(content: str, confidence: Any) -> Dict[str, Any]:
    """Create a table item with structured data and optional caption.
    
    For complex tables (with rowspan/colspan), raw_html is preserved
    because structured parsing loses cell merge information.
    """
    data: Dict[str, Any] = {}
    
    # 检测是否为复杂表格
    is_complex = _has_complex_cell_attributes(content)
    
    if is_complex:
        # 复杂表格：保留HTML，同时生成简化文本
        data["text"] = convert_html_to_markdown(content)
        data["raw_html"] = content
        data["is_complex_table"] = True
    else:
        # 简单表格：尝试结构化解析
        structured = html_table_to_structured(content)
        if structured:
            data = structured
        else:
            data["text"] = convert_html_to_markdown(content)
            data["raw_html"] = content
    
    # Try to extract table caption from the raw HTML or text
    if content:
        # Check first line of text for caption pattern
        first_line = convert_html_to_markdown(content).split('\n')[0] if content else ""
        caption_info = extract_table_caption(first_line)
        if caption_info:
            data["table_num"] = caption_info["table_num"]
            data["caption"] = caption_info["caption"]
            data["caption_type"] = caption_info["table_type"]
    
    item: Dict[str, Any] = {"typer": "table", "data": data}
    if confidence is not None:
        item["confidence"] = confidence
    return item


def _make_image_item(block: Any, content: str, confidence: Any) -> Dict[str, Any]:
    """Create an image item with extracted figure caption if available."""
    image_info = _get_block_attr(block, "image", None)
    image_path = image_info.get("path") if isinstance(image_info, dict) else None
    data: Dict[str, Any] = {"image_path": image_path}
    
    if content:
        # Try to extract figure caption using pattern matching
        caption_info = extract_figure_caption(content)
        if caption_info:
            data["figure_num"] = caption_info["figure_num"]
            data["caption"] = caption_info["caption"]
            data["caption_type"] = caption_info["figure_type"]
        else:
            md_text = convert_html_to_markdown(content)
            if len(md_text) > 300:
                # Long text is almost certainly body text that leaked into the image block,
                # not a caption. Keep it separate so consumers can distinguish.
                data["associated_text"] = md_text
            else:
                data["caption"] = md_text
    
    if confidence is not None:
        data["confidence"] = confidence
    return {"typer": "image", "data": data}


def _make_formula_item(block: Any, content: str, confidence: Any) -> Dict[str, Any]:
    latex_text = _get_block_attr(block, "latex", None) or content
    data: Dict[str, Any] = {
        "text": convert_html_to_markdown(content) if content else "",
        "latex": latex_text or "",
    }
    if confidence is not None:
        data["confidence"] = confidence
    return {"typer": "formula", "data": data}


def block_to_item(block: Any) -> Optional[Dict[str, Any]]:
    label = _get_block_attr(block, "label", None) or _get_block_attr(block, "block_label", None)
    content = (
        _get_block_attr(block, "block_content", "")
        or _get_block_attr(block, "content", "")
        or _get_block_attr(block, "text", "")
    )
    confidence = _get_block_attr(block, "score", None) or _get_block_attr(block, "confidence", None)
    if isinstance(content, str):
        content = content.strip()
        content = strip_paddle_vl_block_artifacts(content)

    if label in _TABLE_LABELS:
        return _make_table_item(content or "", confidence)
    if label in _IMAGE_LABELS:
        return _make_image_item(block, content, confidence)
    if label in _FORMULA_LABELS:
        return _make_formula_item(block, content, confidence)
    if content:
        item: Dict[str, Any] = {"typer": "paragraph", "text": convert_html_to_markdown(content)}
        if confidence is not None:
            item["confidence"] = confidence
        return item
    return None


def text_to_paragraph_items(text: str) -> List[Dict[str, Any]]:
    if not text:
        return []
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    return [{"typer": "paragraph", "text": block} for block in blocks]


# ---------------------------------------------------------------------------
# Semantic role classification
# ---------------------------------------------------------------------------

# Layout-noise block_labels that map directly to header/footer role
_LAYOUT_NOISE_LABELS = frozenset(
    {"header", "footer", "header_image", "footer_image", "aside_text", "number", "footnote"}
)

# Patterns for front-matter transitions
_ABSTRACT_HEADING_RE = re.compile(r"^(?:#+\s*)?abstract\s*$", re.IGNORECASE)
_INTRODUCTION_HEADING_RE = re.compile(
    r"^(?:#+\s*)?(?:1\.?\s+)?introduction\s*$", re.IGNORECASE
)
_REFERENCES_HEADING_RE = re.compile(
    r"^(?:#+\s*)?references?\s*$", re.IGNORECASE
)
_PAGE_NUMBER_RE = re.compile(r"^\d{1,4}$")
_DOI_LABEL_PREFIX_RE = re.compile(r"^\s*doi:\s*10\.", re.IGNORECASE)
_CITE_LINE_RE = re.compile(r"^To\s+cite\s+this\s+article:", re.IGNORECASE)
_COPYRIGHT_LINE_RE = re.compile(
    r"©\s*\d{4}|^\d{4}-\d{3,4}x?/", re.IGNORECASE
)
_KEYWORDS_LINE_RE = re.compile(r"^(?:#+\s*)?keywords?[:\s]", re.IGNORECASE)


def _is_doi_primary_paragraph(text: str) -> bool:
    """True when *text* is dominated by a DOI (URL or ``doi:`` prefix or bare id).

    Uses :func:`~knowmat.pdf.doi_extractor.extract_first_doi` so block tagging matches
    :func:`~knowmat.pdf.doi_extractor.extract_first_doi_from_ocr_items` / MD ``DOI:`` prefix logic.
    """
    if not text:
        return False
    doi = extract_first_doi(text)
    if not doi:
        return False
    t = text.strip()
    if DOI_URL_RE.search(t) or _DOI_LABEL_PREFIX_RE.match(t):
        return True
    # Short single-field lines where the DOI is essentially the whole paragraph
    return len(t) <= len(doi) + 24


def _layout_noise_role(block_label: str) -> str:
    if "header" in block_label:
        return "header"
    if "footer" in block_label:
        return "footer"
    return "layout_noise"


def _step_front_matter(text: str, title_assigned: bool) -> Tuple[str, str, bool]:
    if _ABSTRACT_HEADING_RE.match(text):
        return "abstract", "abstract", title_assigned
    if _INTRODUCTION_HEADING_RE.match(text):
        return "body", "body", title_assigned
    if not title_assigned and len(text) >= 20:
        return "front_matter", "title", True
    return "front_matter", "author" if title_assigned else "masthead", title_assigned


def _step_abstract(text: str, title_assigned: bool) -> Tuple[str, str, bool]:
    if _INTRODUCTION_HEADING_RE.match(text):
        return "body", "body", title_assigned
    if _KEYWORDS_LINE_RE.match(text):
        return "abstract", "keywords", title_assigned
    return "abstract", "abstract", title_assigned


def _state_machine_step(
    state: str,
    text: str,
    title_assigned: bool,
) -> Tuple[str, str, bool]:
    """Advance the document state machine by one paragraph.

    Returns ``(new_state, role, new_title_assigned)``.
    """
    if state == "front_matter":
        return _step_front_matter(text, title_assigned)
    if state == "abstract":
        return _step_abstract(text, title_assigned)
    if state == "body":
        if _REFERENCES_HEADING_RE.match(text):
            return "references", "reference", title_assigned
        return "body", "body", title_assigned
    return "references", "reference", title_assigned


def _fast_path_role(
    item: Dict[str, Any],
    text: str,
    is_masthead_fn: Any,
) -> Optional[str]:
    """Return a role string if *item* can be classified without document context.

    Returns ``None`` when the state machine is needed.
    """
    typer = item.get("typer", "")
    if typer in ("image", "table", "formula"):
        return typer

    blabel = item.get("block_label") or ""
    if item.get("is_layout_noise") or blabel in _LAYOUT_NOISE_LABELS:
        return _layout_noise_role(blabel)

    if _PAGE_NUMBER_RE.match(text):
        return "page_number"

    if _is_doi_primary_paragraph(text):
        return "doi"

    if _CITE_LINE_RE.match(text) or _COPYRIGHT_LINE_RE.search(text):
        return "citation_info"

    if is_masthead_fn(text):
        return "masthead"

    return None


def classify_ocr_item_roles(items: List[Dict[str, Any]]) -> None:
    """Tag each item in *items* with a ``role`` field in-place.

    Roles (mutually exclusive, assigned in priority order):

    - ``header`` / ``footer`` — already marked as layout noise
    - ``page_number`` — bare integer paragraph
    - ``masthead`` — *masthead*: publisher/journal banner or platform UI lines at the
      top of a page (patterns shared with ``strip_leading_journal_masthead``), not the
      article title itself
    - ``doi`` — paragraph whose text is primarily a DOI (aligned with MD ``DOI:`` resolution)
    - ``citation_info`` — "To cite this article", copyright notice (not DOI-primary lines)
    - ``title`` — paper title (first substantive paragraph after mastheads)
    - ``author`` — author/affiliation lines between title and abstract
    - ``abstract`` — abstract heading and its body paragraphs
    - ``keywords`` — keywords line
    - ``body`` — main text paragraphs
    - ``reference`` — paragraphs after the References heading

    The function requires the full item list so it can apply a simple
    sequential state machine across the document.  Non-paragraph items
    (image, table, formula) receive role ``figure``, ``table``, or
    ``formula`` respectively, matching their ``typer``.
    """
    # Lazy import to avoid circular dependency at module load time.
    from .section_normalizer import is_masthead_line  # noqa: PLC0415

    state = "front_matter"
    title_assigned = False

    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("typer") not in ("paragraph", "text", "image", "table", "formula"):
            continue

        text = (item.get("text") or "").strip()
        fast_role = _fast_path_role(item, text, is_masthead_line)
        if fast_role is not None:
            item["role"] = fast_role
            continue

        state, item["role"], title_assigned = _state_machine_step(state, text, title_assigned)

