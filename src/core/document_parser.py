"""Extract text from an uploaded contract, with offsets preserved.

Everything downstream -- clause segmentation, red-flag matching, the grounding
verifier -- addresses the document by character offset into
`ParsedDocument.text`. So normalization happens exactly once, here, and the
normalized string is the single source of truth. Nothing further down may
re-normalize, or offsets stop pointing at the text they claim to quote.

A scanned PDF is rejected rather than reviewed. A PDF with no text layer yields
an empty or near-empty string, and an empty string segments into zero clauses,
which would otherwise render as a clean review of a contract nobody read.
"""

import io
import re
from typing import List, Optional, Tuple

from src.schemas.contract import ParsedDocument

# Upload limits. Enforced here rather than at the API edge so that direct callers
# (tests, scripts, the Streamlit direct mode) are bound by the same ceiling.
MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_PDF_PAGES = 200

# Below this many characters of extracted text per page, a PDF is treated as
# having no usable text layer. A genuine contract page carries well over a
# thousand characters; a scanned page yields a handful of stray ligatures at most.
MIN_CHARS_PER_PAGE = 120

SUPPORTED_MEDIA_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "text/markdown": "txt",
}

_EXTENSION_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}

# Characters PDF producers emit that carry no meaning and break naive matching.
_INVISIBLES = dict.fromkeys(map(ord, "­​‌‍﻿"), None)

# A word split across a line break by the typesetter. Rejoined only when the
# break sits between two lowercase letters, so genuine hyphenated compounds at a
# line end ("Non-\nDisclosure") are left alone.
_HYPHEN_LINEBREAK = re.compile(r"([a-z])-\n([a-z])")

_TRAILING_SPACE = re.compile(r"[ \t]+(?=\n)")
_HORIZONTAL_RUN = re.compile(r"[ \t\f\v]+")
_BLANK_RUN = re.compile(r"\n{3,}")


class DocumentParseError(Exception):
    """Raised when a document cannot be read well enough to review honestly."""


def normalize(raw: str) -> str:
    """Collapse presentation noise without altering wording.

    Wording is preserved for the same reason the statutory corpus is copied
    verbatim: a quote that does not match the source cannot be verified, and an
    unverifiable quote is indistinguishable from an invented one.
    """
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.translate(_INVISIBLES)
    text = text.replace(" ", " ")
    text = _HYPHEN_LINEBREAK.sub(r"\1\2", text)
    text = _HORIZONTAL_RUN.sub(" ", text)
    text = _TRAILING_SPACE.sub("", text)
    text = _BLANK_RUN.sub("\n\n", text)
    return text.strip()


def media_type_for(filename: str, declared: Optional[str] = None) -> str:
    """Resolve a media type, preferring the extension over the browser's claim.

    Browsers routinely send application/octet-stream for .docx, so a declared
    type is only trusted when the extension is unrecognised.
    """
    lowered = (filename or "").lower()
    for extension, media_type in _EXTENSION_MEDIA_TYPES.items():
        if lowered.endswith(extension):
            return media_type
    if declared in SUPPORTED_MEDIA_TYPES:
        return declared
    raise DocumentParseError(
        f"Unsupported file type for {filename!r}. "
        f"Supported: {', '.join(sorted(_EXTENSION_MEDIA_TYPES))}"
    )


def _extract_pdf(data: bytes) -> Tuple[List[str], int]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise DocumentParseError(f"PDF support unavailable: {exc}") from exc

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise DocumentParseError(f"Could not open PDF: {exc}") from exc

    if reader.is_encrypted:
        # An empty-password decrypt covers the common "protected but not secret"
        # case; anything else is a genuine wall and is reported as one.
        try:
            if not reader.decrypt(""):
                raise DocumentParseError(
                    "This PDF is password-protected. Remove the password and re-upload."
                )
        except DocumentParseError:
            raise
        except Exception as exc:
            raise DocumentParseError(
                f"This PDF is password-protected and could not be opened: {exc}"
            ) from exc

    page_count = len(reader.pages)
    if page_count > MAX_PDF_PAGES:
        raise DocumentParseError(
            f"PDF has {page_count} pages, above the {MAX_PDF_PAGES}-page limit."
        )

    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            # One unreadable page must not lose the other 40. The shortfall is
            # caught by the text-layer check below.
            pages.append("")
    return pages, page_count


def _iter_docx_blocks(document) -> List[str]:
    """Yield paragraphs and table cells in document order.

    `document.paragraphs` silently skips tables, and contracts put payment
    schedules, rent amounts and notice periods in tables constantly -- exactly
    the terms a review exists to find.
    """
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    blocks = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            text = Paragraph(child, document).text.strip()
            if text:
                blocks.append(text)
        elif child.tag == qn("w:tbl"):
            for row in Table(child, document).rows:
                cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                # Word repeats a merged cell's text once per underlying grid
                # column; collapsing neighbouring duplicates keeps the row honest.
                deduped = [c for i, c in enumerate(cells) if c and (i == 0 or c != cells[i - 1])]
                if deduped:
                    blocks.append(" | ".join(deduped))
    return blocks


def _extract_docx(data: bytes) -> List[str]:
    try:
        import docx
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise DocumentParseError(f"DOCX support unavailable: {exc}") from exc

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise DocumentParseError(f"Could not open DOCX: {exc}") from exc
    return _iter_docx_blocks(document)


def parse_document(
    data: bytes, filename: str, declared_media_type: Optional[str] = None
) -> ParsedDocument:
    """Read an uploaded contract into normalized text with page offsets."""
    if not data:
        raise DocumentParseError("Uploaded file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise DocumentParseError(
            f"File is {len(data) / 1_048_576:.1f} MB, above the "
            f"{MAX_FILE_BYTES // 1_048_576} MB limit."
        )

    media_type = media_type_for(filename, declared_media_type)
    kind = SUPPORTED_MEDIA_TYPES[media_type]
    warnings: List[str] = []
    page_count: Optional[int] = None

    if kind == "pdf":
        raw_pages, page_count = _extract_pdf(data)
    elif kind == "docx":
        raw_pages = ["\n\n".join(_extract_docx(data))]
    else:
        try:
            raw_pages = [data.decode("utf-8")]
        except UnicodeDecodeError:
            raw_pages = [data.decode("utf-8", errors="replace")]
            warnings.append(
                "File was not valid UTF-8; undecodable bytes were replaced. "
                "Check the text for corruption before relying on this review."
            )

    # Normalize each page before joining so recorded offsets survive the join.
    normalized_pages = [normalize(page) for page in raw_pages]
    separator = "\n\n"
    page_offsets: List[int] = []
    cursor = 0
    for page in normalized_pages:
        page_offsets.append(cursor)
        cursor += len(page) + len(separator)
    text = separator.join(normalized_pages)

    if kind == "pdf" and page_count:
        density = len(text) / page_count
        if density < MIN_CHARS_PER_PAGE:
            raise DocumentParseError(
                f"This PDF has almost no extractable text ({len(text)} characters "
                f"across {page_count} pages). It is most likely a scan or an image. "
                "Run OCR on it and upload the text version -- reviewing it as-is "
                "would report no problems simply because nothing could be read."
            )

    if len(text.split()) < 50:
        raise DocumentParseError(
            f"Only {len(text.split())} words could be read from {filename!r}. "
            "That is too little to review as a contract."
        )

    return ParsedDocument(
        filename=filename,
        media_type=media_type,
        text=text,
        page_count=page_count,
        page_offsets=page_offsets if page_count else [],
        char_count=len(text),
        extraction_warnings=warnings,
    )


def page_for_offset(document: ParsedDocument, offset: int) -> Optional[int]:
    """1-based page containing `offset`, or None for unpaginated formats."""
    if not document.page_offsets:
        return None
    page = 0
    for index, start in enumerate(document.page_offsets):
        if offset >= start:
            page = index
        else:
            break
    return page + 1
