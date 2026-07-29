"""PDF parsing with an OCR fallback for scanned documents."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pypdf import PdfReader

from config import get_settings

logger = logging.getLogger(__name__)

logging.getLogger("pypdf").setLevel(logging.ERROR)


@dataclass
class ParsedDocument:
    text: str
    num_pages: int = 0
    used_ocr: bool = False
    error: str | None = None


def _has_image_xobject(reader: PdfReader) -> bool:
    """True if any page embeds a raster image XObject.

    Some PDFs render the claim body as images while leaving only the page chrome
    (title/section labels/footer) as a real text layer, so pypdf extracts a
    plausible-but-empty text layer and the OCR gate is never tripped. Detecting an
    embedded image lets us OCR those anyway. Reads the resource dictionary directly
    so no image data is decoded."""
    for page in reader.pages:
        resources = page.get("/Resources")
        if resources is None:
            continue
        xobjects = resources.get_object().get("/XObject")
        if xobjects is None:
            continue
        for obj in xobjects.get_object().values():
            try:
                if obj.get_object().get("/Subtype") == "/Image":
                    return True
            except Exception:  # noqa: BLE001 - malformed XObject entry, skip it
                continue
    return False


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

    settings = get_settings()
    stripped = text.strip()
    needs_ocr = len(stripped) < settings.ocr_min_chars or (
        len(stripped) < settings.ocr_image_text_threshold and _has_image_xobject(reader)
    )
    if not needs_ocr:
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
