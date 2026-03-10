"""
PDF parsing node using PaddleOCR-VL (with PaddleOCR fallback).

This parser renders each PDF page to an image, runs OCR, and returns a single
markdown text block for downstream extraction agents.  It also extracts
document-level metadata (DOI, etc.) from the first page header/footer area
and converts any residual HTML in pre-existing .txt files to clean markdown.
"""

import os
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from knowmat.states import KnowMatState


# ---------------------------------------------------------------------------
# DOI extraction helpers
# ---------------------------------------------------------------------------

_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)\b")
_DOI_URL_RE = re.compile(r"https?://doi\.org/(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)")


def _extract_doi_from_text(text: str) -> Optional[str]:
    """Return the first DOI found in *text*, or None."""
    if not text:
        return None
    m = _DOI_URL_RE.search(text)
    if m:
        return m.group(1).rstrip(".")
    m = _DOI_RE.search(text)
    if m:
        return m.group(1).rstrip(".")
    return None


# ---------------------------------------------------------------------------
# HTML → markdown conversion for .txt inputs
# ---------------------------------------------------------------------------

_HTML_IMG_RE = re.compile(r'<div[^>]*>\s*<img[^>]*/>\s*</div>', re.IGNORECASE)
_HTML_DIV_OPEN_RE = re.compile(r'<div[^>]*>', re.IGNORECASE)
_HTML_DIV_CLOSE_RE = re.compile(r'</div>', re.IGNORECASE)
_HTML_TABLE_BLOCK_RE = re.compile(
    r'<table[^>]*>.*?</table>', re.IGNORECASE | re.DOTALL
)
_HTML_TAG_RE = re.compile(r'</?[a-zA-Z][^>]*>')
_LATEX_DISPLAY_RE = re.compile(r'\$\$\s*(.*?)\s*\$\$', re.DOTALL)


def _html_table_to_markdown(html: str) -> str:
    """Best-effort conversion of a single <table> to a markdown table."""
    from html.parser import HTMLParser

    rows: List[List[str]] = []
    current_row: List[str] = []
    current_cell: List[str] = []
    in_cell = False

    class _TableParser(HTMLParser):
        def handle_starttag(self, tag, attrs):
            nonlocal in_cell, current_cell
            if tag in ("td", "th"):
                in_cell = True
                current_cell = []

        def handle_endtag(self, tag):
            nonlocal in_cell, current_row
            if tag in ("td", "th"):
                in_cell = False
                current_row.append(" ".join(current_cell).strip())
            elif tag == "tr":
                if current_row:
                    rows.append(current_row)
                current_row = []

        def handle_data(self, data):
            if in_cell:
                txt = data.strip()
                if txt:
                    current_cell.append(txt)

    try:
        _TableParser().feed(html)
    except Exception:
        return html

    if not rows:
        return html

    col_count = max(len(r) for r in rows)
    lines: List[str] = []
    for i, row in enumerate(rows):
        padded = row + [""] * (col_count - len(row))
        lines.append("| " + " | ".join(padded) + " |")
        if i == 0:
            lines.append("| " + " | ".join(["---"] * col_count) + " |")
    return "\n".join(lines)


def _convert_html_to_markdown(text: str) -> str:
    """Convert residual HTML markup in OCR/txt output to clean markdown."""
    # Convert HTML tables to markdown tables
    text = _HTML_TABLE_BLOCK_RE.sub(lambda m: _html_table_to_markdown(m.group(0)), text)
    # Remove image divs entirely (keep only figure captions which are separate lines)
    text = _HTML_IMG_RE.sub("", text)
    # Remove remaining <div> wrappers but keep content
    text = _HTML_DIV_OPEN_RE.sub("", text)
    text = _HTML_DIV_CLOSE_RE.sub("", text)
    # Strip any remaining HTML tags
    text = _HTML_TAG_RE.sub("", text)
    # Clean up excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _default_model_dir() -> Path:
    """Return the default local model directory in this project."""
    repo_root = Path(__file__).resolve().parents[3]
    model_dir = os.getenv("PADDLEOCRVL_MODEL_DIR", str(repo_root / "models" / "paddleocrvl1_5"))
    return Path(model_dir).expanduser().resolve()


def _prepare_ocr_home(model_dir: Path) -> None:
    """Ensure local model directory exists and is used by PaddleOCR."""
    model_dir.mkdir(parents=True, exist_ok=True)
    os.environ["PADDLEOCR_HOME"] = str(model_dir)


def _create_ocr_engine(model_dir: Path) -> Tuple[Any, str]:
    """Create a PaddleOCR-VL engine, or fallback to PaddleOCR."""
    _prepare_ocr_home(model_dir)

    try:
        from paddleocr import PaddleOCRVL  # type: ignore

        for kwargs in ({}, {"lang": "en"}, {"model_dir": str(model_dir)}, {"lang": "en", "model_dir": str(model_dir)}):
            try:
                return PaddleOCRVL(**kwargs), "paddleocrvl"
            except TypeError:
                continue
    except Exception:
        pass

    try:
        from paddleocr import PaddleOCR  # type: ignore
    except Exception as exc:
        raise ImportError(
            "PaddleOCR is not installed. Install `paddleocr` and `paddlepaddle` first."
        ) from exc

    init_candidates = (
        {"use_angle_cls": True, "lang": "en"},
        {"lang": "en"},
        {},
    )
    last_error: Exception | None = None
    for kwargs in init_candidates:
        try:
            return PaddleOCR(**kwargs), "paddleocr"
        except TypeError as exc:
            last_error = exc

    if last_error:
        raise RuntimeError(f"Failed to initialize PaddleOCR engine: {last_error}") from last_error
    raise RuntimeError("Failed to initialize PaddleOCR engine.")


def _run_ocr(engine: Any, image_path: Path) -> Any:
    """Run OCR for a single page image with broad API compatibility."""
    img = str(image_path)

    if hasattr(engine, "predict"):
        try:
            return engine.predict(img)
        except TypeError:
            return engine.predict(input=img)
        except Exception:
            pass

    if hasattr(engine, "ocr"):
        try:
            return engine.ocr(img, cls=True)
        except TypeError:
            return engine.ocr(img)

    if callable(engine):
        return engine(img)

    raise RuntimeError("OCR engine does not expose a known inference method.")


def _collect_text(obj: Any, out: List[str]) -> None:
    """Recursively collect OCR text from mixed response structures."""
    if obj is None:
        return

    if isinstance(obj, str):
        text = obj.strip()
        if text:
            out.append(text)
        return

    if isinstance(obj, dict):
        for key in ("text", "rec_text", "ocr_text", "content", "transcription"):
            val = obj.get(key)
            if isinstance(val, str):
                val = val.strip()
                if val:
                    out.append(val)
        for val in obj.values():
            _collect_text(val, out)
        return

    if isinstance(obj, (list, tuple)):
        # PaddleOCR classic format: [box, (text, score)]
        if (
            len(obj) == 2
            and isinstance(obj[1], (list, tuple))
            and len(obj[1]) > 0
            and isinstance(obj[1][0], str)
        ):
            text = obj[1][0].strip()
            if text:
                out.append(text)
            return
        for item in obj:
            _collect_text(item, out)


def _normalize_lines(lines: List[str]) -> List[str]:
    """Clean and deduplicate line-level OCR text."""
    normalized: List[str] = []
    prev = ""
    for line in lines:
        text = re.sub(r"\s+", " ", line).strip()
        if not text or text == prev:
            continue
        normalized.append(text)
        prev = text
    return normalized


def _strip_references_section(text: str) -> str:
    """Drop references/bibliography section from parsed text."""
    out: List[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^#+\s*(references?|bibliography|citations?)\s*$", stripped, re.IGNORECASE):
            break
        if re.match(r"^(references?|bibliography|citations?)\s*$", stripped, re.IGNORECASE):
            break
        out.append(line)
    return "\n".join(out).strip()


def _extract_doi_from_pdf_metadata(pdf_path: str) -> Optional[str]:
    """Try to extract DOI from the PDF's built-in metadata fields."""
    try:
        import fitz  # type: ignore
    except Exception:
        return None
    try:
        doc = fitz.open(pdf_path)
        meta = doc.metadata or {}
        doc.close()
        for key in ("doi", "subject", "keywords", "title"):
            val = meta.get(key, "")
            if val:
                doi = _extract_doi_from_text(val)
                if doi:
                    return doi
    except Exception:
        pass
    return None


def _extract_pdf_with_paddleocrvl(pdf_path: str, output_dir: str, model_dir: Path) -> Tuple[str, Dict[str, Any]]:
    """Render PDF pages, run OCR, and return merged text with metadata.

    Also extracts DOI from the first page text and PDF-level metadata.
    The DOI is returned in ``metadata["doi"]``.
    """
    try:
        import fitz  # type: ignore
    except Exception as exc:
        raise ImportError(
            "PyMuPDF is required for PaddleOCR parsing. Install `pymupdf`."
        ) from exc

    pdf = Path(pdf_path)
    out_dir = Path(output_dir)
    image_dir = out_dir / "page_images"
    raw_dir = out_dir / "ocr_raw"
    image_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    engine, backend = _create_ocr_engine(model_dir=model_dir)

    page_blocks: List[str] = []
    first_page_full_text = ""
    doc = fitz.open(str(pdf))
    try:
        for page_idx, page in enumerate(doc, start=1):
            image_path = image_dir / f"{pdf.stem}-page-{page_idx:04d}.png"
            page.get_pixmap(dpi=300, alpha=False).save(str(image_path))

            raw = _run_ocr(engine, image_path)
            with open(raw_dir / f"page-{page_idx:04d}.json", "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2, default=str)

            lines: List[str] = []
            _collect_text(raw, lines)
            lines = _normalize_lines(lines)

            if not lines:
                fallback = page.get_text("text")
                lines = [x.strip() for x in fallback.splitlines() if x.strip()]

            page_text = "\n".join(lines).strip()
            page_blocks.append(f"## Page {page_idx}\n\n{page_text}")

            # Capture full first-page text (OCR + PyMuPDF) for DOI search
            if page_idx == 1:
                pymupdf_text = page.get_text("text") or ""
                first_page_full_text = page_text + "\n" + pymupdf_text
    finally:
        doc.close()

    # --- DOI extraction: PDF metadata → first page OCR+text → whole doc ---
    doi = _extract_doi_from_pdf_metadata(str(pdf))
    if not doi:
        doi = _extract_doi_from_text(first_page_full_text)

    merged = "\n\n".join(page_blocks).strip()
    metadata = {
        "backend": backend,
        "model_dir": str(model_dir),
        "pages": len(page_blocks),
        "image_dir": str(image_dir),
        "ocr_raw_dir": str(raw_dir),
        "doi": doi,
    }
    return merged, metadata


def _read_txt_file(path: Path) -> str:
    """Read plain text file with robust fallback encoding handling."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def parse_pdf_with_paddleocrvl(state: KnowMatState) -> dict:
    """Parse PDF/TXT and return cleaned paper text + document metadata.

    Returns
    -------
    dict
        ``paper_text``: cleaned markdown of the paper body (references stripped).
        ``document_metadata``: dict with at least ``{"doi": str|None}``.
    """
    input_path = state.get("pdf_path")
    if not input_path:
        raise ValueError("No input file path provided in state for parse_pdf_with_paddleocrvl node.")

    output_dir = state.get("output_dir", ".")
    source_path = Path(input_path)
    suffix = source_path.suffix.lower()

    if suffix == ".txt":
        parse_output_dir = Path(output_dir) / "txt_parse"
        parse_output_dir.mkdir(parents=True, exist_ok=True)

        raw_text = _read_txt_file(source_path)
        # Convert any residual HTML to clean markdown
        md_text = _convert_html_to_markdown(raw_text)
        cleaned_text = _strip_references_section(md_text)
        stem = source_path.stem

        # Try to extract DOI from the text itself (first ~5000 chars)
        doi = _extract_doi_from_text(cleaned_text[:5000])

        final_md_path = parse_output_dir / f"{stem}_final_output.md"
        with open(final_md_path, "w", encoding="utf-8") as f:
            f.write(cleaned_text)
        print(f"Saved txt parsed output to: {final_md_path}")

        doc_meta: Dict[str, Any] = {
            "backend": "txt-direct",
            "source_file": str(source_path),
            "doi": doi,
        }
        meta_path = parse_output_dir / f"{stem}_parse_metadata.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(doc_meta, f, ensure_ascii=False, indent=2)
        print(f"Saved parser metadata to: {meta_path}")

        return {"paper_text": cleaned_text, "document_metadata": doc_meta}

    if suffix != ".pdf":
        raise ValueError(f"Unsupported file type: {source_path.suffix}. Only .pdf and .txt are supported.")

    parse_output_dir = Path(output_dir) / "paddleocrvl_parse"
    parse_output_dir.mkdir(parents=True, exist_ok=True)
    model_dir = _default_model_dir()

    try:
        extracted_text, metadata = _extract_pdf_with_paddleocrvl(str(source_path), str(parse_output_dir), model_dir)
        cleaned_text = _strip_references_section(extracted_text)

        pdf_name = source_path.stem
        final_md_path = parse_output_dir / f"{pdf_name}_final_output.md"
        with open(final_md_path, "w", encoding="utf-8") as f:
            f.write(cleaned_text)
        print(f"Saved final markdown output to: {final_md_path}")

        doc_meta = {
            "backend": metadata.get("backend", "paddleocrvl"),
            "model_dir": metadata.get("model_dir"),
            "pages": metadata.get("pages"),
            "doi": metadata.get("doi"),
        }

        meta_path = parse_output_dir / f"{pdf_name}_parse_metadata.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        print(f"Saved parser metadata to: {meta_path}")

        return {"paper_text": cleaned_text, "document_metadata": doc_meta}
    except Exception as exc:
        raise RuntimeError(f"Failed to parse PDF with PaddleOCR-VL: {str(exc)}") from exc
