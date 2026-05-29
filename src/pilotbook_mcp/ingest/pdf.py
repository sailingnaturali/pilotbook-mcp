"""PDF text extraction via poppler's pdftotext, with an OCR fallback for scans."""

from __future__ import annotations

import subprocess
from pathlib import Path

_MIN_CHARS_PER_PAGE = 100


def extract_text(pdf_path: str | Path) -> str:
    """Extract embedded text. '-layout' preserves the column structure pilot books use."""
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def is_scanned(text: str, pages: int) -> bool:
    """Heuristic: too little embedded text per page means the PDF is scanned images."""
    if pages <= 0:
        return len(text.strip()) < _MIN_CHARS_PER_PAGE
    return (len(text.strip()) / pages) < _MIN_CHARS_PER_PAGE


def extract_pages(pdf_path: str | Path) -> list[str]:
    """Per-page text via pdftotext -layout, split on the form-feed page separator."""
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, text=True, check=True,
    )
    pages = result.stdout.split("\x0c")
    if pages and not pages[-1].strip():
        pages.pop()  # pdftotext appends a trailing form-feed → drop the empty tail page
    return pages


def ocr_to_text(pdf_path: str | Path) -> str:
    """OCR a scanned PDF (ocrmypdf -> sidecar text). Requires ocrmypdf installed."""
    src = Path(pdf_path)
    sidecar = src.with_suffix(".ocr.txt")
    out_pdf = src.with_suffix(".ocr.pdf")
    subprocess.run(
        ["ocrmypdf", "--sidecar", str(sidecar), "--skip-text", str(src), str(out_pdf)],
        capture_output=True, text=True, check=True,
    )
    return sidecar.read_text(encoding="utf-8")
