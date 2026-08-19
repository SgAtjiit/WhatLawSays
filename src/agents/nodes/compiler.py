from src.agents.state import GraphState
from src.core.database import save_analysis_record
from src.core.logger import pipeline_logger
from src.schemas.legal import LegalAnalysisResponse


async def run_response_compiler(state: GraphState) -> GraphState:
    pipeline_logger.log_step(
        "STEP 5: RESPONSE COMPILER",
        "Calculating Multi-Component Confidence Calibration & Finalizing Response...",
    )

    draft_offenses = state.get("draft_offenses", [])
    extracted_facts = state.get("extracted_facts")
    verification_passed = state.get("verification_passed", False)
    scenario_domain = state.get("scenario_domain", "POTENTIAL_CRIMINAL")
    retries = state.get("retry_count", 0)

    # Filter offenses: Must be DIRECT/CROSS_REFERENCE, classified as OFFENSE, and free of procedural/contradicted items
    valid_offenses = []
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

        # Check element audits for contradiction
        audits = getattr(o, "element_audits", [])
        if any(getattr(a, "status", "") == "CONTRADICTED_BY_FACT" for a in audits):
            continue

        valid_offenses.append(o)

    # Mathematical Multi-Component Confidence Calibration
    c_retrieval = 0.90 if state.get("retrieved_chunks") else 0.40
    c_authority = 1.00
    c_element_coverage = 0.85 if valid_offenses else 0.50
    c_fact_consistency = 0.95 if verification_passed else 0.40

    calibrated_confidence = c_retrieval * c_authority * c_element_coverage * c_fact_consistency
    calibrated_confidence = round(min(max(calibrated_confidence, 0.25), 0.95), 2)

    # Determine status, offense_status, and justification
    if not valid_offenses:
        status = "UNDETERMINED"
        offense_status = "UNDETERMINED"
        calibrated_confidence = 0.35
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
        "confidence_score": calibrated_confidence,
        "reason": reason,
        "extracted_facts": facts_payload,
        "identified_offenses": [o.model_dump() for o in valid_offenses],
        "applied_defences": applied_defences,
        "procedural_provisions": procedural_provisions,
        "immediate_action_steps": action_steps_payload,
        "citizen_duties": citizen_duties,
        "clarification_questions": clarification_questions,
        "disclaimer": disclaimer,
    }

    pipeline_logger.log_step(
        "STEP 5: RESPONSE COMPILER",
        f"Response compilation complete! Status: [{status}] | Domain: [{scenario_domain}] | Offense Status: [{offense_status}] | Confidence: {calibrated_confidence:.2f}",
        details={
            "status": status,
            "scenario_domain": scenario_domain,
            "offense_status": offense_status,
            "identified_offenses_count": len(valid_offenses),
            "calibrated_confidence": calibrated_confidence,
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
        confidence_score=calibrated_confidence,
        response_payload=final_payload,
    )

    return {**state, "final_response": final_payload}
