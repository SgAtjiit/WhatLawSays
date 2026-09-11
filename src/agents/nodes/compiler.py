from src.agents.state import GraphState
from src.core.confidence import estimate_absence_confidence, estimate_confidence
from src.core.database import save_analysis_record
from src.core.logger import pipeline_logger
from src.schemas.legal import LegalAnalysisResponse


async def run_response_compiler(state: GraphState) -> GraphState:
    pipeline_logger.log_step(
        "STEP 5: RESPONSE COMPILER",
        "Estimating Multi-Component Confidence & Finalizing Response...",
    )

    draft_offenses = state.get("draft_offenses", [])
    extracted_facts = state.get("extracted_facts")
    verification_passed = state.get("verification_passed", False)
    scenario_domain = state.get("scenario_domain", "POTENTIAL_CRIMINAL")
    retry_count = state.get("retry_count", 0)
    retrieved_chunks = state.get("retrieved_chunks", [])
    unknown_facts = state.get("unknown_facts", [])
    llm_available = state.get("llm_available", True)
    reranker_available = state.get("reranker_available", True)
    contradicted_provisions = state.get("contradicted_provisions", []) or []

    # Filter offenses: Must be DIRECT/CROSS_REFERENCE, classified as OFFENSE, and free of procedural/contradicted items
    valid_offenses = []
    contradicted_offenses = []
    for o in draft_offenses:
        relevance = getattr(o, "relevance_level", "DIRECT")
        category = getattr(o, "provision_category", "OFFENSE")
        act = str(getattr(o, "act_name", "")).lower()
        desc = str(getattr(o, "offense_description", "")).lower()

        if relevance not in ["DIRECT", "CROSS_REFERENCE"]:
            continue
        if category not in ["OFFENSE"]:
            continue
        if "nagrik" in act or "nagarik" in act or "bnss" in act or "crpc" in act or "sakshya" in act or "bsa" in act:
            continue
        if any(w in desc for w in ["definition", "procedure", "report", "diary", "examination of witness"]):
            continue

        # Check element audits for contradiction. These are recorded rather than
        # silently dropped: a contradicted element is affirmative evidence that no
        # offence arises, which scores very differently from "we could not tell".
        audits = getattr(o, "element_audits", [])
        if any(getattr(a, "status", "") == "CONTRADICTED_BY_FACT" for a in audits):
            contradicted_offenses.append(o)
            continue

        valid_offenses.append(o)

    # Confidence estimation. Every component is measured from a signal the
    # pipeline actually produced -- cross-encoder relevance, element audits,
    # verification outcome, unsupplied facts -- rather than from a constant.
    if valid_offenses:
        confidence_report = estimate_confidence(
            offenses=valid_offenses,
            retrieved_chunks=retrieved_chunks,
            verification_passed=verification_passed,
            retry_count=retry_count,
            unknown_facts=unknown_facts,
            llm_available=llm_available,
            reranker_available=reranker_available,
        )
        absence_status = None
    else:
        absence_status, confidence_report = estimate_absence_confidence(
            retrieved_chunks=retrieved_chunks,
            # Contradictions reach the compiler two ways: recorded upstream by the
            # analyst, or on a draft offense that this filter just excluded.
            has_contradiction=bool(contradicted_offenses or contradicted_provisions),
            unknown_facts=unknown_facts,
            llm_available=llm_available,
            reranker_available=reranker_available,
        )

    confidence_estimate = confidence_report.score

    # Determine status, offense_status, and justification
    if not valid_offenses:
        offense_status = absence_status
        if offense_status == "NOT_ESTABLISHED":
            # Relevant law was retrieved and its elements are contradicted by the
            # facts. That is a finding, not a failure to answer.
            status = "SUCCESS"
            reason = (
                "Relevant statutory provisions were retrieved and their mandatory elements "
                "are contradicted by the supplied facts: no offence is made out."
            )
            disclaimer = (
                "This finding rests on the facts as supplied. Additional facts could change it. "
                "This platform provides source-grounded legal information based on BNS/BNSS/BSS, "
                "not formal legal counsel."
            )
        else:
            status = "UNDETERMINED"
            reason = "The supplied facts do not establish the elements of an offence."
            disclaimer = (
                "Not established from the supplied facts does not prove no offence occurred. "
                "Answering the unknown facts below will refine the legal analysis."
            )
    elif verification_passed:
        status = "SUCCESS"
        offense_status = "ESTABLISHED"
        reason = "Statutory elements established from explicit facts and verified against source text."
        disclaimer = "This platform provides source-grounded legal information based on BNS/BNSS/BSS, not formal legal counsel."
    else:
        status = "PARTIAL_SUCCESS"
        offense_status = "UNDETERMINED"
        reason = "Preliminary legal identification subject to statutory element verification."
        disclaimer = "Preliminary legal identification subject to statutory element verification."

    # Mark offenses as source verified
    for offense in valid_offenses:
        offense.source_verified = verification_passed

    # Generate Element-Driven Clarification Questions
    element_clarifications = []
    for o in valid_offenses:
        audits = getattr(o, "element_audits", [])
        for a in audits:
            if getattr(a, "status", "") == "UNPROVEN":
                elem_name = getattr(a, "element_name", "")
                question = f"Clarification needed for {getattr(o, 'act_name', 'BNS')} Section {getattr(o, 'section_number', '')} ({getattr(o, 'offense_description', '')}): Was the action accompanied by {elem_name.lower()}?"
                if question not in element_clarifications:
                    element_clarifications.append(question)

    clarification_questions = element_clarifications if element_clarifications else state.get("unknown_facts", [])
    applied_defences = state.get("applied_defences", [])
    procedural_provisions = state.get("procedural_provisions", [])
    raw_action_steps = state.get("immediate_action_steps", [])
    citizen_duties = state.get("citizen_duties", [])

    action_steps_payload = [
        step.model_dump() if hasattr(step, "model_dump") else step
        for step in raw_action_steps
    ]

    # Update extracted_facts offense_status and scenario_domain in payload
    facts_payload = extracted_facts.model_dump() if extracted_facts else {}
    facts_payload["scenario_domain"] = scenario_domain
    facts_payload["offense_status"] = offense_status

    final_payload = {
        "status": status,
        "scenario_domain": scenario_domain,
        "offense_status": offense_status,
        "confidence_score": confidence_estimate,
        "confidence_basis": confidence_report.to_payload(),
        "reason": reason,
        "extracted_facts": facts_payload,
        "identified_offenses": [o.model_dump() for o in valid_offenses],
        "applied_defences": applied_defences,
        "procedural_provisions": procedural_provisions,
        "immediate_action_steps": action_steps_payload,
        "citizen_duties": citizen_duties,
        "clarification_questions": clarification_questions,
        "excluded_provisions": contradicted_provisions,
        "disclaimer": disclaimer,
    }

    pipeline_logger.log_step(
        "STEP 5: RESPONSE COMPILER",
        f"Response compilation complete! Status: [{status}] | Domain: [{scenario_domain}] | Offense Status: [{offense_status}] | Confidence: {confidence_estimate:.2f}",
        details={
            "status": status,
            "scenario_domain": scenario_domain,
            "offense_status": offense_status,
            "identified_offenses_count": len(valid_offenses),
            "confidence_estimate": confidence_estimate,
            "confidence_components": {
                k: round(v, 3) for k, v in confidence_report.components.items()
            },
            "confidence_caps_applied": confidence_report.caps_applied,
            "unknown_facts_count": len(clarification_questions),
        },
        status="SUCCESS",
    )

    # Persist to database asynchronously (or in-memory fallback)
    task_id = state.get("task_id", "local-exec")
    await save_analysis_record(
        task_id=task_id,
        scenario_text=state["scenario_text"],
        status=status,
        confidence_score=confidence_estimate,
        response_payload=final_payload,
    )

    return {
        **state,
        "offense_status": offense_status,
        "confidence_score": confidence_estimate,
        "confidence_basis": confidence_report.to_payload(),
        "final_response": final_payload,
    }
