from langchain_groq import ChatGroq
from src.agents.state import GraphState
from src.config import settings
from src.core.confidence import estimate_absence_confidence
from src.core.logger import pipeline_logger
from src.schemas.legal import ExtractedFacts


async def run_fact_extractor(state: GraphState) -> GraphState:
    scenario = state["scenario_text"]

    pipeline_logger.log_step(
        "AGENT 1: FACT EXTRACTOR",
        f"Processing scenario text for Task [{state.get('task_id', 'local')}] -> Extracting Explicit Facts & Unknowns",
        details=scenario[:120] + "...",
    )

    llm_available = True

    try:
        llm = ChatGroq(
            model=settings.GROQ_MODEL,
            groq_api_key=settings.GROQ_API_KEY,
            temperature=0.0,
        ).with_structured_output(ExtractedFacts)

        prompt = (
            "You are an authoritative legal fact extraction agent for Indian Law (BNS / BNSS / BSS / Constitution).\n"
            "Analyze the citizen scenario and produce three completely separate arrays:\n"
            "1. `established_facts`: Objective, physical facts explicitly stated in the prompt without modifying them.\n"
            "2. `user_allegations`: Subjective claims or accusations made by the user/actor.\n"
            "3. `explicit_facts`: Combined union of established facts and user allegations.\n"
            "4. `unknown_facts`: Indeterminate questions/facts. REMEMBER: UNKNOWN != FALSE and UNKNOWN != TRUE.\n"
            "5. `scenario_domain`: Classify scenario domain as 'POTENTIAL_CRIMINAL', 'CIVIL', 'CONSTITUTIONAL', 'PROCEDURAL', 'MIXED', or 'UNKNOWN'.\n"
            "6. `offense_status`: Always set initial offense_status to 'UNDETERMINED' at this stage.\n"
            "7. Set `should_early_exit = True` ONLY if the input is completely vacuous or gibberish (e.g., 'help', 'asdf') where NO legal inference can be made.\n\n"
            f"Citizen Scenario: {scenario}"
        )
        facts: ExtractedFacts = await llm.ainvoke(prompt)
        if not facts.established_facts:
            facts.established_facts = facts.explicit_facts

        # Deduplicate unknown_facts against established_facts and user_allegations
        known_set = set([f.lower() for f in (facts.established_facts + facts.user_allegations)])
        deduped_unknowns = []
        for u in facts.unknown_facts:
            if u.lower() not in known_set:
                deduped_unknowns.append(u)
        facts.unknown_facts = deduped_unknowns
    except Exception as e:
        pipeline_logger.log_step(
            "AGENT 1: FACT EXTRACTOR",
            f"Groq API Info ({type(e).__name__}). Using Rule-Based Immutable Fact Extractor Engine.",
            status="WARNING",
        )
        llm_available = False
        s_lower = scenario.lower()

        if len(scenario.strip().split()) < 3 and not any(k in s_lower for k in ["theft", "stole", "police", "arrest", "hit", "kill", "fight", "rob", "cheat", "enter", "party"]):
            facts = ExtractedFacts(
                explicit_facts=[scenario],
                established_facts=[scenario],
                user_allegations=[],
                unknown_facts=["Unclear scenario description"],
                actor="Unknown",
                action="Unclear action",
                scenario_domain="UNKNOWN",
                offense_status="UNDETERMINED",
                should_early_exit=True,
            )
        else:
            explicit = [sentence.strip() for sentence in scenario.split(".") if sentence.strip()]
            if not explicit:
                explicit = [scenario]

            unknowns = []
            if "invitation" in s_lower:
                unknowns.extend([
                    "Whether the invitation was genuine",
                    "Whether entry was actually permitted or revoked",
                    "Whether security personnel refused entry",
                    "Whether force or criminal intent existed",
                ])
            elif "police" in s_lower:
                unknowns.extend([
                    "Whether written grounds of belief were recorded prior to search",
                    "Whether formal charge or arrest occurred at the scene",
                ])

            # Classify scenario domain
            if any(k in s_lower for k in ["constitution", "fundamental right", "liberty", "article"]):
                domain = "CONSTITUTIONAL"
            elif any(k in s_lower for k in ["police search", "warrant", "procedure", "fir", "bail"]):
                domain = "PROCEDURAL"
            elif any(k in s_lower for k in ["evidence", "electronic record", "chat message", "confession"]):
                domain = "PROCEDURAL"
            else:
                domain = "POTENTIAL_CRIMINAL"

            actor = "Police Officer" if "police" in s_lower else ("Visitor / Guest" if "invitation" in s_lower or "party" in s_lower else "Accused Person")
            action = "Entry into residence" if "enter" in s_lower or "residence" in s_lower else ("Search of device" if "phone" in s_lower else "Theft / Act")

            facts = ExtractedFacts(
                explicit_facts=explicit,
                established_facts=explicit,
                user_allegations=[],
                unknown_facts=unknowns,
                actor=actor,
                action=action,
                object_involved="Residence / Property" if "residence" in s_lower or "house" in s_lower else "Electronic Device / Assets",
                scenario_domain=domain,
                offense_status="UNDETERMINED",
                should_early_exit=False,
            )

    if facts.should_early_exit:
        # Nothing was retrieved and no offence was analysed, so the absence
        # estimator scores this on retrieval (zero) and fact completeness alone.
        _, early_exit_report = estimate_absence_confidence(
            retrieved_chunks=[],
            has_contradiction=False,
            unknown_facts=facts.unknown_facts,
            llm_available=llm_available,
        )
        pipeline_logger.log_step(
            "AGENT 1: FACT EXTRACTOR",
            "Vacuous input detected -> Triggering EARLY EXIT.",
            details={"unknown_facts": facts.unknown_facts},
            status="EARLY_EXIT",
        )
        return {
            **state,
            "extracted_facts": facts,
            "explicit_facts": facts.explicit_facts,
            "unknown_facts": facts.unknown_facts,
            "scenario_domain": facts.scenario_domain,
            "offense_status": "UNDETERMINED",
            "verification_passed": False,
            "llm_available": llm_available,
            "confidence_basis": early_exit_report.to_payload(),
            "final_response": {
                "status": "NEEDS_CLARIFICATION",
                "scenario_domain": facts.scenario_domain,
                "offense_status": "UNDETERMINED",
                "confidence_score": early_exit_report.score,
                "confidence_basis": early_exit_report.to_payload(),
                "extracted_facts": facts.model_dump(),
                "identified_offenses": [],
                "clarification_questions": facts.unknown_facts or ["Please describe the scenario or event that took place."],
                "disclaimer": "Unclear scenario provided. Please describe what happened for legal analysis.",
            },
        }

    pipeline_logger.log_step(
        "AGENT 1: FACT EXTRACTOR",
        f"Immutable facts extracted -> Domain: [{facts.scenario_domain}] | Offense Status: [UNDETERMINED] -> Next: Legal Query Builder",
        details={
            "explicit_facts": facts.explicit_facts,
            "unknown_facts": facts.unknown_facts,
            "actor": facts.actor,
            "action": facts.action,
            "scenario_domain": facts.scenario_domain,
            "offense_status": facts.offense_status,
        },
        status="SUCCESS",
    )

    return {
        **state,
        "extracted_facts": facts,
        "explicit_facts": facts.explicit_facts,
        "unknown_facts": facts.unknown_facts,
        "scenario_domain": facts.scenario_domain,
        "offense_status": facts.offense_status,
        "llm_available": llm_available,
    }