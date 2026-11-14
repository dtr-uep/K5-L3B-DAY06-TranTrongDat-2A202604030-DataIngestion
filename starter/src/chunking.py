"""Implement fixed-size and structure-aware chunking."""
import re

from .models import Chunk, DocumentPage


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """TODO: split text into overlapping windows and retain page metadata."""
    if size <= 0:
        raise ValueError("size must be greater than zero")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be between zero and size - 1")

    text = page.text
    if not text or not text.strip():
        return []

    chunks: list[Chunk] = []
    start = 0
    chunk_index = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append(
                _make_chunk(page, chunk_text, "fixed", chunk_index, start)
            )
            chunk_index += 1
        if end == len(text):
            break
        start = end - overlap
    return chunks


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """TODO: group paragraphs, split oversized paragraphs and retain metadata."""
    if max_size <= 0:
        raise ValueError("max_size must be greater than zero")

    text = page.text
    if not text or not text.strip():
        return []

    chunks: list[Chunk] = []
    current_parts: list[str] = []
    current_length = 0
    current_section = None
    current_start = 0
    chunk_index = 0

    def flush() -> None:
        nonlocal current_parts, current_length, current_section, current_start
        nonlocal chunk_index
        if current_parts:
            chunks.append(
                _make_chunk(
                    page,
                    "\n\n".join(current_parts),
                    "paragraph",
                    chunk_index,
                    current_start,
                )
            )
            chunk_index += 1
        current_parts = []
        current_length = 0
        current_section = None

    for paragraph_start, paragraph in _paragraph_segments(page, text):
        section = _section_at_offset(page, paragraph_start)
        if current_parts and section != current_section:
            flush()

        if len(paragraph) > max_size:
            flush()
            piece_offset = paragraph_start
            for piece in _split_oversized(paragraph, max_size):
                chunks.append(
                    _make_chunk(
                        page,
                        piece,
                        "paragraph",
                        chunk_index,
                        piece_offset,
                    )
                )
                chunk_index += 1
                piece_offset += len(piece) + 1
            continue

        separator_size = 2 if current_parts else 0
        if current_parts and current_length + separator_size + len(paragraph) > max_size:
            flush()

        if not current_parts:
            current_start = paragraph_start
            current_section = section
        current_parts.append(paragraph)
        current_length += (2 if len(current_parts) > 1 else 0) + len(paragraph)

    flush()
    return chunks


def _make_chunk(
    page: DocumentPage,
    text: str,
    strategy: str,
    index: int,
    offset: int,
) -> Chunk:
    metadata = {
        key: value
        for key, value in page.metadata.items()
        if not key.startswith("_") and key != "section"
    }
    section = _section_at_offset(page, offset)
    if section is not None:
        metadata["section"] = section

    return Chunk(
        chunk_id=f"{page.document_id}:p{page.page}:{strategy}:{index:04d}",
        document_id=page.document_id,
        source=page.source,
        page=page.page,
        text=text.strip(),
        metadata=metadata,
    )


def _section_at_offset(page: DocumentPage, offset: int) -> str | None:
    section = page.metadata.get("section")
    for boundary in page.metadata.get("_section_boundaries", []):
        if int(boundary["offset"]) > offset:
            break
        section = str(boundary["section"])
    return section


def _paragraph_segments(page: DocumentPage, text: str) -> list[tuple[int, str]]:
    boundaries = sorted(
        page.metadata.get("_section_boundaries", []),
        key=lambda boundary: int(boundary["offset"]),
    )
    segments: list[tuple[int, str]] = []
    cursor = 0
    for separator in re.finditer(r"\n\s*\n+", text):
        _append_paragraph_segments(
            segments,
            text,
            cursor,
            separator.start(),
            boundaries,
        )
        cursor = separator.end()
    _append_paragraph_segments(segments, text, cursor, len(text), boundaries)
    return segments


def _append_paragraph_segments(
    segments: list[tuple[int, str]],
    text: str,
    start: int,
    end: int,
    boundaries: list[dict[str, object]],
) -> None:
    raw_paragraph = text[start:end]
    paragraph = raw_paragraph.strip()
    if not paragraph:
        return

    paragraph_start = start + len(raw_paragraph) - len(raw_paragraph.lstrip())
    paragraph_end = paragraph_start + len(paragraph)
    split_offsets = [
        int(boundary["offset"])
        for boundary in boundaries
        if paragraph_start < int(boundary["offset"]) < paragraph_end
    ]
    segment_start = paragraph_start
    for split_offset in split_offsets:
        segment = text[segment_start:split_offset].strip()
        if segment:
            segments.append((segment_start, segment))
        segment_start = split_offset
    segment = text[segment_start:paragraph_end].strip()
    if segment:
        segments.append((segment_start, segment))


def _split_oversized(text: str, max_size: int) -> list[str]:
    remaining = text.strip()
    pieces: list[str] = []
    while len(remaining) > max_size:
        split_at = max(
            (index for index, character in enumerate(remaining[: max_size + 1])
             if character.isspace()),
            default=0,
        )
        if split_at == 0:
            split_at = max_size
        piece = remaining[:split_at].strip()
        if not piece:
            split_at = max_size
            piece = remaining[:split_at].strip()
        pieces.append(piece)
        remaining = remaining[split_at:].strip()
    if remaining:
        pieces.append(remaining)
    return pieces
