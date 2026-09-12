"""Read a scanned contract, and record how well it was read.

A scan has no text layer, so without this the parser refuses it: an empty
extraction segments into zero clauses, every rule matches nothing, and the
result renders as a clean contract nobody read.

OCR removes that refusal but weakens the guarantee the rest of the product rests
on. Elsewhere "every finding quotes the document" is exact -- offsets index into
text lifted verbatim from the file. Here the text is *our reading* of an image,
so a quote can verify perfectly against a transcription that misread the paper:
"shall not" as "shall now", a digit lost from an amount. Verification becomes
circular.

Two things follow, and they shape this module.

    Confidence travels with the text. Tesseract is run in TSV mode rather than
    plain text so every word carries its own confidence and its own box on the
    page. The weak spots are then knowable rather than merely suspected.

    Every character keeps its position on the page. `OcrResult.locate` maps a
    character offset back to the region of the image it came from, which is what
    lets a finding be shown against the actual paper instead of asking the
    reader to trust the transcription.

Line and paragraph structure is reconstructed deliberately: the clause segmenter
finds markers at line starts, so OCR output emitted as one long line would
segment into nothing.
"""

import io
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Scans below this resolution lose thin strokes, and tesseract is tuned for
# roughly this density. Rendering a PDF page at 300 DPI is the usual advice.
TARGET_DPI = 300
_PDF_POINTS_PER_INCH = 72

# A word tesseract is this unsure of is worth telling the reader about. Chosen
# from the measured distribution: a clean render scores ~96 mean, and genuine
# misreads cluster well below 60.
LOW_CONFIDENCE_WORD = 60

# Below this mean confidence the page was not really read, whatever it returned.
MIN_PAGE_CONFIDENCE = 45

# Tesseract emits -1 for whitespace rows in the TSV; those are not words.
_NO_CONFIDENCE = -1

SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/tiff", "image/bmp", "image/webp"}


class OcrUnavailable(RuntimeError):
    """Raised when the OCR toolchain is not installed on this machine."""


@dataclass
class OcrWord:
    text: str
    confidence: float
    page: int
    left: int
    top: int
    width: int
    height: int
    start: int
    end: int

    @property
    def box(self) -> Tuple[int, int, int, int]:
        """(left, top, right, bottom), the form PIL's crop takes."""
        return (self.left, self.top, self.left + self.width, self.top + self.height)


@dataclass
class OcrResult:
    text: str = ""
    words: List[OcrWord] = field(default_factory=list)
    page_offsets: List[int] = field(default_factory=list)
    page_confidences: List[float] = field(default_factory=list)
    page_count: int = 0
    unreadable_pages: List[int] = field(default_factory=list)

    @property
    def mean_confidence(self) -> float:
        if not self.words:
            return 0.0
        return sum(w.confidence for w in self.words) / len(self.words)

    @property
    def low_confidence_words(self) -> List[OcrWord]:
        return [w for w in self.words if w.confidence < LOW_CONFIDENCE_WORD]

    def words_in(self, start: int, end: int) -> List[OcrWord]:
        """Every word overlapping a character span."""
        return [w for w in self.words if w.start < end and w.end > start]

    def word_payload(self) -> List[Dict[str, Any]]:
        """The word map in a form that survives into the graph state."""
        return [
            {
                "s": w.start, "e": w.end, "p": w.page, "l": w.left, "t": w.top,
                "w": w.width, "h": w.height, "c": round(w.confidence, 1),
            }
            for w in self.words
        ]

    def locate(self, start: int, end: int) -> Optional[Dict[str, Any]]:
        """The page and pixel region a character span was read from.

        This is what lets a finding be shown against the scan itself. Without it
        the reader has only our transcription to go on, which is exactly what
        OCR makes unsafe to assume.
        """
        covering = self.words_in(start, end)
        if not covering:
            return None
        page = covering[0].page
        on_page = [w for w in covering if w.page == page]
        confidences = [w.confidence for w in on_page]
        return {
            "page": page,
            "left": min(w.left for w in on_page),
            "top": min(w.top for w in on_page),
            "right": max(w.left + w.width for w in on_page),
            "bottom": max(w.top + w.height for w in on_page),
            "min_confidence": min(confidences),
            "mean_confidence": sum(confidences) / len(confidences),
            "spans_pages": len({w.page for w in covering}) > 1,
        }

    def to_payload(self) -> Dict[str, Any]:
        low = self.low_confidence_words
        return {
            "mean_confidence": round(self.mean_confidence, 1),
            "word_count": len(self.words),
            "low_confidence_words": len(low),
            "page_confidences": [round(c, 1) for c in self.page_confidences],
            "unreadable_pages": self.unreadable_pages,
        }


def is_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _require():
    if not is_available():
        raise OcrUnavailable(
            "OCR is not available on this machine. Install the tesseract binary "
            "(macOS: `brew install tesseract`; Debian: `apt install tesseract-ocr`) "
            "to review scanned documents."
        )


def _prepare(image):
    """Modest, reversible preprocessing.

    Grayscale and an autocontrast stretch help tesseract on the faint, unevenly
    lit output a phone camera or a cheap flatbed produces. Nothing here is
    aggressive: heavy binarisation and denoising routinely destroy thin strokes
    and cost more accuracy than they win, and tesseract does its own thresholding.
    """
    from PIL import ImageOps

    prepared = image.convert("L")
    prepared = ImageOps.autocontrast(prepared, cutoff=1)
    return prepared


def _deskew(image):
    """Rotate a page tesseract reports as turned.

    Only whole-quarter rotations, which is what a page fed in sideways produces
    and what OSD detects reliably. Fine skew correction is left alone: tesseract
    tolerates a few degrees, and resampling a scan to fix it blurs the glyphs.
    """
    import pytesseract

    try:
        osd = pytesseract.image_to_osd(image, output_type=pytesseract.Output.DICT)
    except Exception:
        return image
    rotation = int(osd.get("rotate", 0) or 0)
    if rotation % 90 or rotation == 0:
        return image
    if float(osd.get("orientation_conf", 0) or 0) < 1.0:
        return image
    return image.rotate(-rotation, expand=True)


def _ocr_page(image, page_number: int, base_offset: int):
    """One page to text plus positioned words.

    Blocks, paragraphs and lines are rebuilt from the TSV rather than taking
    tesseract's flat string, because the clause segmenter looks for markers at
    line starts -- output emitted as one long line segments into nothing at all.
    """
    import pytesseract

    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)

    lines: Dict[Tuple[int, int, int], List[int]] = {}
    for index, text in enumerate(data["text"]):
        if not text or not text.strip():
            continue
        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError):
            continue
        if confidence == _NO_CONFIDENCE:
            continue
        key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
        lines.setdefault(key, []).append(index)

    pieces: List[str] = []
    words: List[OcrWord] = []
    cursor = base_offset
    previous_paragraph: Optional[Tuple[int, int]] = None

    for key in sorted(lines):
        block, paragraph, _line = key
        if previous_paragraph is not None:
            # A blank line between paragraphs, a single newline between lines:
            # this is the structure clause segmentation reads.
            separator = "\n\n" if (block, paragraph) != previous_paragraph else "\n"
            pieces.append(separator)
            cursor += len(separator)
        previous_paragraph = (block, paragraph)

        for position, index in enumerate(lines[key]):
            if position:
                pieces.append(" ")
                cursor += 1
            text = data["text"][index]
            words.append(OcrWord(
                text=text,
                confidence=float(data["conf"][index]),
                page=page_number,
                left=int(data["left"][index]),
                top=int(data["top"][index]),
                width=int(data["width"][index]),
                height=int(data["height"][index]),
                start=cursor,
                end=cursor + len(text),
            ))
            pieces.append(text)
            cursor += len(text)

    return "".join(pieces), words


def _render_pdf(data: bytes, dpi: int) -> List[Any]:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(io.BytesIO(data))
    try:
        scale = dpi / _PDF_POINTS_PER_INCH
        return [document[i].render(scale=scale).to_pil() for i in range(len(document))]
    finally:
        # The pages are already materialised as PIL images; holding the handle
        # open leaks it and pdfium complains on exit.
        document.close()


def ocr_images(images: Sequence[Any]) -> OcrResult:
    """Read already-rendered pages."""
    _require()

    result = OcrResult(page_count=len(images))
    parts: List[str] = []
    cursor = 0

    for number, image in enumerate(images, start=1):
        prepared = _prepare(_deskew(image))
        text, words = _ocr_page(prepared, number, cursor)

        confidence = (sum(w.confidence for w in words) / len(words)) if words else 0.0
        result.page_confidences.append(confidence)
        if not words or confidence < MIN_PAGE_CONFIDENCE:
            result.unreadable_pages.append(number)

        result.page_offsets.append(cursor)
        parts.append(text)
        result.words.extend(words)
        cursor += len(text)

        if number < len(images):
            parts.append("\n\n")
            cursor += 2

    result.text = "".join(parts)
    return result


def ocr_pdf(data: bytes, dpi: int = TARGET_DPI) -> OcrResult:
    _require()
    return ocr_images(_render_pdf(data, dpi))


def ocr_image_bytes(data: bytes) -> OcrResult:
    """Read a photograph or a scan saved as an image rather than a PDF."""
    _require()
    from PIL import Image

    return ocr_images([Image.open(io.BytesIO(data))])


def locate_in_words(words: Sequence[Dict[str, Any]], start: int, end: int):
    """`OcrResult.locate` over the compact persisted form."""
    covering = [w for w in words if w["s"] < end and w["e"] > start]
    if not covering:
        return None
    page = covering[0]["p"]
    on_page = [w for w in covering if w["p"] == page]
    confidences = [w["c"] for w in on_page]
    return {
        "page": page,
        "left": min(w["l"] for w in on_page),
        "top": min(w["t"] for w in on_page),
        "right": max(w["l"] + w["w"] for w in on_page),
        "bottom": max(w["t"] + w["h"] for w in on_page),
        "min_confidence": min(confidences),
        "mean_confidence": sum(confidences) / len(confidences),
        "spans_pages": len({w["p"] for w in covering}) > 1,
    }


def render_crop(
    data: bytes, media_type: str, page: int, box: Tuple[int, int, int, int],
    dpi: int = TARGET_DPI, pad: int = 10, max_width: int = 850,
) -> bytes:
    """The region of the original scan a finding was read from, as a JPEG.

    Textual grounding is weaker once the text is a transcription, so the review
    shows the paper instead of asking the reader to take our word for it.
    """
    from PIL import Image

    if media_type == "application/pdf":
        images = _render_pdf(data, dpi)
    else:
        images = [Image.open(io.BytesIO(data))]
    if not 1 <= page <= len(images):
        raise IndexError(f"page {page} outside 1..{len(images)}")

    image = images[page - 1]
    left, top, right, bottom = box
    cropped = image.crop((
        max(0, left - pad),
        max(0, top - pad),
        min(image.width, right + pad),
        min(image.height, bottom + pad),
    ))
    # Rendered at 300 DPI a two-line crop is over 100 KB, which is far too much
    # to carry in a review payload alongside a dozen others. Downscaled it stays
    # entirely legible at a fraction of the size.
    if cropped.width > max_width:
        height = max(1, round(cropped.height * max_width / cropped.width))
        cropped = cropped.resize((max_width, height), Image.LANCZOS)

    # JPEG, not PNG: the crop is evidence for a human eye, and scanner noise is
    # close to incompressible losslessly -- the same region costs ~64 KB as PNG
    # and a few KB here, with no loss a reader would notice.
    buffer = io.BytesIO()
    cropped.convert("L").save(buffer, format="JPEG", quality=68, optimize=True)
    return buffer.getvalue()
