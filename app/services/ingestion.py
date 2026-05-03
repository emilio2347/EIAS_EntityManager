"""Document ingestion — extract plain text from supported file types."""

from __future__ import annotations

import json
from pathlib import Path
from typing import BinaryIO


def extract_text(file: BinaryIO, filename: str) -> str:
    """Read a file-like object and return plain text.

    Supported extensions: .txt, .md, .pdf, .json
    """
    ext = Path(filename).suffix.lower()
    if ext in (".txt", ".md"):
        return _read_text(file)
    elif ext == ".pdf":
        return _read_pdf(file)
    elif ext == ".json":
        return _read_json(file)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def _read_text(file: BinaryIO) -> str:
    raw = file.read()
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw


def _read_pdf(file: BinaryIO) -> str:
    import fitz  # PyMuPDF

    data = file.read()
    doc = fitz.open(stream=data, filetype="pdf")
    pages: list[str] = []
    for page in doc:
        pages.append(page.get_text())
    doc.close()
    return "\n\n".join(pages)


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
