"""Step 3: check that the write-up only uses numbers it was actually shown.

Deliberately not an LLM judge, for the reason `grounding_verifier` already sets
out: whether a number appears in the source is decided by string comparison,
which is exact, free, and cannot itself hallucinate. A model asked to check this
would introduce the very failure mode the node exists to catch.

Numbers are what matter here. The narrative cannot invent a finding -- it has no
field to put one in -- but it can very easily write "the payment term is 90 days"
about a 60-day term, or "three bids" about two. Those read as fact, they are
about somebody's money, and a reader has no way to tell them from the
deterministic text beside them. So every numeric token in the narrative must
appear in the material the model was given, and one that does not sends the
narrative back to be written again rather than being quietly edited out.

Words are left alone. A narrative that characterises a finding badly is a worse
summary; a narrative that states a wrong number is a false statement of fact, and
only the second is worth a retry.
"""

import re

from src.agents.procurement_state import ProcurementGraphState
from src.core.logger import pipeline_logger
from src.schemas.procurement import CheckStatus

STAGE = "PROCUREMENT STEP 3: NARRATIVE VERIFIER (NUMBERS -> SOURCE JUDGE)"

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Ordinals and small counts a summary legitimately uses to structure a sentence
# rather than to state a quantity read off the event.
_ALLOWED = {"0", "1", "2", "3", "15", "45"}


def _numbers(text: str) -> set:
    return {m.group(0).replace(",", "").rstrip(".") for m in _NUMBER.finditer(text or "")}


def _source_numbers(state: ProcurementGraphState) -> set:
    """Every number the model was shown, in the form it was shown them."""
    found = set()
    for outcome in state.get("outcomes", []):
        for text in (outcome.plain_summary, outcome.why_it_matters,
                     outcome.what_would_resolve_it or "", outcome.title):
            found |= _numbers(text)
        for evidence in outcome.evidence:
            for attribute in ("observed", "required", "value", "observed_display",
                              "note", "scope_size"):
                found |= _numbers(str(getattr(evidence, attribute, "") or ""))
    for sections in state.get("statutory_context", {}).values():
        for section in sections:
            found |= _numbers(section.get("text", ""))
            found |= _numbers(section.get("section_number", ""))
    return found


async def run_narrative_verifier(state: ProcurementGraphState) -> ProcurementGraphState:
    narrative = state.get("narrative") or {}
    if narrative.get("source") != "llm":
        state["narrative_passed"] = True
        return state

    allowed = _source_numbers(state) | _ALLOWED
    written = _numbers(narrative.get("headline", "")) | _numbers(
        narrative.get("what_to_do_first", "")
    )
    for note in narrative.get("notes", []):
        written |= _numbers(note.get("note", ""))

    invented = sorted(written - allowed)

    # A status the narrative contradicts is the other way this can be wrong: a
    # check that could not be performed described as fine. Cheap to look for and
    # catastrophic to miss.
    gaps = {
        o.check_id for o in state.get("outcomes", [])
        if o.status == CheckStatus.UNDETERMINED
    }
    contradictions = []
    for note in narrative.get("notes", []):
        if note.get("check_id") in gaps:
            lowered = note.get("note", "").lower()
            if any(phrase in lowered for phrase in
                   ("is compliant", "was compliant", "passed", "no issue", "is fine",
                    "complies with", "meets the requirement")):
                contradictions.append(
                    f"{note['check_id']} could not be checked, but the note describes it "
                    "as having passed"
                )

    problems = [f"the number {n} does not appear anywhere in the review" for n in invented]
    problems += contradictions

    retry = state.get("retry_count", 0)
    if not problems:
        state["narrative_passed"] = True
        state["narrative_problems"] = []
        pipeline_logger.log_step(
            STAGE, "Narrative grounded: every number it uses is in the review.",
            status="SUCCESS",
        )
        return state

    state["narrative_passed"] = False
    state["narrative_problems"] = problems
    state["retry_count"] = retry + 1
    pipeline_logger.log_step(
        STAGE,
        f"Narrative rejected ({len(problems)} problem(s)); rewriting -> attempt {retry + 2}",
        status="RETRY",
        details={"problems": problems[:5]},
    )
    return state
