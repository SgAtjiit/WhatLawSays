"""Agent 2: write the review up for whoever has to act on it.

This is the only place a model touches a procurement review, and the boundary is
narrower than the contract pipeline's on purpose.

**The model does not propose findings here, and that is not timidity.** The
contract pipeline needs a red-flag analyst because a contract is arbitrary prose:
the rules read what they were written to read, and a model can genuinely notice
something in the remaining text that no rule encodes. A sourcing event is not
prose. It is structured data with a fixed schema, and every field in it is
already visible to every check. There is no unread text for a model to find
something in -- so a model "finding" here would not be a reading of the data, it
would be an invented rule, arrived at once, unreproducibly, and presented next to
findings that carry statutory citations. The asymmetry with `red_flag_analyst`
is a consequence of the two inputs being different, not of different standards.

What the model is good for is the thing the deterministic spine is bad at:
saying, in one paragraph, what a reader with thirty seconds needs to know. It is
given the findings and the statutory text and asked to restate them. Every number
it writes is checked against the material it was shown, and a number that is not
there is a fabrication about someone's money, so the narrative is rejected and
retried rather than repaired.

With Groq unreachable the node writes the summary from the findings
deterministically. It is duller and it is correct.
"""

from typing import Any, Dict, List

from langchain_groq import ChatGroq

from src.agents.procurement_state import ProcurementGraphState
from src.config import settings
from src.core.logger import pipeline_logger
from src.schemas.contract import SEVERITY_ORDER
from src.schemas.procurement import CheckStatus
from src.schemas.procurement_review import AwardNarrative

STAGE = "PROCUREMENT AGENT 2: NARRATOR"

MAX_NOTES = 8

PROMPT = """You are writing up a procurement compliance review for the person who is \
about to release this purchase order.

[ABSOLUTE RULES]
1. Deterministic checks have already decided what is a breach, what is only a pattern \
worth asking about, and what could not be checked. You restate those findings. You do \
NOT decide that anything is or is not a breach, and you must not contradict a status.
2. Every number you write -- an amount, a number of days, a count, a percentage -- MUST \
appear in the material below. A number that is not there is a fabrication about \
somebody's money and the whole narrative is discarded.
3. Do NOT say that anyone acted improperly, colluded, or broke the law. Findings marked \
INDICATOR are patterns in data that have ordinary explanations; write about them as \
questions to ask, never as conclusions.
4. Checks marked UNDETERMINED were NOT performed. Never describe them as passing, as \
fine, or as having been checked.
5. Plain words. The reader is a buyer or a finance manager, not a lawyer.

REVIEWING FOR: {side}
OVERALL: {overall}

{material}

Write:
- headline: one sentence on what this review found.
- what_to_do_first: the single most important thing to do before releasing the order.
- notes: at most {max_notes} entries, each naming a check_id from the material above and \
adding one or two sentences of context a reader would not get from the summary alone.
"""


def _material(outcomes, statutory_context: Dict[str, List[Dict[str, Any]]]) -> str:
    blocks = []
    for outcome in outcomes:
        lines = [
            f"check_id: {outcome.check_id}",
            f"status: {outcome.status.value}   severity: {outcome.severity.value}",
            f"title: {outcome.title}",
            f"summary: {outcome.plain_summary}",
            f"why: {outcome.why_it_matters}",
        ]
        if outcome.what_would_resolve_it:
            lines.append(f"to resolve: {outcome.what_would_resolve_it}")
        for evidence in outcome.evidence[:3]:
            kind = getattr(evidence, "kind", None)
            if kind and kind.value == "FIELD":
                lines.append(
                    f"evidence: {evidence.field_path} = "
                    f"{evidence.observed_display or evidence.observed}"
                )
            elif kind and kind.value == "DERIVED":
                lines.append(f"evidence: {evidence.computation} = {evidence.value}")
        for section in statutory_context.get(outcome.check_id, [])[:1]:
            lines.append(
                f"statute: {section['act']} {section['section_number']} -- "
                f"{' '.join((section.get('text') or '').split())[:500]}"
            )
        blocks.append("\n".join(lines))
    return "\n\n---\n\n".join(blocks)


def _deterministic(outcomes, side: str) -> Dict[str, Any]:
    """The fallback, and the floor the model has to beat.

    Built from the findings themselves, so with no model reachable at all the
    review still opens with something a reader can act on.
    """
    breaches = [o for o in outcomes if o.status == CheckStatus.BREACH]
    indicators = [o for o in outcomes if o.status == CheckStatus.INDICATOR]
    gaps = [o for o in outcomes if o.status == CheckStatus.UNDETERMINED]

    def plural(count, singular, many=None):
        return f"{count} {singular if count == 1 else (many or singular + 's')}"

    parts = []
    if breaches:
        parts.append(plural(len(breaches), "requirement") + " not met")
    if indicators:
        parts.append(plural(len(indicators), "pattern") + " in the bid data worth asking about")
    if gaps:
        parts.append(plural(len(gaps), "check") + " that could not be performed")

    if not parts:
        headline = "No breach was found in the checks that could be performed."
    elif len(parts) == 1:
        headline = f"This award has {parts[0]}."
    else:
        headline = f"This award has {', '.join(parts[:-1])} and {parts[-1]}."

    if breaches:
        worst = max(breaches, key=lambda o: SEVERITY_ORDER[o.severity])
        first = f"{worst.title}. {worst.plain_summary}"
    elif gaps:
        first = (
            f"Supply what the {len(gaps)} unperformed check(s) need, so this review can "
            "actually speak to them."
        )
    else:
        first = "Nothing blocks this order on the checks that were run."

    return {
        "headline": headline,
        "what_to_do_first": first,
        "notes": [],
        "source": "rule",
    }


async def run_narrator(state: ProcurementGraphState) -> ProcurementGraphState:
    outcomes = [
        o for o in state.get("outcomes", [])
        if o.status in {CheckStatus.BREACH, CheckStatus.INDICATOR, CheckStatus.UNDETERMINED}
    ]
    side = state.get("side", "UNKNOWN")
    degraded = list(state.get("degraded_nodes", []))
    retry = state.get("retry_count", 0)

    # The deterministic write-up is prepared first, so a failed model call
    # degrades the narrative to a duller one rather than to nothing.
    fallback = _deterministic(outcomes, side)

    if not outcomes or not state.get("llm_available", True):
        state["narrative"] = fallback
        state["narrative_passed"] = True
        return state

    overall = "breaches found" if any(
        o.status == CheckStatus.BREACH for o in outcomes
    ) else "no breach found in what could be checked"

    pipeline_logger.log_step(
        STAGE,
        f"Writing up {len(outcomes)} finding(s) for the {side.lower()} "
        f"(attempt {retry + 1}) -> Next: Narrative Verifier",
    )

    prompt = PROMPT.format(
        side=side.lower(),
        overall=overall,
        material=_material(outcomes, state.get("statutory_context", {})),
        max_notes=MAX_NOTES,
    )
    feedback = state.get("narrative_problems", [])
    if feedback:
        prompt += (
            "\n\n[YOUR PREVIOUS ATTEMPT WAS REJECTED]\n"
            + "\n".join(f"- {p}" for p in feedback[:5])
            + "\nWrite it again using only numbers that appear in the material above."
        )

    try:
        llm = ChatGroq(
            model=settings.GROQ_MODEL,
            groq_api_key=settings.GROQ_API_KEY,
            temperature=0.0,
        ).with_structured_output(AwardNarrative)
        result = await llm.ainvoke(prompt)
        if result is None:
            raise RuntimeError("structured output returned nothing")

        known = {o.check_id for o in outcomes}
        state["narrative"] = {
            "headline": result.headline,
            "what_to_do_first": result.what_to_do_first,
            # A note about a check that is not in this review is about nothing,
            # so it is dropped rather than shown against the wrong finding.
            "notes": [
                {"check_id": n.check_id, "note": n.note}
                for n in result.notes if n.check_id in known
            ][:MAX_NOTES],
            "source": "llm",
        }
        state["llm_calls_used"] = state.get("llm_calls_used", 0) + 1
    except Exception as e:
        degraded.append(f"narrator fell back to the rule-based summary ({type(e).__name__})")
        state["degraded_nodes"] = degraded
        state["llm_available"] = False
        state["narrative"] = fallback
        state["narrative_passed"] = True
        pipeline_logger.log_step(
            STAGE, f"Groq unavailable ({type(e).__name__}); wrote the summary from the "
                   "findings instead", status="WARNING",
        )
    return state
