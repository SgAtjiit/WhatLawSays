from typing import List
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field
from src.agents.state import GraphState
from src.config import settings
from src.core.logger import pipeline_logger
from src.schemas.legal import ElementAudit, ImmediateActionStep, OffenseAnalysis, StatutoryExceptionEvaluation


class OffenseListPayload(BaseModel):
    offenses: List[OffenseAnalysis] = Field(
        default=[], description="List of potential statutory offenses derived strictly from explicit facts and law"
    )
    applied_defences: List[str] = Field(
        default=[], description="General exceptions or legal defences applicable e.g. Right of Private Defence (BNS Sec 38-44)"
    )
    procedural_provisions: List[str] = Field(
        default=[], description="Applicable procedural rules e.g. BNSS Section 185 search rules, BSA Section 63 electronic evidence"
    )
    immediate_action_steps: List[ImmediateActionStep] = Field(
        default=[], description="Clear, immediate step-by-step practical and legal action guide for the citizen/witness"
    )
    citizen_duties: List[str] = Field(
        default=[], description="Statutory duties applicable under Indian law (e.g. BNSS Section 33 duty to report murder/robbery)"
    )


async def run_legal_analyst(state: GraphState) -> GraphState:
    retry_count = state.get("retry_count", 0)
    feedback = state.get("verification_feedback")

    pipeline_logger.log_step(
        "AGENT 3: LEGAL ANALYST",
        f"Mapping scenario to statutory sections (Attempt {retry_count + 1}/3) -> Next: Element Mapper & Verifier",
        details={"verification_feedback": feedback} if feedback else None,
    )

    explicit_facts = state.get("explicit_facts", [])
    unknown_facts = state.get("unknown_facts", [])
    retrieved_chunks = state.get("retrieved_chunks", [])
    scenario_text = state.get("scenario_text", "").lower()

    llm_available = state.get("llm_available", True)

    offenses: List[OffenseAnalysis] = []
    contradicted_provisions: List[dict] = []
    applied_defences: List[str] = []
    procedural_provisions: List[str] = []
    action_steps: List[ImmediateActionStep] = []
    duties: List[str] = []

    try:
        llm = ChatGroq(
            model=settings.GROQ_MODEL,
            groq_api_key=settings.GROQ_API_KEY,
            temperature=0.0,
        ).with_structured_output(OffenseListPayload)

        context_formatted = []
        for doc in retrieved_chunks:
            context_formatted.append(
                f"Act: {doc.get('act', '')}\n"
                f"Section: {doc.get('section_number', '')} - {doc.get('title', '')}\n"
                f"Content: {doc.get('content', '')}\n"
                f"Statutory Punishment: {doc.get('punishment', 'N/A')}\n"
                f"Bailable: {doc.get('bailable', 'N/A')}\n"
                f"Cognizable: {doc.get('cognizable', 'N/A')}\n"
            )
        retrieved_text = "\n---\n".join(context_formatted)

        feedback_instruction = (
            f"\nCRITICAL CORRECTION FROM VERIFICATION JUDGE (Previous attempt failed):\n{feedback}\n"
            "Discard any offense where a statutory element is CONTRADICTED_BY_FACT or UNPROVEN."
            if feedback
            else ""
        )

        prompt = (
            "You are the Legal Analyst Agent for Indian Law (BNS / BNSS / BSS / Constitution).\n"
            "Your objective is to map explicit facts against retrieved legal contexts, perform strict statutory-element verification, evaluate section-specific exceptions, extract exact punishment details, and categorize legal provisions.\n\n"
            "[INPUTS]\n"
            f"1. Scenario Text: {state.get('scenario_text', '')}\n"
            f"2. Explicit Facts (IMMUTABLE): {explicit_facts}\n"
            f"3. Unknown Facts (UNKNOWN != FALSE and UNKNOWN != TRUE): {unknown_facts}\n"
            f"4. Retrieved Legal Contexts:\n{retrieved_text}\n"
            f"{feedback_instruction}\n\n"
            "[STRICT LEGAL RULES & CATEGORIZATION PROTOCOL]\n"
            "1. FACTUAL IMMUTABILITY: You MUST treat `Explicit Facts` as absolute truth. You are FORBIDDEN from altering or inventing facts.\n"
            "2. LEGAL CATEGORIZATION:\n"
            "   - PROCEDURAL & DEFINITIONAL SECTIONS: Any provision from Bharatiya Nagarik Suraksha Sanhita (BNSS), CrPC, Bharatiya Sakshya Adhiniyam (BSA), Evidence Act, or titled 'Definitions', 'Procedure', 'Report', 'Diary', or 'Examination of witnesses' is PROCEDURAL. Place these in `procedural_provisions`, NOT in `offenses`!\n"
            "   - GENERAL EXCEPTIONS & DEFENCES: Any provision relating to Right of Private Defence (BNS Sections 38 to 44 / IPC Sections 96 to 106), Necessity, Accident, or Infancy is a DEFENCE. Place these in `applied_defences`, NOT in `offenses`!\n"
            "   - SUBSTANTIVE OFFENSES: Only substantive penal sections from BNS/IPC where an illegal act is alleged against the actor are placed in `offenses`.\n"
            "3. MANDATORY ELEMENT AUDITING:\n"
            "   - For every candidate section, decompose it into its mandatory statutory elements in `element_audits`.\n"
            "   - Set `applicability_status` = 'ESTABLISHED' if ALL mandatory elements are 'SUPPORTED'.\n"
            "   - Set `applicability_status` = 'POTENTIAL_UNDER_INVESTIGATION' if core action matches but key elements are 'UNPROVEN' due to missing facts.\n"
            "   - If ANY element is 'CONTRADICTED_BY_FACT', EXCLUDE the section from `offenses` -- but STILL RETURN IT with its element_audits so the exclusion is recorded as a finding. Do not silently omit it.\n"
            "4. SECTION-SPECIFIC STATUTORY EXCEPTIONS:\n"
            "   - Inspect candidate section text for internal exceptions (e.g., Exceptions 1-5 under BNS Section 101/103 Murder: Grave Provocation, Exceeding Self Defence, Sudden Fight, etc., or Exceptions to Defamation BNS 356).\n"
            "   - Evaluate if any section exception applies based on explicit facts and populate `statutory_exceptions` (e.g., Exception 4 Sudden Fight -> Reduces Murder to Culpable Homicide).\n"
            "5. STATUTORY PUNISHMENT & PROCEDURE CLASSIFICATION:\n"
            "   - Extract exact statutory punishment into `potential_punishment`.\n"
            "   - Populate `cognizable` (True/False), `bailable` (True/False), and `punishment_severity` ('CAPITAL_LIFE', 'SERIOUS', or 'MINOR').\n"
            "6. IMMEDIATE ACTION STEPS & DUTIES: Provide 3-4 step-by-step immediate practical actions and cite legal reporting obligations (e.g., BNSS Section 33 duty to inform police of life-threatening crimes)."
        )

        result: OffenseListPayload = await llm.ainvoke(prompt)
        raw_offenses = result.offenses or []
        applied_defences = result.applied_defences or []
        procedural_provisions = result.procedural_provisions or []
        action_steps = result.immediate_action_steps or []
        duties = result.citizen_duties or []

        # Filter out procedural sections or general exceptions from offenses array
        for o in raw_offenses:
            sec_str = str(o.section_number).lower()
            act_str = str(o.act_name).lower()
            title_str = str(o.offense_description).lower()

            # Exclude procedural / BNSS provisions (route to procedural_provisions)
            if "nagrik" in act_str or "nagarik" in act_str or "bnss" in act_str or "crpc" in act_str or "sakshya" in act_str or "bsa" in act_str or any(w in title_str for w in ["definition", "procedure", "report", "diary", "examination of witness", "repeal"]):
                proc_str = f"{o.act_name} {o.section_number}: {o.offense_description}"
                if proc_str not in procedural_provisions:
                    procedural_provisions.append(proc_str)
                continue

            # Exclude self-defense sections from offenses (route to defences)
            if any(s in sec_str for s in ["17", "38", "39", "40", "41", "42", "43", "44"]) or any(w in title_str for w in ["private defence", "self defence", "justified"]):
                def_str = f"{o.act_name} {o.section_number}: {o.offense_description}"
                if def_str not in applied_defences:
                    applied_defences.append(def_str)
                continue

            # A contradicted element excludes the section from the offenses array,
            # but the exclusion is itself a finding and must survive as data.
            if any(
                str(getattr(a, "status", "")).upper() == "CONTRADICTED_BY_FACT"
                for a in (o.element_audits or [])
            ):
                contradicted_provisions.append(
                    {
                        "act_name": o.act_name,
                        "section_number": o.section_number,
                        "offense_description": o.offense_description,
                        "contradicted_elements": [
                            a.element_name
                            for a in (o.element_audits or [])
                            if str(getattr(a, "status", "")).upper() == "CONTRADICTED_BY_FACT"
                        ],
                    }
                )
                continue

            offenses.append(o)

    except Exception as e:
        pipeline_logger.log_step(
            "AGENT 3: LEGAL ANALYST",
            f"Groq API Info ({type(e).__name__}). Using Strict Statutory Element & Categorization Engine.",
            status="WARNING",
        )
        llm_available = False
        offenses = []
        applied_defences = []
        procedural_provisions = []
        ef_joined = (" ".join(explicit_facts) + " " + scenario_text).lower()

        # Check for Self Defence
        if any(w in ef_joined for w in ["self defence", "self-defence", "private defence", "defend", "defended"]):
            applied_defences.append(
                "Right of Private Defence (Bharatiya Nyaya Sanhita, 2023 - Sections 38 to 44 / IPC Sections 96 to 106)"
            )

        for chunk in retrieved_chunks:
            act_name = chunk.get("act", "")
            sec_num = str(chunk.get("section_number", ""))
            title = chunk.get("title", "")
            title_lower = title.lower()
            act_lower = act_name.lower()
            punishment_text = chunk.get("punishment") or "Statutory penalty prescribed under BNS"
            bailable = chunk.get("bailable")
            cognizable = chunk.get("cognizable")

            # 1. Procedural / Definitional Filter
            # This pool is BNS-only, so anything non-substantive here (definitions,
            # repeals, preliminary provisions) is simply not an offence. Procedural
            # provisions come from their own retrieval pass, not from this loop.
            if "nagrik" in act_lower or "nagarik" in act_lower or "bnss" in act_lower or "crpc" in act_lower or "sakshya" in act_lower or "bsa" in act_lower or any(w in title_lower for w in ["definition", "procedure", "report", "diary", "examination of witness", "repeal", "local inquiry"]):
                continue

            # 2. General Exception / Self-Defense Filter
            if ("private defence" in title_lower or "self defence" in title_lower or "justified" in title_lower) or (sec_num in ["17", "38", "39", "40", "41", "42", "43", "44"] and "sanhita" in act_lower):
                def_entry = f"{act_name} Section {sec_num}: {title}"
                if def_entry not in applied_defences:
                    applied_defences.append(def_entry)
                continue

            # 3. Penalty Gate: a provision that prescribes no penalty cannot create
            # an offence (e.g. POSH s.8 Grants and audit, s.4 Constitution of the
            # Internal Complaints Committee). Checked with `is False` so a chunk
            # indexed before this flag existed is not silently dropped.
            if chunk.get("prescribes_penalty") is False:
                continue

            # 4. Specific Offense Statutory Element Audits
            # Dowry Death (Sec 80)
            if "80" in sec_num or "dowry" in title_lower:
                if "dowry" not in ef_joined and "husband" not in ef_joined and "marriage" not in ef_joined:
                    pipeline_logger.log_step(
                        "AGENT 3: LEGAL ANALYST",
                        f"Element Audit: Dowry Death ({sec_num}) UNPROVEN (no marriage/dowry facts). DO NOT ASSERT.",
                        status="SUCCESS",
                    )
                    continue

            # Miscarriage / Abortion (Sec 88/89)
            if any(s in sec_num for s in ["88", "89"]) or "miscarriage" in title_lower or "abortion" in title_lower:
                if "pregnant" not in ef_joined and "miscarriage" not in ef_joined and "abortion" not in ef_joined:
                    pipeline_logger.log_step(
                        "AGENT 3: LEGAL ANALYST",
                        f"Element Audit: Miscarriage/Abortion ({sec_num}) UNPROVEN (no pregnancy facts). DO NOT ASSERT.",
                        status="SUCCESS",
                    )
                    continue

            # Currency / Bank-Note Forgery (Sec 178, 179, 180, 181, 182)
            if any(s in sec_num for s in ["178", "179", "180", "181", "182"]) or "currency-note" in title_lower or "bank-note" in title_lower or "resembling currency" in title_lower:
                if not any(w in ef_joined for w in ["counterfeit", "fake note", "forged note", "forgery", "banknote"]):
                    pipeline_logger.log_step(
                        "AGENT 3: LEGAL ANALYST",
                        f"Element Audit: Currency Forgery ({sec_num}) UNPROVEN (no counterfeit currency facts). DO NOT ASSERT.",
                        status="SUCCESS",
                    )
                    continue

            # Rape / Sexual Assault (Sec 63)
            if "63" in sec_num or "rape" in title_lower or "sexual assault" in title_lower:
                if "rape" not in ef_joined and "sexual" not in ef_joined and "molest" not in ef_joined:
                    pipeline_logger.log_step(
                        "AGENT 3: LEGAL ANALYST",
                        f"Element Audit: Rape ({sec_num}) UNPROVEN (no sexual violence facts). DO NOT ASSERT.",
                        status="SUCCESS",
                    )
                    continue

            # Robbery / Dacoity (Sec 309, 310, 311, 312)
            if any(s in sec_num for s in ["309", "310", "311", "312"]) or "robbery" in title_lower or "dacoity" in title_lower:
                if not any(w in ef_joined for w in ["stole", "stolen", "robbed", "robbery", "theft", "extort"]):
                    pipeline_logger.log_step(
                        "AGENT 3: LEGAL ANALYST",
                        f"Element Audit: Robbery/Dacoity ({sec_num}) UNPROVEN (no theft/robbery facts). DO NOT ASSERT.",
                        status="SUCCESS",
                    )
                    continue

            # Attempt to Murder (Sec 109)
            if "109" in sec_num or "attempt to murder" in title_lower:
                if any(w in ef_joined for w in ["murdered", "killed", "dead", "death", "stabbed to death"]):
                    pipeline_logger.log_step(
                        "AGENT 3: LEGAL ANALYST",
                        f"Element Audit: Attempt to Murder ({sec_num}) CONTRADICTED_BY_FACT (death occurred). DO NOT ASSERT.",
                        status="SUCCESS",
                    )
                    contradicted_provisions.append(
                        {
                            "act_name": act_name,
                            "section_number": f"Section {sec_num}",
                            "offense_description": title,
                            "contradicted_elements": ["Death occurred, so an attempt cannot be made out."],
                        }
                    )
                    continue

            # Rash or Negligent Act (Sec 106)
            if "106" in sec_num or "negligence" in title_lower or "negligent" in title_lower:
                if any(w in ef_joined for w in ["murdered", "stabbed", "stole", "thief", "intentional"]):
                    pipeline_logger.log_step(
                        "AGENT 3: LEGAL ANALYST",
                        f"Element Audit: Negligence ({sec_num}) CONTRADICTED_BY_FACT (act was intentional/voluntary). DO NOT ASSERT.",
                        status="SUCCESS",
                    )
                    contradicted_provisions.append(
                        {
                            "act_name": act_name,
                            "section_number": f"Section {sec_num}",
                            "offense_description": title,
                            "contradicted_elements": ["The act was intentional or voluntary, not negligent."],
                        }
                    )
                    continue

            # Criminal Intimidation (Sec 351)
            if "351" in sec_num or "intimidation" in title_lower or "threat" in title_lower:
                if not any(w in ef_joined for w in ["threatened", "intimidated", "warned"]):
                    pipeline_logger.log_step(
                        "AGENT 3: LEGAL ANALYST",
                        f"Element Audit: Criminal Intimidation ({sec_num}) UNPROVEN (no threat facts). DO NOT ASSERT.",
                        status="SUCCESS",
                    )
                    continue

            # False Information / False Statement (Sec 217 / Sec 212 / Sec 246)
            if any(s in sec_num for s in ["217", "212", "211", "246"]) or "false information" in title_lower or "false claim" in title_lower:
                if not any(w in ef_joined for w in ["false report", "lied to police", "false statement", "false claim"]):
                    pipeline_logger.log_step(
                        "AGENT 3: LEGAL ANALYST",
                        f"Element Audit: False Information ({sec_num}) UNPROVEN (no false reporting facts). DO NOT ASSERT.",
                        status="SUCCESS",
                    )
                    continue

            # Trespass (Sec 329)
            if "329" in sec_num or "trespass" in title_lower:
                if any(w in ef_joined for w in ["invitation", "permission", "consent"]):
                    pipeline_logger.log_step(
                        "AGENT 3: LEGAL ANALYST",
                        f"Element Audit: Trespass ({sec_num}) CONTRADICTED_BY_FACT (invitation/permission exists). DO NOT ASSERT.",
                        status="SUCCESS",
                    )
                    contradicted_provisions.append(
                        {
                            "act_name": act_name,
                            "section_number": f"Section {sec_num}",
                            "offense_description": title,
                            "contradicted_elements": ["A valid invitation, permission or consent exists."],
                        }
                    )
                    continue

            # Search (Sec 185)
            if "185" in sec_num or "search" in title_lower:
                if "police" not in ef_joined and "officer" not in ef_joined:
                    continue

            elements = [
                ElementAudit(
                    element_name="Core statutory action",
                    status="SUPPORTED" if any(w in ef_joined for w in ["entered", "search", "theft", "took", "stolen", "kill", "murder", "stabbed"]) else "UNPROVEN",
                    evidence_quote=explicit_facts[0] if explicit_facts else None,
                )
            ]

            sec_exceptions = []
            # Section-Specific Statutory Exception Evaluation (e.g. BNS Sec 101/103 Murder)
            if ("103" in sec_num or "101" in sec_num or "murder" in title_lower) and "sanhita" in act_lower:
                if any(w in ef_joined for w in ["self defence", "private defence", "defend"]):
                    sec_exceptions.append(
                        StatutoryExceptionEvaluation(
                            exception_name="BNS Sec 101(2) Exception 2 - Right of Private Defence Exceeded",
                            status="EVALUATED_APPLICABLE",
                            legal_effect="Reduces charge from Murder (BNS Sec 103) to Culpable Homicide Not Amounting to Murder (BNS Sec 101(2)).",
                        )
                    )
                elif any(w in ef_joined for w in ["sudden fight", "heat of passion", "quarrel"]):
                    sec_exceptions.append(
                        StatutoryExceptionEvaluation(
                            exception_name="BNS Sec 101(2) Exception 4 - Sudden Fight",
                            status="EVALUATED_APPLICABLE",
                            legal_effect="Reduces charge from Murder (BNS Sec 103) to Culpable Homicide Not Amounting to Murder.",
                        )
                    )

            # Determine punishment severity
            p_lower = punishment_text.lower()
            if any(w in p_lower for w in ["death", "life", "imprisonment for life"]):
                severity = "CAPITAL_LIFE"
            elif any(w in p_lower for w in ["7 years", "10 years", "5 years", "3 years"]):
                severity = "SERIOUS"
            else:
                severity = "MINOR"

            # Default cognizable / bailable if missing
            if cognizable is None:
                cognizable = True if "murder" in title_lower or "theft" in title_lower or "robbery" in title_lower else False
            if bailable is None:
                bailable = False if "murder" in title_lower or "robbery" in title_lower else True

            offenses.append(
                OffenseAnalysis(
                    act_name=act_name or "Bharatiya Nyaya Sanhita, 2023 (BNS)",
                    section_number=sec_num,
                    offense_description=title or "Statutory Provision",
                    potential_punishment=punishment_text,
                    punishment_severity=severity,
                    cognizable=cognizable,
                    bailable=bailable,
                    reasoning_chain=[
                        f"Explicit Fact: {explicit_facts[0] if explicit_facts else 'User scenario'}",
                        f"Mapped against {act_name} Section {sec_num}.",
                    ],
                    element_audits=elements,
                    statutory_exceptions=sec_exceptions,
                    relevance_level="DIRECT",
                    provision_category="OFFENSE",
                    source_verified=True,
                )
            )

    # Procedural and constitutional provisions come from their own act-scoped
    # retrieval pass (BNSS / BSA / Constitution) and feed the procedural tab only.
    # They are never candidates for the offences array.
    for chunk in state.get("procedural_chunks", []):
        title = str(chunk.get("title", ""))
        title_lower = title.lower()
        # Keep the existing notion of materially relevant: drop generic definitions,
        # repeals and boilerplate.
        if any(w in title_lower for w in ["definition", "repeal", "summons for petty", "effect of error"]):
            continue
        entry = f"{chunk.get('act', '')} {chunk.get('section_number', '')}: {title}"
        if entry not in procedural_provisions and len(procedural_provisions) < 5:
            procedural_provisions.append(entry)

    # Fallback/Supplemental Action Steps Generation if missing
    ef_joined = (" ".join(explicit_facts) + " " + scenario_text).lower()
    if not action_steps:
        if any(w in ef_joined for w in ["murder", "kill", "stab", "death", "corpse", "blood", "attack", "assault"]):
            action_steps = [
                ImmediateActionStep(
                    step_number=1,
                    title="Ensure Personal Safety & Dial Emergency 112",
                    action_details="Immediately reach a safe distance and call the National Emergency Helpline (112) or Police (100) to report the incident.",
                    statutory_duty_reference="BNSS Section 33 / CrPC Section 39",
                    urgency="CRITICAL",
                ),
                ImmediateActionStep(
                    step_number=2,
                    title="Mandatory Legal Reporting Duty",
                    action_details="Inform the nearest police officer or police station without delay. Under Indian law, witnesses have a binding legal duty to inform law enforcement of offenses affecting life.",
                    statutory_duty_reference="Bharatiya Nagarik Suraksha Sanhita (BNSS) Section 33",
                    urgency="CRITICAL",
                ),
                ImmediateActionStep(
                    step_number=3,
                    title="Preserve Crime Scene & Digital Evidence",
                    action_details="Do not touch physical evidence. If you captured video/photos on your mobile device, preserve the unaltered file and timestamps for police investigators.",
                    urgency="HIGH",
                ),
                ImmediateActionStep(
                    step_number=4,
                    title="Request Zero FIR if Needed",
                    action_details="If you are at a police station outside the local territorial jurisdiction, demand the registration of a Zero FIR, which must be transferred to the jurisdictional police station.",
                    statutory_duty_reference="BNSS Section 173 (Zero FIR)",
                    urgency="HIGH",
                ),
            ]
            duties = [
                "Under Section 33 of the Bharatiya Nagarik Suraksha Sanhita, 2023 (BNSS), every person aware of the commission of or intention to commit any offense affecting human life (such as murder or culpable homicide) is legally bound to give information to the nearest magistrate or police officer.",
                "Witnesses are protected under the Witness Protection Scheme and Good Samaritan guidelines against unlawful harassment during legal proceedings.",
            ]
        elif any(w in ef_joined for w in ["thief", "stolen", "theft", "robbed", "snatch", "stolen phone", "lost phone"]):
            action_steps = [
                ImmediateActionStep(
                    step_number=1,
                    title="Block SIM & Mobile Device (IMEI)",
                    action_details="Immediately block your stolen mobile connection via your telecom operator and block the IMEI via the Central Equipment Identity Register (CEIR portal at ceir.gov.in).",
                    urgency="CRITICAL",
                ),
                ImmediateActionStep(
                    step_number=2,
                    title="Secure Financial Accounts",
                    action_details="Block all UPI apps, net banking credentials, and credit/debit cards linked to the stolen phone number.",
                    urgency="CRITICAL",
                ),
                ImmediateActionStep(
                    step_number=3,
                    title="Lodge Police Complaint / e-FIR",
                    action_details="File an e-FIR or written complaint at the local police station detailing the device IMEI, time, date, and location of theft.",
                    statutory_duty_reference="BNSS Section 173",
                    urgency="HIGH",
                ),
                ImmediateActionStep(
                    step_number=4,
                    title="Obtain Police Acknowledgment Copy",
                    action_details="Collect an official stamped copy of the FIR / Police Lost Report for SIM re-issuance and insurance claims.",
                    urgency="MEDIUM",
                ),
            ]
            duties = [
                "Citizens must promptly report stolen property to assist law enforcement and prevent the fraudulent misuse of stolen devices or identity credentials."
            ]
        else:
            action_steps = [
                ImmediateActionStep(
                    step_number=1,
                    title="Call National Emergency Helpline",
                    action_details="Dial 112 for immediate police, medical, or fire assistance.",
                    urgency="HIGH",
                ),
                ImmediateActionStep(
                    step_number=2,
                    title="File Police Report / Complaint",
                    action_details="Approach the nearest police station having jurisdiction to submit a written account of events.",
                    statutory_duty_reference="BNSS Section 173",
                    urgency="HIGH",
                ),
                ImmediateActionStep(
                    step_number=3,
                    title="Preserve Evidence & Documentation",
                    action_details="Retain all relevant receipts, photos, text messages, or physical proof related to the incident.",
                    urgency="MEDIUM",
                ),
            ]
            duties = []

    pipeline_logger.log_step(
        "AGENT 3: LEGAL ANALYST",
        f"Draft conclusion generated with {len(offenses)} offenses, {len(applied_defences)} defences, and {len(action_steps)} action steps -> Next: Verification Agent",
        details=[
            {
                "act": o.act_name,
                "section": o.section_number,
                "offense": o.offense_description,
                "relevance": o.relevance_level,
            }
            for o in offenses
        ],
        status="SUCCESS",
    )

    return {
        **state,
        "draft_offenses": offenses,
        "applied_defences": applied_defences,
        "procedural_provisions": procedural_provisions,
        "immediate_action_steps": action_steps,
        "citizen_duties": duties,
        "contradicted_provisions": contradicted_provisions,
        "retry_count": retry_count + 1,
        "llm_available": llm_available,
    }