"""Tests for the deterministic contract-review spine.

Parsing, segmentation, red-flag rules and gap detection run without an LLM, so
they are fully testable -- and they are the layer every later stage trusts. A
clause boundary in the wrong place mis-attributes a finding; an offset that
drifts makes a quote unverifiable. Both are checked here rather than left for a
model to paper over.
"""

import io

import pytest

from src.core.clause_checklists import find_missing_clauses
from src.core.clause_segmenter import classify_clause, segment_clauses
from src.core.document_parser import (
    DocumentParseError,
    media_type_for,
    normalize,
    page_for_offset,
    parse_document,
)
from src.core.pattern_utils import whitespace_tolerant
from src.core.red_flag_rules import RULES, evaluate_clauses, verify_quotes
from src.schemas.contract import (
    ClauseCategory,
    ContractType,
    PartyPosition,
    Severity,
)

FIXTURES = {
    "employment": "tests/fixtures/employment_agreement.txt",
    "rental": "tests/fixtures/rental_agreement.txt",
}


def load(name):
    with open(FIXTURES[name], "rb") as handle:
        return parse_document(handle.read(), f"{name}.txt")


@pytest.fixture(scope="module")
def employment():
    document = load("employment")
    return document, segment_clauses(document)


@pytest.fixture(scope="module")
def rental():
    document = load("rental")
    return document, segment_clauses(document)


# ---------------------------------------------------------------------------
# Document parsing
# ---------------------------------------------------------------------------

def test_normalize_joins_a_hyphenated_word_across_a_line_break_keeping_the_hyphen():
    """The newline goes, the hyphen stays.

    Dropping it produced "twentyfour months" and "interestfree deposit" in the
    evidence quoted back to the reader, because contracts break exactly those
    compounds at line ends. Leaving a genuine syllable break as "termi-nation"
    needs the producer to hyphenate mid-word, which Word does not do by default.
    """
    assert normalize("twenty-\nfour months") == "twenty-four months"
    assert normalize("interest-\nfree deposit") == "interest-free deposit"


def test_normalize_keeps_genuine_hyphenated_compounds():
    """Only a lowercase-to-lowercase break is a typesetter's wrap."""
    assert normalize("Non-\nDisclosure") == "Non-\nDisclosure"


def test_normalize_collapses_horizontal_runs_but_keeps_paragraphs():
    assert normalize("a  \t b\n\n\n\nc") == "a b\n\nc"


def test_media_type_prefers_the_extension_over_the_declared_type():
    """Browsers routinely send octet-stream for .docx."""
    assert media_type_for("x.docx", "application/octet-stream").endswith(
        "wordprocessingml.document"
    )


def test_unsupported_extension_is_refused():
    with pytest.raises(DocumentParseError, match="Unsupported file type"):
        media_type_for("contract.pages")


def test_a_scanned_pdf_is_refused_rather_than_reviewed():
    """A PDF with no text layer segments into zero clauses, which would render
    as a clean review of a contract nobody read."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)

    with pytest.raises(DocumentParseError, match="scan or an image"):
        parse_document(buffer.getvalue(), "scan.pdf")


def test_too_little_text_is_refused():
    with pytest.raises(DocumentParseError, match="too little to review"):
        parse_document(b"Agreement between two parties.", "tiny.txt")


def test_empty_upload_is_refused():
    with pytest.raises(DocumentParseError, match="empty"):
        parse_document(b"", "empty.txt")


def test_page_for_offset_is_none_without_pagination(employment):
    document, _ = employment
    assert page_for_offset(document, 10) is None


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------

def test_numbered_contract_segments_into_its_clauses(employment):
    _, clauses = employment
    numbered = [c.number for c in clauses if c.number]
    assert numbered == [str(n) for n in range(1, 12)]


def test_the_text_before_the_first_clause_is_kept(employment):
    """The title, recitals and definition of the parties used to be discarded
    outright, so a waiver buried in the recitals reached no rule at all."""
    document, clauses = employment
    preamble = clauses[0]
    assert preamble.number is None
    assert preamble.start_offset == 0
    assert "EMPLOYMENT AGREEMENT" in preamble.text
    assert document.text[preamble.start_offset : preamble.end_offset] == preamble.text


def test_every_clause_offset_round_trips_to_its_own_text(employment):
    """Offsets are the anchor for every quote, highlight and citation."""
    document, clauses = employment
    for clause in clauses:
        assert document.text[clause.start_offset : clause.end_offset] == clause.text


def test_body_offset_lands_past_the_number_and_heading(employment):
    document, clauses = employment
    termination = next(c for c in clauses if c.number == "5")
    body = document.text[termination.body_offset : termination.end_offset]
    assert body.startswith("The Company may terminate")
    assert "TERMINATION" not in body.split("\n")[0]


def test_hyphenated_headings_survive_intact(employment):
    """'NON-COMPETITION' must not be read as the heading 'NON'."""
    _, clauses = employment
    assert next(c for c in clauses if c.number == "8").heading == "NON-COMPETITION"


def test_clauses_are_contiguous_and_ordered(employment):
    _, clauses = employment
    for earlier, later in zip(clauses, clauses[1:]):
        assert earlier.end_offset <= later.start_offset


def test_unnumbered_text_falls_back_to_paragraphs():
    text = (
        "This letter confirms your engagement as a consultant with effect from "
        "1 June 2025 on the terms set out below.\n\n"
        "You will be paid a fee of Rs. 90,000 per month, payable within fifteen "
        "days of receipt of your invoice for the preceding month.\n\n"
        "Either party may end this engagement by giving the other thirty days "
        "written notice, and no reason need be given for doing so.\n\n"
        "You shall keep confidential all information of the company that comes to "
        "your knowledge during the engagement and after it ends."
    )
    document = parse_document(text.encode(), "letter.txt")
    clauses = segment_clauses(document)
    assert len(clauses) == 4
    assert all(c.number is None for c in clauses)
    assert all(document.text[c.start_offset : c.end_offset] == c.text for c in clauses)


def test_a_number_inside_a_clause_body_does_not_split_it():
    """Real top-level numbering only moves forward, and by small steps."""
    text = (
        "1. PAYMENT\nThe fee is payable within thirty days of the invoice date, "
        "and shall be paid by electronic transfer to the account nominated in "
        "writing by the consultant from time to time.\n"
        "2. NOTICE\nEither party may terminate on thirty days written notice to "
        "the other party at the address stated above, and 9. of the Schedule "
        "shall then apply to any amounts outstanding on the date of termination.\n"
        "3. GOVERNING LAW\nThis agreement is governed by the laws of India and "
        "the courts at Mumbai shall have jurisdiction over any dispute."
    )
    document = parse_document(text.encode(), "c.txt")
    assert [c.number for c in segment_clauses(document)] == ["1", "2", "3"]


def test_term_and_termination_are_not_confused():
    """'\\bterm\\b' cannot match inside 'termination', which keeps the two apart
    -- and a contract wrongly read as having no TERM clause gets a false gap."""
    category, _ = classify_clause(
        "This Agreement shall remain in force with effect from 15 April 2025 "
        "until terminated in accordance with the provisions herein.",
        "APPOINTMENT AND TERM",
    )
    assert category is ClauseCategory.TERM


def test_classification_reports_the_terms_that_decided_it(employment):
    _, clauses = employment
    confidentiality = next(c for c in clauses if c.number == "6")
    assert confidentiality.category is ClauseCategory.CONFIDENTIALITY
    assert confidentiality.category_matched_terms


# ---------------------------------------------------------------------------
# Line wrapping
# ---------------------------------------------------------------------------

def test_patterns_tolerate_a_wrap_mid_phrase():
    """A PDF wraps mid-phrase constantly; a pattern written with a plain space
    would fail silently on exactly the clause it was written for."""
    import re

    assert re.search(whitespace_tolerant("whether or not"), "whether\nor not")


def test_whitespace_tolerance_leaves_character_classes_alone():
    assert whitespace_tolerant(r"non[- ]?compete here") == r"non[- ]?compete\s+here"


def test_a_wrapped_clause_still_raises_its_red_flag():
    wrapped = (
        "1. INTELLECTUAL PROPERTY\nThe Employee assigns to the Company all\n"
        "intellectual property and inventions created during the term of\n"
        "employment, whether or not related to the business of the Company.\n"
        "2. PAYMENT\nSalary is payable monthly in arrears on the seventh day of "
        "the succeeding calendar month, subject to statutory deduction.\n"
        "3. NOTICE\nEither party may terminate this agreement by giving the "
        "other party thirty days written notice in that behalf."
    )
    document = parse_document(wrapped.encode(), "wrapped.txt")
    findings = evaluate_clauses(segment_clauses(document), PartyPosition.EMPLOYEE)
    assert "BROAD_IP_ASSIGNMENT" in {f.rule_id for f in findings}


# ---------------------------------------------------------------------------
# Red-flag rules
# ---------------------------------------------------------------------------

def test_rule_ids_are_unique():
    ids = [rule.rule_id for rule in RULES]
    assert len(ids) == len(set(ids))


def test_employment_contract_raises_its_known_red_flags(employment):
    _, clauses = employment
    fired = {f.rule_id for f in evaluate_clauses(clauses, PartyPosition.EMPLOYEE)}
    assert {
        "NON_COMPETE_POST_TERM",
        "EMPLOYMENT_BOND",
        "UNILATERAL_ARBITRATOR",
        "UNILATERAL_TERMINATION",
        "BROAD_IP_ASSIGNMENT",
        "PERPETUAL_CONFIDENTIALITY",
    } <= fired


def test_lease_raises_its_known_red_flags(rental):
    _, clauses = rental
    fired = {f.rule_id for f in evaluate_clauses(clauses, PartyPosition.TENANT)}
    assert {
        "EXCESSIVE_SECURITY_DEPOSIT",
        "LOCK_IN_WITHOUT_EXIT",
        "PENALTY_STIPULATION",
        "AUTO_RENEWAL",
        "OUSTER_OF_LEGAL_REMEDY",
        "UNILATERAL_ARBITRATOR",
    } <= fired


def test_the_non_compete_cites_the_provision_that_voids_it(employment):
    """Retrieval cannot find s.27 from contract wording, so the rule carries it."""
    _, clauses = employment
    finding = next(
        f
        for f in evaluate_clauses(clauses, PartyPosition.EMPLOYEE)
        if f.rule_id == "NON_COMPETE_POST_TERM"
    )
    assert [(c.section_number) for c in finding.citations] == ["Section 27"]
    assert "Contract Act" in finding.citations[0].act


def test_severity_depends_on_which_side_you_are_on(employment):
    """The same contract is a different document to each party."""
    _, clauses = employment
    as_employee = {
        f.rule_id: f.severity for f in evaluate_clauses(clauses, PartyPosition.EMPLOYEE)
    }
    as_employer = {
        f.rule_id: f.severity for f in evaluate_clauses(clauses, PartyPosition.EMPLOYER)
    }
    assert as_employee["BROAD_IP_ASSIGNMENT"] is Severity.CRITICAL
    assert as_employer["BROAD_IP_ASSIGNMENT"] is Severity.INFO


def test_an_unenforceable_clause_is_still_reported_to_the_side_it_favours(employment):
    """Planning around a protection that would not survive a challenge is its
    own risk, so a void term is never demoted all the way to noise."""
    _, clauses = employment
    as_employer = {
        f.rule_id: f.severity for f in evaluate_clauses(clauses, PartyPosition.EMPLOYER)
    }
    assert as_employer["NON_COMPETE_POST_TERM"] is Severity.MEDIUM


def test_an_unknown_position_reports_everything_at_base_severity(employment):
    _, clauses = employment
    findings = evaluate_clauses(clauses, PartyPosition.UNKNOWN)
    assert all(f.severity is not Severity.INFO for f in findings)


def test_findings_are_ordered_worst_first(employment):
    from src.schemas.contract import SEVERITY_ORDER

    _, clauses = employment
    findings = evaluate_clauses(clauses, PartyPosition.EMPLOYEE)
    ranks = [SEVERITY_ORDER[f.severity] for f in findings]
    assert ranks == sorted(ranks, reverse=True)


@pytest.mark.parametrize("name,position", [
    ("employment", PartyPosition.EMPLOYEE),
    ("rental", PartyPosition.TENANT),
])
def test_every_quote_is_really_in_the_document(name, position):
    """The guarantee the whole feature rests on: a finding quotes the contract."""
    document = load(name)
    findings = evaluate_clauses(segment_clauses(document), position)
    assert findings
    assert verify_quotes(findings, document.text) == []


def test_verify_quotes_catches_a_quote_that_does_not_match():
    document = load("employment")
    findings = evaluate_clauses(segment_clauses(document), PartyPosition.EMPLOYEE)
    findings[0].matched_quote = "a term that was never in this contract"
    assert verify_quotes(findings, document.text)


def test_a_capped_indemnity_is_not_flagged_as_uncapped():
    text = (
        "1. INDEMNITY\nThe Supplier shall indemnify the Customer against any and "
        "all claims arising out of the Services, provided that the Supplier's "
        "total aggregate liability under this indemnity shall not exceed the "
        "fees paid in the preceding twelve months.\n"
        "2. TERM\nThis agreement commences on 1 April 2025 and continues for "
        "twelve months unless terminated earlier in accordance with clause 3.\n"
        "3. NOTICE\nEither party may terminate on sixty days written notice to "
        "the other party, given in writing at the address stated above."
    )
    document = parse_document(text.encode(), "capped.txt")
    findings = evaluate_clauses(segment_clauses(document), PartyPosition.SERVICE_PROVIDER)
    assert "UNCAPPED_INDEMNITY" not in {f.rule_id for f in findings}


# ---------------------------------------------------------------------------
# Missing clauses
# ---------------------------------------------------------------------------

def test_a_gap_the_contract_really_has_is_reported(rental):
    _, clauses = rental
    missing = find_missing_clauses(clauses, ContractType.LEASE, PartyPosition.TENANT)
    assert ClauseCategory.MAINTENANCE in {m.category for m in missing}


def test_a_covered_requirement_is_not_reported_as_missing(rental):
    _, clauses = rental
    missing = {m.category for m in find_missing_clauses(clauses, ContractType.LEASE)}
    assert ClauseCategory.SECURITY_DEPOSIT not in missing
    assert ClauseCategory.TERMINATION not in missing


def test_an_alternative_clause_satisfies_the_requirement(employment):
    """A termination clause answers the notice-period requirement."""
    _, clauses = employment
    missing = {
        m.category
        for m in find_missing_clauses(clauses, ContractType.EMPLOYMENT)
    }
    assert ClauseCategory.NOTICE_PERIOD not in missing


def test_a_gap_matters_more_to_the_side_that_did_not_draft_it():
    document = parse_document(
        (
            "1. SERVICES\nThe Consultant shall provide software development "
            "services to the Client as described in the statement of work.\n"
            "2. FEES\nThe Client shall pay the Consultant Rs. 2,00,000 per month "
            "within thirty days of receipt of a valid invoice.\n"
            "3. TERM\nThis agreement commences on 1 May 2025 and continues until "
            "completion of the services described in the statement of work."
        ).encode(),
        "services.txt",
    )
    clauses = segment_clauses(document)
    provider = {
        m.category: m.severity
        for m in find_missing_clauses(
            clauses, ContractType.SERVICE, PartyPosition.SERVICE_PROVIDER
        )
    }
    client = {
        m.category: m.severity
        for m in find_missing_clauses(clauses, ContractType.SERVICE, PartyPosition.CLIENT)
    }
    assert provider[ClauseCategory.CONFIDENTIALITY] is Severity.HIGH
    assert client[ClauseCategory.CONFIDENTIALITY] is Severity.MEDIUM


def test_missing_clause_findings_carry_their_citations():
    document = parse_document(
        (
            "1. SERVICES\nThe Vendor shall supply the goods described in the "
            "schedule to this agreement at the times stated in that schedule.\n"
            "2. PRICE\nThe Buyer shall pay the price stated in the schedule "
            "within forty five days of delivery of the goods to its warehouse.\n"
            "3. TERM\nThis agreement commences on signature and continues for a "
            "period of twenty four months from that date."
        ).encode(),
        "vendor.txt",
    )
    missing = find_missing_clauses(
        segment_clauses(document), ContractType.VENDOR, PartyPosition.CLIENT
    )
    cited = [m for m in missing if m.citations]
    assert cited, "at least the data-protection and force-majeure gaps carry citations"


# ---------------------------------------------------------------------------
# DOCX extraction
# ---------------------------------------------------------------------------

def _docx_bytes(paragraphs, table_rows=None):
    import docx

    document = docx.Document()
    for text in paragraphs:
        document.add_paragraph(text)
    if table_rows:
        table = document.add_table(rows=len(table_rows), cols=len(table_rows[0]))
        for row_index, row in enumerate(table_rows):
            for cell_index, value in enumerate(row):
                table.cell(row_index, cell_index).text = value
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_docx_paragraphs_are_extracted():
    data = _docx_bytes([
        "1. SERVICES",
        "The Consultant shall provide the services described in the schedule to "
        "this agreement at the times stated in that schedule.",
        "2. TERM",
        "This agreement commences on 1 May 2025 and continues for twelve months "
        "unless terminated earlier under clause 3 of this agreement.",
        "3. NOTICE",
        "Either party may terminate on thirty days written notice given to the "
        "other party at the address stated above in this agreement.",
    ])
    document = parse_document(data, "services.docx")
    assert "Consultant shall provide" in document.text
    assert len(segment_clauses(document)) == 3


def test_docx_tables_are_extracted():
    """`document.paragraphs` skips tables, and contracts put rent, payment
    schedules and notice periods in them constantly."""
    data = _docx_bytes(
        [
            "RENTAL AGREEMENT",
            "This agreement is made between the Lessor and the Lessee on the terms "
            "set out in this document and in the schedule below.",
            "1. RENT",
            "The Lessee shall pay the rent stated in the schedule below on or "
            "before the fifth day of each calendar month without demand.",
            "2. TERM",
            "This agreement commences on 15 March 2025 and continues for eleven "
            "months from that date unless terminated earlier.",
        ],
        table_rows=[
            ["Particulars", "Amount"],
            ["Monthly rent", "Rs. 32,000"],
            ["Security deposit", "Rs. 3,20,000 (ten months rent), non-refundable"],
        ],
    )
    document = parse_document(data, "rent.docx")
    assert "Security deposit" in document.text
    assert "3,20,000" in document.text


def test_a_red_flag_stated_only_in_a_table_is_still_found():
    """The whole point of reading tables: the dangerous term is often only there."""
    data = _docx_bytes(
        [
            "RENTAL AGREEMENT",
            "This agreement is made between the Lessor and the Lessee on the terms "
            "set out in this document and in the schedule below.",
            "1. RENT",
            "The Lessee shall pay the rent stated in the schedule on or before the "
            "fifth day of each calendar month without any demand being made.",
            "2. TERM",
            "This agreement commences on 15 March 2025 and continues for eleven "
            "months from that date unless terminated earlier by either party.",
        ],
        table_rows=[
            ["Particulars", "Amount"],
            [
                "Security deposit",
                "An interest-free security deposit equivalent to ten months rent, "
                "which shall stand forfeited if the Lessee vacates early",
            ],
        ],
    )
    document = parse_document(data, "rent.docx")
    findings = evaluate_clauses(segment_clauses(document), PartyPosition.TENANT)
    assert "EXCESSIVE_SECURITY_DEPOSIT" in {f.rule_id for f in findings}
    assert verify_quotes(findings, document.text) == []


# ---------------------------------------------------------------------------
# Ruleset coverage
# ---------------------------------------------------------------------------

ALL_FIXTURES = [
    ("employment_agreement", PartyPosition.EMPLOYEE),
    ("rental_agreement", PartyPosition.TENANT),
    ("saas_services_agreement", PartyPosition.CLIENT),
]


def _fire_all():
    fired = set()
    for name, position in ALL_FIXTURES:
        with open(f"tests/fixtures/{name}.txt", "rb") as handle:
            document = parse_document(handle.read(), f"{name}.txt")
        findings = evaluate_clauses(segment_clauses(document), position)
        assert verify_quotes(findings, document.text) == [], name
        fired |= {f.rule_id for f in findings}
    return fired


def test_every_rule_has_a_fixture_that_trips_it():
    """A rule with no positive fixture is an untested rule, and a rule that never
    fires is indistinguishable from a clean contract. Two real misses were found
    exactly this way: a lease saying "Lessor" and a SaaS agreement saying
    "Provider", neither matched by the party list at the time."""
    missing = {rule.rule_id for rule in RULES} - _fire_all()
    assert not missing, f"rules with no fixture coverage: {sorted(missing)}"


def test_saas_agreement_raises_its_known_red_flags():
    with open("tests/fixtures/saas_services_agreement.txt", "rb") as handle:
        document = parse_document(handle.read(), "saas.txt")
    fired = {
        f.rule_id
        for f in evaluate_clauses(segment_clauses(document), PartyPosition.CLIENT)
    }
    assert {
        "UNCAPPED_INDEMNITY",
        "UNILATERAL_AMENDMENT",
        "UNFAIR_TERM_WAIVER",
        "FOREIGN_EXCLUSIVE_JURISDICTION",
        "DATA_SHARING_WITHOUT_CONSENT",
        "ONE_SIDED_ASSIGNMENT",
        "AUTO_RENEWAL",
    } <= fired


def test_one_sided_assignment_needs_both_halves_of_the_asymmetry():
    """Consent-to-assign is normal and mutual; it is only a flag when the other
    side is simultaneously free to assign."""
    mutual = (
        "1. ASSIGNMENT\nNeither party shall assign or transfer this Agreement "
        "without the prior written consent of the other party, such consent not "
        "to be unreasonably withheld or delayed.\n"
        "2. TERM\nThis agreement commences on 1 May 2025 and continues for twelve "
        "months from that date unless terminated earlier by either party.\n"
        "3. NOTICE\nEither party may terminate this agreement on sixty days "
        "written notice given to the other party at the address stated above."
    )
    document = parse_document(mutual.encode(), "mutual.txt")
    findings = evaluate_clauses(segment_clauses(document), PartyPosition.CLIENT)
    assert "ONE_SIDED_ASSIGNMENT" not in {f.rule_id for f in findings}


# ---------------------------------------------------------------------------
# Robustness to real-world drafting
# ---------------------------------------------------------------------------

def _single_clause_findings(text, position=PartyPosition.EMPLOYEE):
    from src.schemas.contract import Clause

    category, _ = classify_clause(text, None)
    clause = Clause(
        index=0,
        number="1",
        heading=None,
        text=text,
        start_offset=0,
        end_offset=len(text),
        body_offset=0,
        category=category,
    )
    from src.core.red_flag_rules import evaluate_clause

    return category, {f.rule_id for f in evaluate_clause(clause, position)}


@pytest.mark.parametrize("wording", [
    # Verbose commercial drafting: ~95 characters separate the restraint verb
    # from "compete". A tight pattern gap made this fail silently, which reads
    # exactly like a clean contract.
    "The Employee shall not engage in any activity whatsoever which may in the "
    "reasonable opinion of the Company be considered to compete with or be "
    "prejudicial to the interests of the Company for a period of two years "
    "after the termination of employment",
    "The Employee shall not join a competing business for 24 months after "
    "termination of employment",
    "The Employee shall not accept employment with any competing firm for one "
    "year following resignation",
    "The Employee shall not join any competitor of the Company for twelve "
    "months after separation",
    "The Employee shall not set up any similar business within Bengaluru for "
    "eighteen months after leaving the Company",
    "The Consultant shall not render services to any competing business for one "
    "year following cessation of this engagement",
])
def test_post_term_non_compete_survives_drafting_variation(wording):
    """The most consequential rule in the set, so it must not depend on one
    phrasing. Indian law voids these outright under Contract Act s.27."""
    category, fired = _single_clause_findings(wording)
    assert category is ClauseCategory.NON_COMPETE
    assert "NON_COMPETE_POST_TERM" in fired


@pytest.mark.parametrize("wording", [
    # Restraint only during the term is lawful -- s.27 bites on restraints that
    # operate after the contract ends.
    "The Employee shall not engage in any competing business during the term of "
    "employment and shall devote full time to the Company",
    # Confidentiality surviving termination is not a restraint of trade.
    "The Employee shall not disclose confidential information after the "
    "termination of employment for any purpose whatsoever",
    "The Employee shall keep confidential all information and shall not disclose "
    "it to competitors of the Company at any time after termination",
])
def test_a_lawful_restraint_is_not_flagged_as_a_non_compete(wording):
    _, fired = _single_clause_findings(wording)
    assert "NON_COMPETE_POST_TERM" not in fired


def test_the_ruleset_is_fast_enough_for_a_long_contract():
    """120 clauses is a realistic long agreement. The rules use nested bounded
    gaps, which are exactly the shape that backtracks catastrophically."""
    import time

    parts = []
    for index in range(1, 121):
        parts.append(
            f"{index}. CLAUSE {index}\nThe parties agree that the provisions of "
            f"this clause {index} shall apply to all matters arising under this "
            "agreement and shall be binding upon their successors in title."
        )
    document = parse_document("\n\n".join(parts).encode(), "long.txt")
    clauses = segment_clauses(document)
    assert len(clauses) == 120

    started = time.perf_counter()
    evaluate_clauses(clauses, PartyPosition.EMPLOYEE)
    assert time.perf_counter() - started < 2.0


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------

def _pdf_bytes(lines):
    """Build a PDF carrying a genuine text layer.

    Written rather than committed as a binary fixture so the input is readable
    and the test says what it is testing.
    """
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    page = writer.pages[0]

    escaped = [line.replace("(", "").replace(")", "") for line in lines]
    content = (
        "BT /F1 11 Tf 50 780 Td 14 TL\n"
        + "\n".join(f"({line}) Tj T*" for line in escaped)
        + "\nET"
    )
    stream = DecodedStreamObject()
    stream.set_data(content.encode())
    page[NameObject("/Contents")] = writer._add_object(stream)

    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
    })

    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


CONSULTANCY_PDF_LINES = [
    "1. SERVICES",
    "The Consultant shall provide software development services to the",
    "Client as described in the statement of work attached hereto.",
    "2. NON-COMPETITION",
    "The Consultant shall not, for a period of twenty four months after the",
    "termination of this agreement, engage in or be employed by any competing",
    "business anywhere in India.",
    "3. FEES",
    "The Client shall pay Rs. 2,00,000 per month within thirty days of receipt",
    "of a valid invoice from the Consultant for the preceding month.",
    "4. TERM",
    "This agreement commences on 1 May 2025 and continues for twelve months.",
]


def test_a_pdf_with_a_text_layer_is_read_and_segmented():
    document = parse_document(_pdf_bytes(CONSULTANCY_PDF_LINES), "consultancy.pdf")
    assert document.page_count == 1
    clauses = segment_clauses(document)
    assert [c.number for c in clauses] == ["1", "2", "3", "4"]


def test_pdf_offsets_round_trip_like_every_other_format():
    document = parse_document(_pdf_bytes(CONSULTANCY_PDF_LINES), "consultancy.pdf")
    for clause in segment_clauses(document):
        assert document.text[clause.start_offset : clause.end_offset] == clause.text


def test_a_red_flag_in_a_pdf_is_found_and_its_quote_verifies():
    """The line wrapping a PDF introduces is exactly what defeated these
    patterns before `whitespace_tolerant` existed."""
    document = parse_document(_pdf_bytes(CONSULTANCY_PDF_LINES), "consultancy.pdf")
    findings = evaluate_clauses(
        segment_clauses(document), PartyPosition.SERVICE_PROVIDER
    )
    assert "NON_COMPETE_POST_TERM" in {f.rule_id for f in findings}
    assert verify_quotes(findings, document.text) == []


def test_pages_are_tracked_across_a_multi_page_pdf():
    from src.core.document_parser import page_for_offset

    document = parse_document(_pdf_bytes(CONSULTANCY_PDF_LINES), "consultancy.pdf")
    assert page_for_offset(document, 0) == 1
    assert page_for_offset(document, len(document.text) - 1) == 1
