import re
from src.agents.contract_state import ContractGraphState
from src.core.logger import pipeline_logger
from src.schemas.contract import Severity

STAGE = "CONTRACT AGENT 7: CONSISTENCY CHECKER"

# A period that is actually *attached to a notice*: "sixty days written notice",
# "thirty (30) days prior notice", "notice period of ninety days". Matching every
# duration in any clause containing the word "notice" reported a CONFLICT on
# fair_employment_agreement -- a contract the answer key labels clean -- because
# its probation notice (15 days) and its ordinary notice (60 days) sit in one
# clause and are not in conflict at all.
_NOTICE_PERIOD = re.compile(
    r"\b(\d{1,3}|one|two|three|six|nine|twelve|fifteen|thirty|sixty|ninety)\s*"
    r"(?:\(\s*\d{1,3}\s*\)\s*)?(day|days|month|months|year|years)\b"
    r"[^.]{0,40}?notice"
    r"|notice\s+period\s+(?:of|shall\s+be|is)\s+"
    r"(\d{1,3}|one|two|three|six|nine|twelve|fifteen|thirty|sixty|ninety)\s*"
    r"(?:\(\s*\d{1,3}\s*\)\s*)?(day|days|month|months|year|years)\b",
    re.I,
)
_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "six": 6, "nine": 9, "twelve": 12,
    "fifteen": 15, "thirty": 30, "sixty": 60, "ninety": 90,
}
# Language that makes two different periods a scheme rather than a contradiction.
_PHASE_SCHEME = re.compile(
    r"during\s+(?:the\s+)?probation|probation(?:ary)?\s+period|"
    r"during\s+the\s+(?:first|initial)\s|after\s+confirmation|"
    r"upon\s+confirmation|whichever\s+is",
    re.I,
)

_CROSS_REF = re.compile(r"\bclause\s+(\d{1,3}(?:\.\d{1,3})*)\b", re.I)
# Case-sensitive on the label deliberately. Under re.I this matched ordinary
# prose -- "payment schedule set out below" became annexure "Schedule Set",
# "shall exhibit the highest standards" became "Exhibit The" -- and every one
# was reported to the user as a document they had not been shown.
_ANNEXURE = re.compile(r"\b(Annexure|Schedule|Exhibit|Appendix)\s+([A-Z]{1,2}|\d{1,3})\b(?![a-z])")


def _label(clause) -> str:
    """How to name a clause to a reader.

    "clause None" appeared whenever the segmenter fell back to paragraphs.
    """
    return f"clause {clause.number}" if clause.number else f"paragraph {clause.index + 1}"


def _to_days(value: str, unit: str):
    number = _WORD_NUMBERS.get(value.lower(), None)
    if number is None:
        try:
            number = int(value)
        except ValueError:
            return None
    unit = unit.lower()
    if unit.startswith("day"):
        return number
    if unit.startswith("month"):
        return number * 30
    return number * 365


async def run_consistency_checker(state: ContractGraphState) -> ContractGraphState:
    clauses = state.get("clauses", [])

    pipeline_logger.log_step(
        STAGE,
        f"Cross-checking {len(clauses)} clauses for conflicting periods and broken references -> Next: Grounding Verifier",
    )

    # Idempotent: the grounding retry loop re-enters the analyst, and this node
    # must not accumulate a second copy of every issue on the way back through.
    if state.get("retry_count", 0) > 0 and state.get("consistency_findings"):
        pipeline_logger.log_step(
            STAGE,
            "Consistency already established on the first pass -> Next: Grounding Verifier",
            status="SUCCESS",
        )
        return state

    issues = []

    # Conflicting notice periods. Deterministic, and among the most common real
    # drafting defects: clause 5 says fifteen days, clause 12 says ninety.
    notice_periods = {}
    for clause in clauses:
        if "notice" not in clause.text.lower():
            continue
        for match in _NOTICE_PERIOD.finditer(clause.text):
            # Either the "<n> <unit> ... notice" branch (groups 1,2) or the
            # "notice period of <n> <unit>" branch (groups 3,4) matched.
            value, unit = (match.group(1), match.group(2)) if match.group(1) else (match.group(3), match.group(4))
            days = _to_days(value, unit)
            if days:
                notice_periods.setdefault(days, []).append(
                    (clause.index, _label(clause), " ".join(match.group(0).split()))
                )
    # Two different periods are a conflict unless the contract says they apply to
    # different phases. "During probation the notice period shall be fifteen days"
    # beside a sixty-day general period is a scheme; the Company taking fifteen
    # days while the Employee must give ninety, for the same event, is an
    # asymmetry worth reporting and one of the commonest one-sided terms.
    phased = any(
        _PHASE_SCHEME.search(clause.text)
        for clause in clauses
        if clause.index in {c[0] for entries in notice_periods.values() for c in entries}
    )
    if len(notice_periods) > 1 and not phased:
        spread = sorted(notice_periods)
        issues.append({
            "kind": "CONFLICT",
            "description": (
                "This contract states more than one notice period: "
                + ", ".join(
                    f"{notice_periods[d][0][2]} ({notice_periods[d][0][1]})" for d in spread
                )
                + ". Check whether they apply to different things, or whether one side "
                "simply has to give far more warning than the other."
            ),
            "clause_indices": sorted({c[0] for d in spread for c in notice_periods[d]}),
            "quotes": [notice_periods[d][0][2] for d in spread],
            "severity": Severity.MEDIUM.value,
            "detector": "rule",
        })

    # Cross-references to clauses that do not exist.
    numbers = {c.number for c in clauses if c.number}
    for clause in clauses:
        for match in _CROSS_REF.finditer(clause.text):
            target = match.group(1)
            if target not in numbers and not any(n and n.startswith(target + ".") for n in numbers):
                issues.append({
                    "kind": "BROKEN_CROSS_REFERENCE",
                    "description": (
                        f"{_label(clause).capitalize()} refers to clause {target}, which "
                        "is not in this document."
                    ),
                    "clause_indices": [clause.index],
                    "quotes": [" ".join(match.group(0).split())],
                    "severity": Severity.LOW.value,
                    "detector": "rule",
                })

    # Referenced annexures with nothing attached.
    referenced = {}
    for clause in clauses:
        for match in _ANNEXURE.finditer(clause.text):
            referenced.setdefault(match.group(0).title(), clause.index)
    document_text = state.get("document_text", "")
    for label, index in referenced.items():
        # A real annexure appears at least twice: once referenced, once as its
        # own heading. A single mention is a reference to something absent.
        if len(re.findall(re.escape(label), document_text, re.I)) < 2:
            issues.append({
                "kind": "MISSING_ANNEXURE",
                "description": (
                    f"{label} is referred to but does not appear in this document. "
                    "Terms you are agreeing to may be in a document you have not seen."
                ),
                "clause_indices": [index],
                "quotes": [label],
                "severity": Severity.MEDIUM.value,
                "detector": "rule",
            })

    pipeline_logger.log_step(
        STAGE,
        f"{len(issues)} consistency issue(s) found -> Next: Grounding Verifier",
        details=[i["description"][:110] for i in issues[:5]],
        status="SUCCESS",
    )

    return {**state, "consistency_findings": issues}
