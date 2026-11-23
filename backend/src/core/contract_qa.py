"""Answer questions about the user's own contract.

Grounded the same way the review is: an answer must rest on clauses that are
actually in the uploaded document, and it says which ones. A question the
contract does not address gets told so, rather than answered from the model's
general impression of what contracts usually say -- which is how a reader ends
up believing their agreement contains a protection it does not.

Retrieval is lexical and in process (see `clause_search`): a contract is at most
a couple of hundred clauses, and the same question must return the same clauses
every time it is asked.
"""

from typing import Any, Dict, List, Optional, Sequence

from langchain_groq import ChatGroq

from src.config import settings
from src.core.clause_search import search_clauses, tokenize
from src.core.logger import pipeline_logger
from src.schemas.contract import Citation
from src.schemas.contract_review import ContractAnswer

STAGE = "CONTRACT Q&A"

_MAX_CLAUSES = 5


def _clause_payload(clause) -> Dict[str, Any]:
    return {
        "index": clause.index,
        "number": clause.number,
        "heading": clause.heading,
        "category": clause.category.value if hasattr(clause.category, "value") else clause.category,
        "text": clause.text,
        "start_offset": clause.start_offset,
        "end_offset": clause.end_offset,
    }


def _rule_based_answer(clauses, hits) -> str:
    """What the deterministic engine can honestly say without a model.

    It cannot compose prose, so it does not pretend to: it points at the clauses
    that match and lets the reader read them.
    """
    if not hits:
        return (
            "Nothing in this contract appears to address that. Check the original "
            "document, and note that terms may also sit in a schedule or annexure "
            "that was not part of the file uploaded."
        )
    by_index = {c.index: c for c in clauses}
    lines = ["The clauses in your contract that deal with this are:"]
    for hit in hits:
        clause = by_index.get(hit.clause_index)
        if clause is None:
            continue
        label = f"Clause {clause.number}" if clause.number else f"Clause {clause.index + 1}"
        if clause.heading:
            label += f" ({clause.heading})"
        lines.append(f"- {label}")
    lines.append(
        "The model that writes plain-language answers is unavailable, so the text "
        "of those clauses is shown below unsummarised."
    )
    return "\n".join(lines)


# Bodies longer than this are truncated before the model sees them. The audit
# found a 2,063-character clause whose answer sat past a 1,600-character cut, so
# the model was asked about text it had never been shown.
_MAX_CLAUSE_CHARS = 4000

_UNINTERPRETABLE = (
    "I couldn't find any words to search for in that question. Try asking about a "
    "specific term, such as 'notice period', 'security deposit' or 'termination'."
)


async def _statutory_context(clauses, cited_indices, findings) -> List[Citation]:
    """Provisions already established as bearing on the clauses the answer cites.

    Taken from the review's own findings rather than retrieved afresh: those
    citations were attached by rules and have been checked, whereas a fresh
    retrieval against a free-text question would be a new, unverified claim.
    Keyed on the clauses actually cited, not on every retrieval hit -- an answer
    about the termination clause was arriving with the bond clause's s.27 and
    s.74 attached because both were in the same top five.
    """
    cited = set(cited_indices)
    seen, citations = set(), []
    for finding in findings or []:
        if finding.get("clause_index") not in cited:
            continue
        for citation in finding.get("citations", []):
            key = (citation["act"], citation["section_number"])
            if key not in seen:
                seen.add(key)
                citations.append(Citation(**citation))
    return citations


async def answer_question(
    *,
    question: str,
    clauses: Sequence[Any],
    findings: Optional[Sequence[Dict[str, Any]]] = None,
    explanations: Optional[Dict[int, Dict[str, Any]]] = None,
    position: str = "UNKNOWN",
) -> Dict[str, Any]:
    """Answer `question` from `clauses`, citing the clauses relied on."""
    if not tokenize(question):
        # Whitespace, emoji, or only stopwords. Saying "the contract does not
        # address that" here would be false: nothing was looked up.
        return {
            "answer": _UNINTERPRETABLE,
            "answered_from_contract": False,
            "cited_clauses": [],
            "statutory_context": [],
            "degraded": False,
        }

    hits = search_clauses(clauses, question, limit=_MAX_CLAUSES)
    by_index = {c.index: c for c in clauses}
    shown = {hit.clause_index for hit in hits}

    pipeline_logger.log_step(
        STAGE,
        f"Question matched {len(hits)} clause(s) -> Composing grounded answer",
        details={"question": question[:120], "clauses": [h.clause_index for h in hits]},
    )

    side = position.replace("_", " ").lower() if position != "UNKNOWN" else "reader"
    degraded = False
    answer_text = None
    cited_indices = [hit.clause_index for hit in hits]
    answered_from_contract = bool(hits)

    if hits:
        try:
            llm = ChatGroq(
                model=settings.GROQ_MODEL,
                groq_api_key=settings.GROQ_API_KEY,
                temperature=0.0,
            ).with_structured_output(ContractAnswer)

            blocks = []
            for hit in hits:
                clause = by_index.get(hit.clause_index)
                if clause is None:
                    continue
                if len(clause.text) > _MAX_CLAUSE_CHARS:
                    pipeline_logger.log_step(
                        STAGE,
                        f"Clause {clause.index} truncated from {len(clause.text)} to {_MAX_CLAUSE_CHARS} characters for the model",
                        status="WARNING",
                    )
                blocks.append(
                    f"clause_index={clause.index} number={clause.number or '-'} "
                    f"heading={clause.heading or '-'}\n{clause.text[:_MAX_CLAUSE_CHARS]}"
                )

            prompt = (
                f"You are answering a question about a contract, for the {side}.\n\n"
                "[ABSOLUTE RULES]\n"
                "1. Answer ONLY from the clauses supplied below. They are the entire "
                "contract as far as you are concerned.\n"
                "2. If the clauses do not answer the question, set "
                "answered_from_contract=false and say plainly that the contract does "
                "not address it. Do NOT fill the gap with what contracts usually say.\n"
                "3. Cite the clause_index values you relied on in cited_clauses.\n"
                "4. Do NOT state whether a term is legal, valid, void or enforceable. "
                "That is decided elsewhere from the actual statute, and your "
                "assumptions about which country's law applies are frequently wrong.\n"
                "5. Do NOT advise whether to sign.\n"
                "6. Plain words, short sentences, second person.\n\n"
                f"[QUESTION]\n{question}\n\n"
                "[CLAUSES FROM THE CONTRACT]\n" + "\n\n---\n\n".join(blocks)
            )
            result = await llm.ainvoke(prompt)
            # An empty answer is no answer: let the rule-based engine speak.
            answer_text = (result.answer or "").strip() or None
            answered_from_contract = result.answered_from_contract
            # Only clauses the model was actually shown, each once. It used to
            # be checked against the whole contract, so a citation of an unseen
            # governing-law clause passed as grounded.
            validated = list(dict.fromkeys(
                i for i in (result.cited_clauses or []) if i in shown
            ))
            if not answered_from_contract:
                # "The contract does not address this" must not arrive with
                # five clauses and two statutes attached as though it did.
                cited_indices = validated
            elif validated:
                cited_indices = validated
        except Exception as e:
            pipeline_logger.log_step(
                STAGE,
                f"Groq API Info ({type(e).__name__}). Using Rule-Based Clause Lookup Engine.",
                status="WARNING",
            )
            degraded = True

    if answer_text is None:
        answer_text = _rule_based_answer(clauses, hits)
        degraded = degraded or bool(hits)

    cited = []
    for index in cited_indices:
        clause = by_index.get(index)
        if clause is None:
            continue
        payload = _clause_payload(clause)
        if explanations and index in explanations:
            payload["plain_english"] = explanations[index].get("plain_english", "")
        cited.append(payload)

    citations = (
        await _statutory_context(clauses, cited_indices, findings)
        if answered_from_contract
        else []
    )

    pipeline_logger.log_step(
        STAGE,
        f"Answered from {len(cited)} clause(s), {len(citations)} statutory citation(s)"
        + ("" if answered_from_contract else " -> contract does not address the question"),
        status="SUCCESS",
    )

    return {
        "answer": answer_text,
        "answered_from_contract": answered_from_contract,
        "cited_clauses": cited,
        "statutory_context": [c.model_dump() for c in citations],
        "degraded": degraded,
    }
