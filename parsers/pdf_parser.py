"""PDF parsing with an OCR fallback for scanned documents."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pypdf import PdfReader

from config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ParsedDocument:
    text: str
    num_pages: int = 0
    used_ocr: bool = False
    error: str | None = None


def _ocr_pdf(path: str) -> str | None:
    """OCR fallback; requires pdf2image+poppler and pytesseract+tesseract.
    Returns None if the OCR stack is unavailable."""
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError:
        logger.info("OCR stack not installed (pdf2image/pytesseract), skipping OCR")
        return None
    try:
        pages = convert_from_path(path, dpi=200)
        return "\n\n".join(pytesseract.image_to_string(page) for page in pages)
    except Exception as exc:  # noqa: BLE001 - missing system binaries land here
        logger.warning("OCR failed: %s", exc)
        return None


def process_pdf(path: str) -> ParsedDocument:
    """Extract text from a PDF; if it looks like a scan (no text layer), try OCR."""
    try:
        reader = PdfReader(path)
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        num_pages = len(reader.pages)
    except Exception as exc:  # noqa: BLE001
        return ParsedDocument(text="", error=f"PDF parse error: {exc}")

    if len(text.strip()) >= get_settings().ocr_min_chars:
        return ParsedDocument(text=text, num_pages=num_pages)

    ocr_text = _ocr_pdf(path)
    if ocr_text and len(ocr_text.strip()) > len(text.strip()):
        return ParsedDocument(text=ocr_text, num_pages=num_pages, used_ocr=True)

    if not text.strip():
        return ParsedDocument(
            text="",
            num_pages=num_pages,
            error=(
                "No text could be extracted. The document appears to be a scan and the "
                "OCR stack (tesseract + poppler) is not available."
            ),
        )
    return ParsedDocument(text=text, num_pages=num_pages)
