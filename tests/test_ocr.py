"""Reviewing a scan, and being honest that it is one.

A scan has no text layer, so before this the parser refused it -- an empty
extraction segments into zero clauses and every rule matches nothing, which
renders as a clean contract nobody read.

OCR removes that refusal but weakens the guarantee everything else rests on.
Elsewhere "this finding quotes the document" is exact. Here the text is our
reading of an image, so a quote verifies against a transcription that may have
misread the paper, and verification becomes circular. These tests pin the three
things that make the feature honest rather than merely working: the review is
labelled as OCR, confidence is capped by how well the page was read, and every
finding carries the region of the scan it came from.
"""

import functools
import io

import pytest

from src.core import ocr
from src.core.clause_segmenter import segment_clauses
from src.core.contract_confidence import (
    OCR_MIN_CAP,
    OCR_SOURCE_CAP,
    estimate_contract_confidence,
    text_fidelity,
)
from src.core.document_parser import DocumentParseError, parse_document
from src.core.red_flag_rules import evaluate_clauses, verify_quotes
from src.schemas.contract import PartyPosition

SCAN = "samples/09_scanned_employment.pdf"
PHOTO = "samples/10_photo_of_contract.png"
ORIGINAL = "samples/01_employment_loaded.pdf"

needs_ocr = pytest.mark.skipif(not ocr.is_available(), reason="tesseract not installed")
needs_samples = pytest.mark.skipif(
    not __import__("pathlib").Path(SCAN).exists(),
    reason="run scripts/generate_sample_contracts.py first",
)


@functools.lru_cache(maxsize=8)
def _read(path):
    """Cached: OCR of a two-page scan takes seconds, and these tests all read
    the same few files."""
    with open(path, "rb") as handle:
        return parse_document(handle.read(), path.split("/")[-1])


def _rules(document, position=PartyPosition.EMPLOYEE):
    return {f.rule_id for f in evaluate_clauses(segment_clauses(document), position)}


# ---------------------------------------------------------------------------
# Fidelity: the score must track how well the page was read
# ---------------------------------------------------------------------------

def test_text_lifted_from_a_file_is_perfectly_faithful():
    assert text_fidelity("text_layer", None) == 1.0


@pytest.mark.parametrize("confidence,expected", [(100.0, 1.0), (55.0, 0.25), (40.0, 0.25)])
def test_fidelity_tracks_ocr_confidence(confidence, expected):
    assert text_fidelity("ocr", confidence) == pytest.approx(expected, abs=0.01)


def test_fidelity_falls_as_confidence_falls():
    scores = [text_fidelity("ocr", c) for c in (100, 90, 80, 70, 60)]
    assert scores == sorted(scores, reverse=True)


def test_an_unmeasured_ocr_read_is_not_assumed_good():
    assert text_fidelity("ocr", None) < 1.0


# ---------------------------------------------------------------------------
# The cap
# ---------------------------------------------------------------------------

def _confidence(source, ocr_confidence, clauses, findings, text):
    return estimate_contract_confidence(
        clauses=clauses, findings=findings, document_text=text,
        analysed_indices=[c.index for c in clauses],
        position_source="USER_DECLARED", contract_type="EMPLOYMENT",
        source=source, ocr_confidence=ocr_confidence,
    )


@needs_ocr
@needs_samples
def test_an_ocr_review_can_never_score_as_well_as_the_file_itself():
    """The transcription problem does not go away on a clean scan: the dangerous
    misreads are the ones OCR is confident about, most often a digit."""
    document = _read(ORIGINAL)
    clauses = segment_clauses(document)
    findings = evaluate_clauses(clauses, PartyPosition.EMPLOYEE)

    from_file = _confidence("text_layer", None, clauses, findings, document.text)
    perfect_scan = _confidence("ocr", 100.0, clauses, findings, document.text)

    assert perfect_scan.score <= OCR_SOURCE_CAP
    assert perfect_scan.score < from_file.score
    assert any("read_by_ocr" in cap for cap in perfect_scan.caps_applied)


@needs_ocr
@needs_samples
def test_a_poor_scan_scores_below_a_clean_one():
    """A flat ceiling gave a barely-legible scan the same score as a clean one,
    because fidelity carries only a tenth of the weight."""
    document = _read(ORIGINAL)
    clauses = segment_clauses(document)
    findings = evaluate_clauses(clauses, PartyPosition.EMPLOYEE)

    scores = [
        _confidence("ocr", c, clauses, findings, document.text).score
        for c in (100.0, 85.0, 70.0, 52.0)
    ]
    assert scores == sorted(scores, reverse=True), scores
    assert scores[-1] <= OCR_MIN_CAP + 0.15


# ---------------------------------------------------------------------------
# Reading an actual scan
# ---------------------------------------------------------------------------

@needs_ocr
@needs_samples
def test_a_scan_is_read_rather_than_refused():
    document = _read(SCAN)
    assert document.source == "ocr"
    assert document.ocr_confidence > 50
    assert document.ocr_words


@needs_ocr
@needs_samples
def test_a_scan_finds_what_the_original_finds():
    """The same contract, once with a text layer and once as a skewed, noisy,
    200 DPI image. The deterministic findings must survive the round trip."""
    assert _rules(_read(SCAN)) == _rules(_read(ORIGINAL))


@needs_ocr
@needs_samples
def test_a_scan_still_segments_into_its_clauses():
    """OCR output emitted as one long line would segment into nothing, so line
    and paragraph structure is rebuilt from the word boxes."""
    numbers = [c.number for c in segment_clauses(_read(SCAN)) if c.number]
    assert numbers == [str(n) for n in range(1, 12)]


@needs_ocr
@needs_samples
def test_quotes_from_a_scan_still_verify_against_the_text():
    document = _read(SCAN)
    findings = evaluate_clauses(segment_clauses(document), PartyPosition.EMPLOYEE)
    assert findings
    assert verify_quotes(findings, document.text) == []


@needs_ocr
@needs_samples
def test_a_photograph_is_read():
    document = _read(PHOTO)
    assert document.source == "ocr"
    assert "NON_COMPETE_POST_TERM" in _rules(document)


@needs_ocr
@needs_samples
def test_the_reader_is_told_it_was_read_by_ocr():
    warnings = " ".join(_read(SCAN).extraction_warnings).lower()
    assert "ocr" in warnings and "no text layer" in warnings


# ---------------------------------------------------------------------------
# Visual grounding
# ---------------------------------------------------------------------------

@needs_ocr
@needs_samples
def test_a_character_span_maps_back_to_a_region_of_the_page():
    document = _read(SCAN)
    index = document.text.find("twenty four months")
    assert index != -1
    located = ocr.locate_in_words(document.ocr_words, index, index + 18)
    assert located is not None
    assert located["page"] >= 1
    assert located["right"] > located["left"] and located["bottom"] > located["top"]


@needs_ocr
@needs_samples
def test_the_region_renders_as_a_legible_crop():
    with open(SCAN, "rb") as handle:
        raw = handle.read()
    document = parse_document(raw, "s.pdf")
    index = document.text.find("shall not, for a period")
    located = ocr.locate_in_words(document.ocr_words, index, index + 80)
    image = ocr.render_crop(
        raw, "application/pdf", located["page"],
        (located["left"], located["top"], located["right"], located["bottom"]),
    )
    assert image.startswith(b"\xff\xd8")  # JPEG
    # Small enough to travel inside a review payload beside a dozen others.
    assert len(image) < 60_000


@needs_ocr
@needs_samples
def test_every_finding_on_a_scan_carries_its_evidence():
    """Textual grounding is circular once the text is a transcription, so the
    reader is shown the paper rather than asked to trust it."""
    import asyncio
    import contextlib
    from unittest.mock import patch

    from src.core.contract_service import review_contract
    from src.schemas.contract import ContractType

    def dead(*args, **kwargs):
        raise RuntimeError("offline")

    async def run():
        with contextlib.ExitStack() as stack:
            for module in ["profiler", "clause_classifier", "query_builder",
                           "explainer", "red_flag_analyst"]:
                stack.enter_context(
                    patch(f"src.agents.contract_nodes.{module}.ChatGroq", side_effect=dead))
            stack.enter_context(patch(
                "src.agents.contract_nodes.clause_retriever.vector_store.hybrid_search",
                side_effect=RuntimeError("no qdrant")))
            with open(SCAN, "rb") as handle:
                return await review_contract(
                    data=handle.read(), filename="scan.pdf", persist=False,
                    contract_type=ContractType.EMPLOYMENT,
                    position=PartyPosition.EMPLOYEE)

    review = asyncio.run(run())
    assert review["source"] == "ocr"
    assert review["findings"]
    for finding in review["findings"]:
        assert finding["read_confidence"] is not None
        assert finding["evidence_image"].startswith("data:image/jpeg;base64,")


# ---------------------------------------------------------------------------
# Refusals that must survive
# ---------------------------------------------------------------------------

def test_a_page_with_nothing_on_it_is_still_refused():
    """OCR removes the refusal for scans that carry text. A blank page is not
    such a case and must not start passing."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(2):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(DocumentParseError):
        parse_document(buffer.getvalue(), "blank.pdf")


def test_a_corrupt_image_is_refused_cleanly():
    """Whatever the renderer raises must reach the caller as a refusal it can
    act on, not as a 500."""
    with pytest.raises(DocumentParseError, match="Could not read"):
        parse_document(b"this is not an image" * 40, "broken.png")
