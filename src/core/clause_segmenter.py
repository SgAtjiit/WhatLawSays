"""Split a contract into clauses, deterministically.

Segmentation is the load-bearing step: every later stage addresses the contract
by clause, so a clause boundary in the wrong place silently mis-attributes a red
flag to the wrong obligation. It is therefore done with rules rather than a
model, and every clause carries offsets back into `ParsedDocument.text`.

Two passes. The first finds numbering markers ("4.", "4.1", "(a)", "Article V")
at line starts and cuts between them. The second runs only when the first finds
too little structure -- some contracts, especially offer letters and one-page
rental agreements, genuinely have no numbering -- and falls back to paragraphs.
"""

import re
from typing import Dict, List, Optional, Sequence, Tuple

from src.core.pattern_utils import compile_loose
from src.schemas.contract import Clause, ClauseCategory, ParsedDocument

# A decimal marker: 4. / 4.1 / 4.1.2 -- optionally followed by a closing paren.
_DECIMAL = re.compile(r"^[ \t]*(\d{1,3}(?:\.\d{1,3}){0,3})[.)]?[ \t]+(?=\S)", re.M)
# An alpha or roman marker in parentheses: (a) / (iv) / (2)
_PAREN = re.compile(r"^[ \t]*\(([a-zA-Z]{1,5}|\d{1,3})\)[ \t]+(?=\S)", re.M)
# A spelled-out heading: ARTICLE V / Clause 12 / SECTION 3.
_SPELLED = re.compile(
    r"^[ \t]*(?:(?:ARTICLE|Article|CLAUSE|Clause|SECTION|Section)\s+"
    r"(\d{1,3}(?:\.\d{1,3})*|[IVXLC]{1,7}))\b[ \t.:-]*",
    re.M,
)

# A schedule or annexure heading standing on its own line. These carry the real
# commercial terms constantly -- rent, deposit, payment schedules -- yet they are
# rarely numbered like clauses, so without this they were absorbed into whatever
# numbered clause happened to come last and inherited its category. Requiring the
# heading to occupy the whole line keeps an in-sentence "the schedule below" out.
_ANNEX_HEADING = re.compile(
    r"^[ \t]*((?:THE\s+)?(?:SCHEDULE|ANNEXURE|ANNEX|APPENDIX|EXHIBIT)"
    r"(?:\s+[A-Z0-9]{1,3})?)[ \t]*:?[ \t]*$",
    re.M,
)

# A heading is a short line that names the clause rather than stating it. Matched
# on the text immediately following the marker.
# The hyphen must not terminate a heading: "NON-COMPETITION" would otherwise be
# read as the heading "NON", and the rest of the word would fall into the body.
_HEADING = re.compile(
    r"^(?P<heading>[A-Z][^\n.;:]{2,70}?)\s*(?::\s*|\.(?=\s)|\n)",
)

# Lines that look like markers but are not: money, dates and bare years lead many
# a contract line and would otherwise shatter a clause into fragments.
_NOT_A_MARKER = re.compile(
    r"^[ \t]*(?:\d{1,3}(?:\.\d{1,3})?)\s*(?:%|per\s*cent|lakh|crore|million|days?|months?|years?)\b",
    re.I,
)

# Below this many detected markers, or this fraction of the document covered,
# the numbering pass is judged to have failed and paragraphs are used instead.
_MIN_MARKERS = 3
_MIN_COVERAGE = 0.55

_MIN_CLAUSE_CHARS = 25


def _top_level(number: str) -> Optional[int]:
    head = number.split(".")[0]
    return int(head) if head.isdigit() else None


def _collect_markers(text: str) -> List[Tuple[int, str]]:
    """Offsets and numbers of every plausible clause marker, in document order."""
    found: Dict[int, str] = {}
    for pattern in (_DECIMAL, _SPELLED, _PAREN, _ANNEX_HEADING):
        for match in pattern.finditer(text):
            start = match.start()
            line_end = text.find("\n", start)
            line = text[start : line_end if line_end != -1 else len(text)]
            if _NOT_A_MARKER.match(line):
                continue
            # An earlier pattern wins the same offset: decimal numbering is more
            # reliable than a parenthesised letter, which also appears mid-list.
            found.setdefault(start, match.group(1))
    return sorted(found.items())


def _drop_out_of_sequence(markers: Sequence[Tuple[int, str]]) -> List[Tuple[int, str]]:
    """Discard top-level markers that break the document's counting.

    A clause body containing "... within 30 days. 5. of the Schedule ..." can
    produce a marker that would cut a clause in half. Real top-level numbering
    only ever moves forward, and by small steps, so a marker that jumps backwards
    or leaps ahead is noise.
    """
    kept: List[Tuple[int, str]] = []
    last_top = 0
    for offset, number in markers:
        top = _top_level(number)
        is_nested = "." in number or top is None
        if not is_nested:
            if top <= last_top or top > last_top + 3:
                continue
            last_top = top
        kept.append((offset, number))
    return kept


def _split_heading(body: str) -> Tuple[Optional[str], str]:
    match = _HEADING.match(body)
    if not match:
        return None, body
    heading = match.group("heading").strip()
    # A heading is a label, not a sentence. Anything with sentence punctuation or
    # too many words is clause text that merely starts with a capital.
    if len(heading.split()) > 9:
        return None, body
    return heading, body[match.end() :].lstrip()


def _paragraph_blocks(text: str) -> List[Tuple[int, int]]:
    blocks, cursor = [], 0
    for chunk in re.split(r"\n{2,}", text):
        start = text.find(chunk, cursor)
        if start == -1:
            continue
        blocks.append((start, start + len(chunk)))
        cursor = start + len(chunk)
    return blocks


def segment_clauses(document: ParsedDocument) -> List[Clause]:
    """Cut the document into clauses, numbering-first with a paragraph fallback."""
    text = document.text
    markers = _drop_out_of_sequence(_collect_markers(text))

    spans: List[Tuple[int, int, Optional[str]]] = []
    if len(markers) >= _MIN_MARKERS:
        covered = markers[-1][0] - markers[0][0]
        if covered >= _MIN_COVERAGE * max(len(text) - markers[0][0], 1):
            for index, (start, number) in enumerate(markers):
                end = markers[index + 1][0] if index + 1 < len(markers) else len(text)
                spans.append((start, end, number))

    if not spans:
        spans = [(start, end, None) for start, end in _paragraph_blocks(text)]

    clauses: List[Clause] = []
    # A numbered heading with no body of its own ("4. TERMINATION" above 4.1) is
    # not a clause, but it does tell the classifier what 4.1 is about. It is
    # carried forward rather than emitted.
    inherited_heading: Optional[str] = None

    for start, end, number in spans:
        raw = text[start:end]
        body = raw
        if number and not _ANNEX_HEADING.match(raw):
            marker_match = re.match(r"^[ \t]*\(?[^\s)]{1,16}\)?[ \t.)]*", raw)
            if marker_match:
                body = raw[marker_match.end() :]
        heading, remainder = _split_heading(body.strip())

        if len(remainder.strip()) < _MIN_CLAUSE_CHARS:
            if heading:
                inherited_heading = heading
            continue

        effective_heading = heading or inherited_heading
        category, matched = classify_clause(remainder, effective_heading)

        clause_text = raw.strip()
        offset_shift = raw.index(clause_text) if clause_text else 0
        clause_start = start + offset_shift
        # Locate the body within the clause rather than recomputing it, so the
        # recorded offset always addresses the same characters `remainder` holds.
        body_index = clause_text.find(remainder[:40]) if remainder else -1
        clauses.append(
            Clause(
                index=len(clauses),
                number=number,
                heading=heading,
                text=clause_text,
                start_offset=clause_start,
                end_offset=clause_start + len(clause_text),
                body_offset=clause_start + (body_index if body_index != -1 else 0),
                category=category,
                category_matched_terms=matched,
                page=_page_for(document, start),
            )
        )
    return clauses


def _page_for(document: ParsedDocument, offset: int) -> Optional[int]:
    from src.core.document_parser import page_for_offset

    return page_for_offset(document, offset)


# ---------------------------------------------------------------------------
# Deterministic clause classification
# ---------------------------------------------------------------------------
#
# This is the first pass and the permanent fallback. Phase 3's model classifier
# refines it, but the pipeline must still produce a usable review when the LLM is
# unavailable -- the same contract every other node in this codebase honours.

_CATEGORY_TERMS: Dict[ClauseCategory, Tuple[str, ...]] = {
    ClauseCategory.NON_COMPETE: (
        r"non[- ]?compet\w*", r"restraint of trade",
        # "competing business" alone missed "competing firm", "competing entity"
        # and "competitor" -- all ordinary drafting for the same restraint.
        # "competes" and "competitive" sit outside competing/competitor, while
        # "competent authority" must stay out -- so the forms are explicit.
        r"compet(?:e|es|ing|itor|itors|itive|ition)\b",
        r"similar business", r"similar trade",
        r"shall not.{0,80}(?:engage|carry on|be employed|join|accept employment|set up)",
    ),
    ClauseCategory.NON_SOLICIT: (
        r"non[- ]?solicit\w*", r"solicit.{0,40}(?:employee|customer|client)",
        r"poach\w*", r"entice away",
    ),
    ClauseCategory.CONFIDENTIALITY: (
        r"confidential\w*", r"non[- ]?disclosure", r"proprietary information",
        r"trade secret", r"shall not disclose",
    ),
    ClauseCategory.IP_ASSIGNMENT: (
        r"intellectual property", r"\bIPR?\b", r"copyright", r"patent",
        r"work[s]? (?:made )?for hire", r"assign\w*.{0,40}(?:right|title|interest)",
        r"moral rights",
    ),
    ClauseCategory.INDEMNITY: (
        r"indemnif\w*", r"hold harmless", r"defend and hold",
    ),
    ClauseCategory.LIABILITY: (
        r"limitation of liability", r"liability.{0,40}(?:shall|is) (?:not )?(?:be )?limited",
        r"consequential damages", r"in no event shall", r"aggregate liability",
    ),
    ClauseCategory.LIQUIDATED_DAMAGES: (
        r"liquidated damages", r"penalt(?:y|ies)", r"pre[- ]?estimate of.{0,20}loss",
        r"compensation for breach",
    ),
    ClauseCategory.TERMINATION: (
        r"terminat\w*", r"expiry of this agreement", r"end this agreement",
        r"cessation of employment",
    ),
    ClauseCategory.NOTICE_PERIOD: (
        r"notice period", r"\b(?:one|two|three|\d{1,3})\s*(?:month|day)s?['’]? (?:prior )?(?:written )?notice",
        r"serve.{0,30}notice",
    ),
    ClauseCategory.DISPUTE_RESOLUTION: (
        r"arbitrat\w*", r"dispute resolution", r"concilia\w*", r"mediat\w*",
        r"sole arbitrator", r"arbitral tribunal",
        # A clause barring suit is about dispute resolution whatever it is headed.
        r"(?:institute|file|bring)[^.]{0,30}(?:suit|proceeding)", r"in any court",
    ),
    ClauseCategory.GOVERNING_LAW: (
        r"governing law", r"governed by.{0,40}laws", r"exclusive jurisdiction",
        r"courts? at .{0,30}shall have", r"subject to the jurisdiction",
    ),
    ClauseCategory.FORCE_MAJEURE: (
        r"force majeure", r"act of god", r"beyond the reasonable control",
    ),
    ClauseCategory.RENEWAL: (
        r"renew\w*", r"auto[- ]?renew\w*", r"extended for a further",
    ),
    ClauseCategory.AMENDMENT: (
        r"amend\w*", r"modif\w*.{0,30}(?:terms|agreement)", r"vary the terms",
        r"at its sole discretion.{0,40}(?:change|modify|revise)",
    ),
    ClauseCategory.ASSIGNMENT: (
        r"assign\w*.{0,40}(?:this agreement|its rights)", r"novat\w*",
        r"transfer.{0,30}(?:obligations|this agreement)",
    ),
    ClauseCategory.DATA_PROTECTION: (
        r"personal data", r"data protection", r"data fiduciary", r"data principal",
        r"privacy polic\w*", r"process\w*.{0,30}personal information",
    ),
    ClauseCategory.SECURITY_DEPOSIT: (
        r"security deposit", r"interest[- ]free deposit", r"caution money",
        r"refundable deposit",
    ),
    ClauseCategory.RENT: (
        r"\brent\b", r"monthly rent", r"rent.{0,20}(?:payable|escalat\w*)", r"lease rent",
    ),
    ClauseCategory.LOCK_IN: (
        r"lock[- ]?in", r"minimum (?:period|term) of.{0,30}(?:month|year)",
    ),
    ClauseCategory.MAINTENANCE: (
        r"maintenance charge", r"repairs?.{0,30}(?:shall be|borne)", r"upkeep",
    ),
    ClauseCategory.SALARY: (
        r"\bsalary\b", r"remunerat\w*", r"\bCTC\b", r"gross compensation", r"emolument",
    ),
    ClauseCategory.PAYMENT: (
        r"payment terms", r"invoice", r"\bfees?\b", r"payable within",
        r"milestone payment",
        # A loan's repayment schedule is its payment clause. Without these the
        # evaluation set reported a loan with a full EMI schedule as lacking
        # payment terms.
        r"repay\w*", r"instalments?", r"\bEMIs?\b", r"principal amount",
    ),
    ClauseCategory.BOND: (
        r"\bbond\b", r"minimum service period", r"training cost",
        r"refund.{0,40}(?:training|recruitment)", r"service agreement bond",
    ),
    ClauseCategory.PROBATION: (r"probation\w*", r"confirmation of employment"),
    ClauseCategory.WORKING_HOURS: (r"working hours", r"hours of work", r"shift timing"),
    ClauseCategory.LEAVE: (r"\bleave\b", r"casual leave", r"earned leave", r"holiday entitlement"),
    ClauseCategory.WARRANTY: (r"warrant\w*", r"represents? and warrants?", r"\bas is\b"),
    # "\bterm\b" cannot match "termination" -- there is no word boundary after
    # "term" inside it -- so the two categories stay distinguishable.
    ClauseCategory.TERM: (
        r"\bterm\b", r"commencement date", r"commenc\w*", r"with effect from",
        r"shall remain in force", r"duration of this agreement",
    ),
    ClauseCategory.DEFINITIONS: (r"^definitions?\b", r"shall mean", r"unless the context"),
    ClauseCategory.PARTIES: (r"between\b.{0,80}\band\b.{0,80}(?:hereinafter|referred to as)", r"party of the first part"),
}

_COMPILED_TERMS: Dict[ClauseCategory, Tuple[re.Pattern, ...]] = {
    category: tuple(compile_loose(p, re.I | re.M | re.S) for p in patterns)
    for category, patterns in _CATEGORY_TERMS.items()
}

# A heading names the clause outright, so a hit there outweighs any number of
# incidental mentions in the body -- "termination" appears inside half the
# clauses of an employment contract without any of them being the termination clause.
_HEADING_WEIGHT = 4
_BODY_WEIGHT = 1


def classify_clause(
    text: str, heading: Optional[str] = None
) -> Tuple[ClauseCategory, List[str]]:
    """Label a clause by keyword evidence, returning the terms that decided it."""
    scores: Dict[ClauseCategory, int] = {}
    evidence: Dict[ClauseCategory, List[str]] = {}

    for category, patterns in _COMPILED_TERMS.items():
        for pattern in patterns:
            if heading and pattern.search(heading):
                scores[category] = scores.get(category, 0) + _HEADING_WEIGHT
                evidence.setdefault(category, []).append(f"heading:{pattern.pattern}")
            found = pattern.search(text)
            if found:
                scores[category] = scores.get(category, 0) + _BODY_WEIGHT
                evidence.setdefault(category, []).append(found.group(0).strip()[:60])

    if not scores:
        return ClauseCategory.OTHER, []

    best = max(scores.items(), key=lambda item: item[1])[0]
    # Dedupe while preserving the order evidence was found in.
    seen, terms = set(), []
    for term in evidence[best]:
        if term.lower() not in seen:
            seen.add(term.lower())
            terms.append(term)
    return best, terms[:6]
