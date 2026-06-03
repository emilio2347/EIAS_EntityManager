"""Document ingestion — extract plain text from supported file types."""

from __future__ import annotations

import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO


@dataclass
class ExtractedText:
    text: str
    normalization_method: str
    page_count: int | None = None
    ocr_pages: list[int] | None = None


def extract_text(file: BinaryIO, filename: str) -> str:
    """Read a file-like object and return plain text.

    Supported extensions: .txt, .md, .pdf, .json
    """
    return extract_text_with_metadata(file, filename).text


def extract_text_with_metadata(file: BinaryIO, filename: str) -> ExtractedText:
    """Read a file-like object and return normalized text plus provenance."""
    ext = Path(filename).suffix.lower()
    if ext in (".txt", ".md"):
        return ExtractedText(text=_read_text(file), normalization_method="machine_readable_text")
    elif ext == ".pdf":
        return _read_pdf(file)
    elif ext == ".json":
        return ExtractedText(text=_read_json(file), normalization_method="json_flattened_text")
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def _read_text(file: BinaryIO) -> str:
    raw = file.read()
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw


def _read_pdf(file: BinaryIO) -> ExtractedText:
    import fitz  # PyMuPDF

    data = file.read()
    doc = fitz.open(stream=data, filetype="pdf")
    pages: list[str] = []
    ocr_pages: list[int] = []
    for page in doc:
        page_text = page.get_text()
        if len(page_text.strip()) < 25:
            ocr_text = _ocr_pdf_page(page)
            if ocr_text.strip():
                page_text = ocr_text
                ocr_pages.append(page.number + 1)
        pages.append(page_text)
    page_count = doc.page_count
    doc.close()
    return ExtractedText(
        text="\n\n".join(pages),
        normalization_method="pdf_text_extraction_ocr_fallback",
        page_count=page_count,
        ocr_pages=ocr_pages,
    )


def _ocr_pdf_page(page) -> str:
    """OCR a PDF page when optional OCR dependencies are available."""
    try:
        textpage = page.get_textpage_ocr(language="eng", dpi=200, full=True)
        text = page.get_text("text", textpage=textpage)
        if text.strip():
            return text
    except Exception:
        pass

    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""

    try:
        matrix = page.parent.Matrix(2, 2) if hasattr(page.parent, "Matrix") else None
    except Exception:
        matrix = None
    try:
        import fitz

        pix = page.get_pixmap(matrix=matrix or fitz.Matrix(2, 2), alpha=False)
        image = Image.open(BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(image) or ""
    except Exception:
        return ""


def _read_json(file: BinaryIO) -> str:
    raw = file.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    data = json.loads(raw)
    return _flatten_json_values(data)


def _flatten_json_values(obj, parts: list[str] | None = None) -> str:
    """Recursively extract all string values from a JSON structure."""
    if parts is None:
        parts = []
    if isinstance(obj, str):
        parts.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _flatten_json_values(v, parts)
    elif isinstance(obj, list):
        for item in obj:
            _flatten_json_values(item, parts)
    return "\n".join(parts) if parts else ""
