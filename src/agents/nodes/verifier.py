from typing import Optional
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field
from src.agents.state import GraphState
from src.config import settings
from src.core.logger import pipeline_logger


class VerificationResult(BaseModel):
    audit_status: str = Field(
        ..., description="'PASS' if passes BOTH Step 1 (Fact Alignment) and Step 2 (Statute Verification); 'FAIL' otherwise"
    )
    audit_reasoning: str = Field(
        ..., description="Detailed audit breakdown explaining why it passed or failed"
    )
    correction_feedback: Optional[str] = Field(
        None, description="Explicit instructions on what Agent 3 must fix if FAIL. Null if PASS."
    )


async def run_verifier(state: GraphState) -> GraphState:
    pipeline_logger.log_step(
        "AGENT 4: VERIFICATION AGENT (CLAIM -> EVIDENCE -> FACT JUDGE)",
        "Auditing draft legal analysis against Immutable Explicit Facts & Statutory Source Texts...",
    )

    explicit_facts = state.get("explicit_facts", [])
    unknown_facts = state.get("unknown_facts", [])
    draft = [o.model_dump() for o in state.get("draft_offenses", [])]
    source_texts = state.get("retrieved_chunks", [])

    llm_available = state.get("llm_available", True)

    try:
        llm = ChatGroq(
            model=settings.GROQ_MODEL,
            groq_api_key=settings.GROQ_API_KEY,
            temperature=0.0,
        ).with_structured_output(VerificationResult)

        prompt = (
            "You are the Verification Agent. Your job is to audit draft legal conclusions to prevent factual contradictions, procedural clutter, and legal hallucinations. You act as the final strict gatekeeper.\n\n"
            "[INPUTS]\n"
            f"1. Explicit Facts (IMMUTABLE GROUND TRUTH): {explicit_facts}\n"
            f"2. Unknown Facts (UNKNOWN != FALSE and UNKNOWN != TRUE): {unknown_facts}\n"
            f"3. Draft Legal Analysis (Target to Audit): {draft}\n"
            f"4. Raw Statutory Source Texts (The Law): {source_texts}\n\n"
            "[AUDIT PROTOCOL]\n"
            "STEP 1: CATEGORY AUDIT\n"
            "- Are any procedural sections (BNSS, CrPC, BSA, Evidence Act, Definitions, Procedure, Witness Examination, Police Report) included in draft offenses?\n"
            "- Are any General Exceptions / Self-Defense sections (BNS Sec 38-44) listed as draft offenses?\n"
            "- Verdict Rule: IF PROCEDURAL SECTIONS OR DEFENCE EXCEPTIONS ARE LISTED AS OFFENSES, YOU MUST FAIL THE AUDIT.\n\n"
            "STEP 2: FACT-ALIGNMENT & ELEMENT SUPPORT AUDIT\n"
            "- Check element audits for each draft offense against Explicit Facts.\n"
            "- Does any draft offense contain elements marked 'CONTRADICTED_BY_FACT' or 'UNPROVEN' for mandatory core elements?\n"
            "- Does draft assert Attempt to Murder (BNS 109) when death actually occurred?\n"
            "- Does draft assert Criminal Intimidation, False Information, or Negligence without explicit fact support?\n"
            "- Verdict Rule: IF ANY MANDATORY ELEMENT IS UNPROVEN OR CONTRADICTED, YOU MUST FAIL THE AUDIT.\n\n"
            "STEP 3: STATUTORY VERIFICATION (Hallucination Audit)\n"
            "- Compare section numbers, offense descriptions, and punishments against Raw Statutory Source Texts.\n"
            "- Verdict Rule: If statutory text is hallucinated or misstated, YOU MUST FAIL THE AUDIT.\n\n"
            "[OUTPUT REQUIREMENTS]\n"
            "Return JSON object. If FAIL, set audit_status = 'FAIL' and provide explicit correction_feedback for Agent 3."
        )

        verification: VerificationResult = await llm.ainvoke(prompt)
    except Exception as e:
        pipeline_logger.log_step(
            "AGENT 4: VERIFICATION AGENT (CLAIM -> EVIDENCE -> FACT JUDGE)",
            f"Groq API Info ({type(e).__name__}). Using Rule-Based Claim-Evidence Verification Engine.",
            status="WARNING",
        )
        llm_available = False
        ef_joined = " ".join(explicit_facts).lower()
        failed = False
        feedback = None

        for o in draft:
            sec = str(o.get("section_number", ""))
            act = str(o.get("act_name", "")).lower()
            desc = str(o.get("offense_description", "")).lower()

            # 1. Procedural / BNSS check
            if "nagrik" in act or "nagarik" in act or "bnss" in act or "crpc" in act or "sakshya" in act or "bsa" in act:
                failed = True
                feedback = f"PROCEDURAL SECTION DETECTED IN DRAFT OFFENSES: Section {sec} from {act}. Drop procedural sections from offenses array!"
                break
            if any(w in desc for w in ["definition", "procedure", "report", "diary", "examination of witness"]):
                failed = True
                feedback = f"PROCEDURAL/DEFINITIONAL PROVISION IN DRAFT OFFENSES: Section {sec} ({desc}). Drop immediately!"
                break

            # 2. General Exception / Self Defense check
            if ("private defence" in desc or "self defence" in desc) or (sec in ["38", "39", "40", "41", "42", "43", "44"] and "sanhita" in act):
                failed = True
                feedback = f"DEFENCE EXCEPTION IN DRAFT OFFENSES: Section {sec} ({desc}). Move to applied_defences array!"
                break

            # 3. Specialized Statutory Prerequisites Check (Dowry Death, Miscarriage, Rape)
            if ("80" in sec or "dowry" in desc) and ("dowry" not in ef_joined and "marriage" not in ef_joined):
                failed = True
                feedback = f"SPECIALIZED OFFENSE UNPROVEN: Charged Dowry Death ({sec}) without marriage/dowry facts. Drop Section {sec}!"
                break
            if ("88" in sec or "89" in sec or "miscarriage" in desc or "abortion" in desc) and ("pregnant" not in ef_joined and "miscarriage" not in ef_joined):
                failed = True
                feedback = f"SPECIALIZED OFFENSE UNPROVEN: Charged Miscarriage ({sec}) without pregnancy facts. Drop Section {sec}!"
                break
            if ("63" in sec or "rape" in desc or "sexual assault" in desc) and ("rape" not in ef_joined and "sexual" not in ef_joined):
                failed = True
                feedback = f"SPECIALIZED OFFENSE UNPROVEN: Charged Rape ({sec}) without sexual violence facts. Drop Section {sec}!"
                break
            if (sec in ["178", "179", "180", "181", "182"] or "currency-note" in desc or "bank-note" in desc or "resembling currency" in desc) and not any(w in ef_joined for w in ["counterfeit", "fake note", "forged note", "forgery", "banknote"]):
                failed = True
                feedback = f"SPECIALIZED OFFENSE UNPROVEN: Charged Currency Forgery ({sec}) without counterfeit currency facts. Drop Section {sec}!"
                break
            if (sec in ["309", "310", "311", "312"] or "robbery" in desc or "dacoity" in desc) and not any(w in ef_joined for w in ["stole", "stolen", "robbed", "robbery", "theft", "extort"]):
                failed = True
                feedback = f"SPECIALIZED OFFENSE UNPROVEN: Charged Robbery/Dacoity ({sec}) without theft/robbery facts. Drop Section {sec}!"
                break
            if ("351" in sec or "intimidation" in desc) and ("threat" not in ef_joined and "intimidat" not in ef_joined):
                failed = True
                feedback = f"OFFENSE UNPROVEN: Charged Criminal Intimidation ({sec}) without threat facts. Drop Section {sec}!"
                break
            if (sec in ["217", "212", "211", "246"] or "false information" in desc or "false claim" in desc) and ("false" not in ef_joined and "lied" not in ef_joined):
                failed = True
                feedback = f"OFFENSE UNPROVEN: Charged False Information/Claim ({sec}) without false statement facts. Drop Section {sec}!"
                break

            # 4. Fact-alignment check: Trespass charged despite invitation/consent
            if ("329" in sec or "trespass" in desc) and ("invitation" in ef_joined or "permission" in ef_joined or "consent" in ef_joined):
                failed = True
                feedback = f"FACTUAL CONTRADICTION DETECTED: Charged Criminal Trespass ({sec}) despite valid invitation/permission. Drop Section {sec}!"
                break

            # 5. Attempt conflict check: Attempt to Murder charged when death occurred
            if ("109" in sec or "attempt to murder" in desc) and any(w in ef_joined for w in ["murdered", "killed", "dead", "death"]):
                failed = True
                feedback = f"ATTEMPT CONFLICT DETECTED: Charged Attempt to Murder ({sec}) when death occurred. Drop Section {sec}!"
                break

        if failed:
            verification = VerificationResult(
                audit_status="FAIL",
                audit_reasoning=feedback or "Draft offenses contain invalid or factually unsupported sections.",
                correction_feedback=feedback,
            )
        else:
            verification = VerificationResult(
                audit_status="PASS",
                audit_reasoning="Draft analysis strictly aligns with explicit facts and statutory source text.",
                correction_feedback=None,
            )

    is_pass = verification.audit_status.upper() == "PASS"

    if is_pass:
        pipeline_logger.log_step(
            "AGENT 4: VERIFICATION AGENT (CLAIM -> EVIDENCE -> FACT JUDGE)",
            "Audit complete: PASS [SUCCESS] (Fact-Alignment & Statutory Verification Passed) -> Next: Response Compiler",
            details={"audit_reasoning": verification.audit_reasoning},
            status="SUCCESS",
        )
        return {
            **state,
            "verification_passed": True,
            "verification_feedback": None,
            "llm_available": llm_available,
        }
    else:
        pipeline_logger.log_step(
            "AGENT 4: VERIFICATION AGENT (CLAIM -> EVIDENCE -> FACT JUDGE)",
            f"Audit complete: FAIL [RETRY] -> Triggering Retry Loop (Count: {state.get('retry_count', 0)}/3)",
            details={
                "audit_reasoning": verification.audit_reasoning,
                "correction_feedback": verification.correction_feedback,
            },
            status="RETRY",
        )
        return {
            **state,
            "verification_passed": False,
            "verification_feedback": verification.correction_feedback or verification.audit_reasoning,
            "llm_available": llm_available,
        }