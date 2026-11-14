"""Read and normalize source data. TODO: implement functions."""
import logging
import re
import unicodedata
from pathlib import Path

import pymupdf

from .models import DocumentPage

logger = logging.getLogger(__name__)


def load_pdf(path: Path, document_id: str, source: str) -> list[DocumentPage]:
    """TODO: extract each physical page; keep its page number and source.

    Detect and record pages with no text. OCR, when needed, is a separate step.
    """
    if not path.is_file():
        raise FileNotFoundError(f"PDF not found: {path}")

    pages: list[DocumentPage] = []
    current_section: str | None = None
    with pymupdf.open(path) as doc:
        if not doc.is_pdf:
            raise ValueError(f"Expected a PDF file: {path}")
        if doc.page_count == 0:
            raise ValueError(f"PDF has no pages: {path}")

        for page_number, pdf_page in enumerate(doc, start=1):
            text = normalize_text(pdf_page.get_text("text", sort=True))
            text = _remove_page_number(text, page_number)
            section_boundaries = _section_boundaries(pdf_page, text)
            page_section = current_section
            for boundary in section_boundaries:
                current_section = boundary["section"]

            has_text = bool(text)
            if not has_text:
                logger.warning(
                    "No extractable text on PDF page %d in %s",
                    page_number,
                    path,
                )
            pages.append(
                DocumentPage(
                    document_id=document_id,
                    source=source,
                    page=page_number,
                    text=text,
                    metadata={
                        "text_extraction": "ok" if has_text else "empty",
                        "section": page_section,
                        "_section_boundaries": section_boundaries,
                    },
                )
            )
    return pages


def normalize_text(text: str) -> str:
    """TODO: normalize Unicode and whitespace without discarding useful structure."""
    normalized_text = unicodedata.normalize("NFC", text)
    normalized_text = normalized_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [
        re.sub(r"[^\S\n]+", " ", line).strip()
        for line in normalized_text.split("\n")
    ]
    normalized_text = "\n".join(lines)
    normalized_text = re.sub(r"\n{3,}", "\n\n", normalized_text)
    return normalized_text.strip()


def _remove_page_number(text: str, page_number: int) -> str:
    lines = text.splitlines()
    if lines and lines[0].strip() == str(page_number):
        lines.pop(0)
    if lines and lines[-1].strip() == str(page_number):
        lines.pop()
    return "\n".join(lines).strip()


def _section_name(text: str) -> str | None:
    if re.fullmatch(r"\d+(?:\.\d+)*\.?", text):
        return None

    numbered_heading = re.match(r"^\d+(?:\.\d+)*\.?\s+(.+?)\s*:?$", text)
    if numbered_heading:
        return numbered_heading.group(1).strip().rstrip(":")

    if (
        ":" not in text
        and len(text) <= 80
        and len(text.split()) <= 8
        and not text.endswith((".", "!", "?"))
    ):
        return text
    return None


def _section_boundaries(pdf_page: pymupdf.Page, text: str) -> list[dict[str, object]]:
    boundaries: list[dict[str, object]] = []
    search_from = 0
    blocks = pdf_page.get_text("dict", sort=True).get("blocks", [])
    body_sizes = sorted(
        float(span.get("size", 0))
        for block in blocks
        if block.get("type") == 0
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if span.get("text", "").strip() and not span.get("flags", 0) & 16
    )
    body_size = body_sizes[len(body_sizes) // 2] if body_sizes else 0
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans or not all(span.get("flags", 0) & 16 for span in spans):
                continue
            if any(float(span.get("size", 0)) < body_size - 0.25 for span in spans):
                continue

            heading_text = normalize_text(
                "".join(span.get("text", "") for span in spans)
            )
            section = _section_name(heading_text)
            if not section:
                continue

            offset = text.find(heading_text, search_from)
            if offset < 0:
                offset = text.find(heading_text)
            if offset >= 0:
                heading_offset = offset
                line_start = text.rfind("\n", 0, heading_offset) + 1
                heading_prefix = text[line_start:heading_offset]
                if re.fullmatch(r"\s*\d+(?:\.\d+)*\.?\s*", heading_prefix):
                    offset = line_start
                boundaries.append({"offset": offset, "section": section})
                search_from = heading_offset + len(heading_text)

    boundaries.sort(key=lambda boundary: int(boundary["offset"]))
    return boundaries
