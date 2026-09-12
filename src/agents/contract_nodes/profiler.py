from langchain_groq import ChatGroq
from src.agents.contract_state import ContractGraphState
from src.config import settings
from src.core.logger import pipeline_logger
from src.schemas.contract import POSITIONS_BY_TYPE, ContractType, PartyPosition
from src.schemas.contract_review import ContractProfile

STAGE = "CONTRACT AGENT 1: PROFILER"

# Keyword evidence for the rule-based fallback. Ordered most specific first: a
# lease that mentions salary is still a lease.
_TYPE_TERMS = (
    (ContractType.LEASE, ("lease", "lessor", "lessee", "tenant", "landlord", "rental agreement", "leave and licence")),
    (ContractType.EMPLOYMENT, ("employment", "employee", "employer", "salary", "ctc", "probation", "appointment letter")),
    (ContractType.NDA, ("non-disclosure", "nondisclosure", "disclosing party", "receiving party", "confidentiality agreement")),
    (ContractType.LOAN, ("loan", "borrower", "lender", "principal amount", "interest rate", "repayment")),
    (ContractType.SAAS, ("software-as-a-service", "software as a service", "subscription", "platform", "saas")),
    (ContractType.FREELANCE, ("freelance", "freelancer", "independent contractor")),
    (ContractType.SERVICE, ("services agreement", "service provider", "consultant", "statement of work", "master services")),
    (ContractType.VENDOR, ("vendor", "supplier", "purchase order", "goods")),
)


def _rule_based_type(text: str) -> tuple:
    lowered = text.lower()
    scores = {}
    for contract_type, terms in _TYPE_TERMS:
        hits = [t for t in terms if t in lowered]
        if hits:
            scores[contract_type] = (len(hits), hits)
    if not scores:
        return ContractType.UNKNOWN, 0.0, []
    best = max(scores.items(), key=lambda item: item[1][0])
    contract_type, (count, hits) = best
    return contract_type, min(0.85, 0.35 + 0.12 * count), hits


async def run_contract_profiler(state: ContractGraphState) -> ContractGraphState:
    document = state.get("document")
    text = state.get("document_text", "") or (document.text if document else "")
    clauses = state.get("clauses", [])

    pipeline_logger.log_step(
        STAGE,
        f"Profiling uploaded contract for Task [{state.get('task_id', 'local')}] -> Identifying type, parties and reviewing side",
        details={"clauses": len(clauses), "characters": len(text)},
    )

    declared_type = state.get("declared_contract_type")
    declared_position = state.get("declared_position")

    if len(clauses) < 3:
        pipeline_logger.log_step(
            STAGE,
            "Document did not segment into a reviewable set of clauses -> Triggering EARLY EXIT.",
            details={"clauses": len(clauses)},
            status="EARLY_EXIT",
        )
        return {
            **state,
            "final_response": {
                "status": "NEEDS_CLARIFICATION",
                "contract_type": ContractType.UNKNOWN.value,
                "position": PartyPosition.UNKNOWN.value,
                "position_source": "UNKNOWN",
                "confidence_score": 0.05,
                "clause_count": len(clauses),
                "clarification_questions": [
                    "Only %d clause(s) could be read from this file. Is it the full contract?" % len(clauses),
                    "If it is a scan or a photograph, run OCR on it and upload the text version.",
                ],
                "extraction_warnings": list(document.extraction_warnings) if document else [],
            },
        }

    llm_available = state.get("llm_available", True)
    llm_calls = state.get("llm_calls_used", 0)
    profile = None

    try:
        llm = ChatGroq(
            model=settings.GROQ_MODEL,
            groq_api_key=settings.GROQ_API_KEY,
            temperature=0.0,
        ).with_structured_output(ContractProfile)

        # The opening recitals name the parties and the closing clauses carry
        # governing law; the middle is obligations the profiler does not need.
        head = text[:6000]
        tail = text[-2000:] if len(text) > 8000 else ""

        prompt = (
            "You are the Contract Profiler Agent for Indian contracts.\n"
            "Read the contract extract and populate every field of the schema.\n\n"
            "[RULES]\n"
            "1. Report only what the document states. Do not infer a party's name that is not written.\n"
            "2. `party_names` maps the role label as printed to the party's full name, "
            "e.g. {'the Company': 'Northwind Technologies Private Limited'}.\n"
            "3. `governing_law` and `stated_term` must be copied verbatim or left null.\n"
            "4. `inferred_position` is which side a person asking for this review is most "
            "likely on. Choose UNKNOWN unless the document makes it clear.\n\n"
            f"[CONTRACT EXTRACT - OPENING]\n{head}\n"
            + (f"\n[CONTRACT EXTRACT - CLOSING]\n{tail}\n" if tail else "")
        )
        profile = await llm.ainvoke(prompt)
        llm_calls += 1
    except Exception as e:
        pipeline_logger.log_step(
            STAGE,
            f"Groq API Info ({type(e).__name__}). Using Rule-Based Contract Profiler Engine.",
            status="WARNING",
        )
        llm_available = False

    if profile is not None:
        contract_type = profile.contract_type
        confidence = profile.contract_type_confidence
        party_names = profile.party_names or {}
        governing_law = profile.governing_law
        inferred = profile.inferred_position
        notes = list(profile.notes or [])
    else:
        contract_type, confidence, hits = _rule_based_type(text)
        party_names = {}
        governing_law = None
        inferred = PartyPosition.UNKNOWN
        notes = [f"Type inferred from terms: {', '.join(hits[:6])}"] if hits else []

    # A user-declared type or side always wins. The reviewer knows which side
    # they are on, and every severity in the review turns on that answer.
    if declared_type:
        contract_type = declared_type
        confidence = 1.0
        notes.append("Contract type supplied by the user.")

    if declared_position:
        position = declared_position
        position_source = "USER_DECLARED"
    elif inferred != PartyPosition.UNKNOWN:
        position = inferred
        position_source = "LLM_INFERRED"
    else:
        position = PartyPosition.UNKNOWN
        position_source = "UNKNOWN"

    # A side that does not belong to this contract type is not usable: a LANDLORD
    # on an employment contract would mis-score every finding. Which of the two
    # gives way depends on where each came from. The API already rejects a
    # user-declared pair that disagrees, so a disagreement here means at least
    # one side of it was guessed -- and a guess must never overrule the person
    # who told us. Discarding their answer and then asking them for it again was
    # the worst of both.
    valid = POSITIONS_BY_TYPE.get(contract_type)
    if valid and position != PartyPosition.UNKNOWN and position not in valid:
        if position_source == "USER_DECLARED":
            owner = next(
                (t for t, pair in POSITIONS_BY_TYPE.items() if position in pair), None
            )
            notes.append(
                f"Inferred type {contract_type.value} disagrees with the side you "
                f"gave ({position.value}); keeping your answer."
            )
            contract_type = owner or ContractType.UNKNOWN
            confidence = min(confidence, 0.4)
        else:
            notes.append(
                f"Discarded inferred side {position.value}: not a party to a "
                f"{contract_type.value} contract."
            )
            position = PartyPosition.UNKNOWN
            position_source = "UNKNOWN"

    pipeline_logger.log_step(
        STAGE,
        f"Profiled as [{contract_type.value}] reviewed as [{position.value}] -> Next: Clause Classifier",
        details={
            "contract_type": contract_type.value,
            "position": position.value,
            "position_source": position_source,
            "parties": party_names,
            "governing_law": governing_law,
        },
        status="SUCCESS",
    )

    return {
        **state,
        "contract_type": contract_type.value,
        "contract_type_confidence": confidence,
        "party_names": party_names,
        "position": position.value,
        "position_source": position_source,
        "governing_law": governing_law,
        "profile_notes": notes,
        "llm_available": llm_available,
        "llm_calls_used": llm_calls,
    }
