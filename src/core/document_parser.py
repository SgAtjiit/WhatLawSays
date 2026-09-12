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
from typing import Dict, List, Optional, Tuple

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
    # A scan or a photograph of a contract. Read by OCR, and the result is
    # labelled as such all the way through to the response.
    "image/png": "image",
    "image/jpeg": "image",
    "image/tiff": "image",
    "image/bmp": "image",
    "image/webp": "image",
}

_EXTENSION_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}

# Characters PDF producers emit that carry no meaning and break naive matching.
_INVISIBLES = dict.fromkeys(map(ord, "­​‌‍﻿"), None)

# A hyphenated word split across a line break. The hyphen is KEPT and only the
# newline removed.
#
# Dropping it produced "twentyfour months" and "interestfree deposit" in the
# quoted evidence shown to the reader, because contracts break exactly these
# compounds at line ends. The alternative error -- leaving a syllable break as
# "termi-nation" -- needs the producer to hyphenate mid-word, which Word does
# not do by default and which none of the contract PDFs measured here do. The
# rule patterns already spell hyphenated compounds as "[- ]?", so a preserved
# hyphen costs nothing there.
_HYPHEN_LINEBREAK = re.compile(r"([a-z])-\n([a-z])")
_HYPHEN_JOIN = r"\1-\2"

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
    text = text.replace(" ", " ").replace("\x00", "")
    text = _HYPHEN_LINEBREAK.sub(_HYPHEN_JOIN, text)
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

    pages, unreadable = [], []
    for index, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if len(text.strip()) < MIN_CHARS_PER_PAGE:
            unreadable.append(index + 1)
        pages.append(text)
    return pages, page_count, unreadable


def _element_text(element) -> str:
    """All text under an element, tracked-change insertions included.

    `Paragraph.text` reads only the runs directly under w:p, so text the other
    side added in Track Changes -- which lives in a w:ins wrapper -- was dropped
    silently. Reviewing a redlined contract is the whole point, and the review
    was reading the version from before their edits. Deletions stay out: Word
    puts those in w:delText, which this never sees.
    """
    from docx.oxml.ns import qn

    return "".join(node.text or "" for node in element.iter(qn("w:t")))


def _iter_docx_blocks(document) -> List[str]:
    """Yield paragraphs and table cells in document order.

    `document.paragraphs` silently skips tables, and contracts put payment
    schedules, rent amounts and notice periods in tables constantly -- exactly
    the terms a review exists to find.
    """
    from docx.oxml.ns import qn
    from docx.table import Table

    blocks: List[str] = []
    # Word's automatic numbering lives in w:numPr, not in the text, so a
    # contract numbered that way arrived with no clause numbers at all and every
    # finding cited "paragraph 7" instead of the clause the reader can see. The
    # counters are rebuilt here per (numId, level), deeper levels resetting when
    # a shallower one advances, and the number is written back into the text.
    counters: Dict[tuple, List[int]] = {}

    styles_element = document.styles.element
    resolved_styles: Dict[str, object] = {}

    def style_numbering(style_id: str, depth: int = 0):
        """numPr inherited from a paragraph style, following w:basedOn.

        Word's own "List Number" and numbered heading styles keep the numbering
        in styles.xml rather than on the paragraph, so looking only at the
        paragraph found nothing for the most common way a contract is numbered.
        """
        if not style_id or depth > 8:
            return None
        if style_id in resolved_styles:
            return resolved_styles[style_id]
        found = None
        for style in styles_element.findall(qn("w:style")):
            if style.get(qn("w:styleId")) != style_id:
                continue
            properties = style.find(qn("w:pPr"))
            if properties is not None and properties.find(qn("w:numPr")) is not None:
                found = properties.find(qn("w:numPr"))
            else:
                based_on = style.find(qn("w:basedOn"))
                if based_on is not None:
                    found = style_numbering(based_on.get(qn("w:val")), depth + 1)
            break
        resolved_styles[style_id] = found
        return found

    def numbering_prefix(paragraph) -> str:
        properties = paragraph.find(qn("w:pPr"))
        number_properties = None
        if properties is not None:
            number_properties = properties.find(qn("w:numPr"))
            if number_properties is None:
                style = properties.find(qn("w:pStyle"))
                if style is not None:
                    number_properties = style_numbering(style.get(qn("w:val")))
        if number_properties is None:
            return ""
        def value(tag, default=0):
            node = number_properties.find(qn(tag))
            if node is None:
                return default
            raw = node.get(qn("w:val"))
            return int(raw) if raw is not None and raw.lstrip("-").isdigit() else default
        num_id, level = value("w:numId", -1), value("w:ilvl", 0)
        if num_id < 0 or level > 8:
            return ""
        counts = counters.setdefault(num_id, [])
        while len(counts) <= level:
            counts.append(0)
        counts[level] += 1
        del counts[level + 1 :]
        return ".".join(str(n) for n in counts[: level + 1]) + " "

    def walk(element):
        for child in element.iterchildren():
            if child.tag == qn("w:p"):
                text = " ".join(_element_text(child).split())
                if text:
                    blocks.append(numbering_prefix(child) + text)
            elif child.tag == qn("w:tbl"):
                for row in Table(child, document).rows:
                    cells, seen = [], None
                    for cell in row.cells:
                        # Word repeats a merged cell once per underlying grid
                        # column. Comparing the ELEMENT catches that; comparing
                        # the text also swallowed two distinct cells that
                        # happened to read the same, such as a repeated amount.
                        if cell._tc is seen:
                            continue
                        seen = cell._tc
                        # Reads nested tables too, which were dropped entirely.
                        value = " ".join(_element_text(cell._tc).split())
                        if value:
                            cells.append(value)
                    if cells:
                        blocks.append(" | ".join(cells))
            elif child.tag in (qn("w:sdt"), qn("w:sdtContent"), qn("w:customXml")):
                # A content control. Everything inside one used to vanish, and a
                # whole clause with it, with nothing said about the loss.
                walk(child)

    walk(document.element.body)
    return blocks


def _docx_warnings(document) -> List[str]:
    from docx.oxml.ns import qn

    body = document.element.body
    if any(True for _ in body.iter(qn("w:ins"))) or any(True for _ in body.iter(qn("w:del"))):
        return [
            "This file contains unaccepted tracked changes. Insertions are included "
            "in the review and deletions are not, so it reads as the document would "
            "if every change were accepted."
        ]
    return []


def _extract_docx(data: bytes) -> List[str]:
    try:
        import docx
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise DocumentParseError(f"DOCX support unavailable: {exc}") from exc

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise DocumentParseError(f"Could not open DOCX: {exc}") from exc
    return _iter_docx_blocks(document), _docx_warnings(document)


def _decode_text(data: bytes):
    """Decode a text upload, detecting UTF-16.

    A UTF-16 file decoded as UTF-8 becomes text with a NUL between every letter:
    it segments into one clause of gibberish and every rule silently matches
    nothing. Windows editors write UTF-16 routinely, and without a BOM there is
    nothing to notice but the NULs themselves.
    """
    for bom, encoding in (
        (b"\xef\xbb\xbf", "utf-8-sig"),
        (b"\xff\xfe", "utf-16"),
        (b"\xfe\xff", "utf-16"),
    ):
        if data.startswith(bom):
            try:
                return data.decode(encoding), None
            except UnicodeDecodeError:
                break

    try:
        text = data.decode("utf-8")
        if text.count("\x00") * 3 < len(text):
            return text, None
    except UnicodeDecodeError:
        text = None

    # No BOM, but NUL-riddled: almost certainly UTF-16 written without one.
    # Which endianness is decided by WHERE the NULs sit, not by whether the
    # decode succeeds -- BE text decoded as LE yields CJK-range characters with
    # no NUL at all, so a NUL test alone happily accepts the wrong one.
    head = data[:4096]
    even_nuls = head[0::2].count(0)
    odd_nuls = head[1::2].count(0)
    order = ["utf-16-le", "utf-16-be"] if odd_nuls >= even_nuls else ["utf-16-be", "utf-16-le"]
    for encoding in order:
        try:
            candidate = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\x00" not in candidate:
            return candidate, None

    if text is not None:
        return text, None
    return (
        data.decode("utf-8", errors="replace"),
        "File was not valid UTF-8; undecodable bytes were replaced. "
        "Check the text for corruption before relying on this review.",
    )


def _ocr_document(data: bytes, filename: str, media_type: str, kind: str):
    """Read an image or a text-layerless PDF, and say how well it went."""
    from src.core import ocr

    try:
        result = ocr.ocr_image_bytes(data) if kind == "image" else ocr.ocr_pdf(data)
    except ocr.OcrUnavailable:
        raise
    except Exception as exc:
        # A corrupt or unreadable file must reach the caller as a refusal it can
        # act on, not as whatever the renderer happened to raise.
        raise DocumentParseError(
            f"Could not read {filename!r} as an image: {exc}"
        ) from exc
    if not result.words:
        raise DocumentParseError(
            f"Nothing could be read from {filename!r}, even by OCR. If it is a "
            "photograph, retake it square-on in good light at the highest "
            "resolution available."
        )

    warnings = [
        "This document has no text layer, so it was read by OCR. Every quoted "
        f"passage is our reading of the image rather than text taken from the "
        f"file, and characters can be misread -- particularly in amounts. Mean "
        f"confidence {result.mean_confidence:.0f}%."
    ]
    if result.unreadable_pages:
        shown = ", ".join(str(n) for n in result.unreadable_pages[:10])
        warnings.append(
            f"{len(result.unreadable_pages)} page(s) could not be read at all "
            f"(page {shown}). Anything on them was not reviewed."
        )
    low = len(result.low_confidence_words)
    if low:
        warnings.append(
            f"{low} of {len(result.words)} words were read with low confidence. "
            "Check any figure or date a finding turns on against the original."
        )
    return result, warnings


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
    ocr_result = None
    unreadable: List[int] = []

    if kind == "image":
        ocr_result, ocr_warnings = _ocr_document(data, filename, media_type, kind)
        raw_pages = [ocr_result.text]
        page_count = ocr_result.page_count
        warnings.extend(ocr_warnings)
    elif kind == "pdf":
        raw_pages, page_count, unreadable = _extract_pdf(data)
        # Most of the document has no text layer: it is a scan. Read it by OCR
        # where that is possible, and refuse only when it is not -- reviewing it
        # as-is would report no problems simply because nothing could be read,
        # which is indistinguishable from a clean contract.
        if page_count and unreadable and len(unreadable) * 2 > page_count:
            from src.core import ocr as _ocr

            if _ocr.is_available():
                ocr_result, ocr_warnings = _ocr_document(data, filename, media_type, kind)  # noqa: E501
                raw_pages = [ocr_result.text]
                page_count = ocr_result.page_count
                warnings.extend(ocr_warnings)
                unreadable = []
            else:
                raise DocumentParseError(
                    f"{len(unreadable)} of this PDF's {page_count} pages have no "
                    "readable text, so most of the contract could not be read. It "
                    "is most likely a scan or an image, and OCR is not installed "
                    "on this machine (macOS: `brew install tesseract`). Run OCR on "
                    "it and upload the text version -- reviewing it as-is would "
                    "report no problems simply because nothing could be read."
                )
    elif kind == "docx":
        blocks, docx_warnings = _extract_docx(data)
        raw_pages = ["\n\n".join(blocks)]
        warnings.extend(docx_warnings)
    else:
        decoded, encoding_warning = _decode_text(data)
        raw_pages = [decoded]
        if encoding_warning:
            warnings.append(encoding_warning)

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
        # Averaged density hides a partial scan: 8 good pages among 20 pass it
        # comfortably while 12 pages of the contract were never read at all.
        if unreadable:
            shown = ", ".join(str(n) for n in unreadable[:10])
            warnings.append(
                f"{len(unreadable)} of {page_count} pages had no readable text "
                f"(page{'s' if len(unreadable) > 1 else ''} {shown}"
                f"{' and others' if len(unreadable) > 10 else ''}). Anything on "
                "them was not reviewed."
            )

        density = len(text) / page_count
        if density < MIN_CHARS_PER_PAGE and ocr_result is None:
            raise DocumentParseError(
                f"This PDF has almost no extractable text ({len(text)} characters "
                f"across {page_count} pages). It is most likely a scan or an image, "
                "and OCR is not installed on this machine (macOS: `brew install "
                "tesseract`). Run OCR on it and upload the text version -- "
                "reviewing it as-is "
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
        source="ocr" if ocr_result is not None else "text_layer",
        ocr_confidence=ocr_result.mean_confidence if ocr_result is not None else None,
        ocr_basis=ocr_result.to_payload() if ocr_result is not None else None,
        ocr_words=ocr_result.word_payload() if ocr_result is not None else [],
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
