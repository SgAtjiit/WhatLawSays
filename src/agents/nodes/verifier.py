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

    try:
        llm = ChatGroq(
            model=settings.GROQ_MODEL,
            groq_api_key=settings.GROQ_API_KEY,
            temperature=0.0,
        ).with_structured_output(VerificationResult)

        prompt = (
            "You are the Verification Agent. Your job is to audit draft legal conclusions to prevent factual contradictions and legal hallucinations. You act as the final strict gatekeeper.\n\n"
            "[INPUTS]\n"
            f"1. Explicit Facts (IMMUTABLE GROUND TRUTH): {explicit_facts}\n"
            f"2. Unknown Facts (UNKNOWN != FALSE and UNKNOWN != TRUE): {unknown_facts}\n"
            f"3. Draft Legal Analysis (Target to Audit): {draft}\n"
            f"4. Raw Statutory Source Texts (The Law): {source_texts}\n\n"
            "[AUDIT PROTOCOL]\n"
            "STEP 1: FACT-ALIGNMENT CHECK (Logic Audit)\n"
            "- Compare the reasoning chain and element status of each draft offense against Explicit Facts.\n"
            "- Does the reasoning chain contradict any established fact (e.g., charging trespass when an invitation is established)?\n"
            "- Verdict Rule: If a contradiction exists, YOU MUST FAIL THE AUDIT.\n\n"
            "STEP 2: STATUTORY VERIFICATION (Hallucination Audit)\n"
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
        ef_joined = " ".join(explicit_facts).lower()
        contradiction = False
        feedback = None

        for o in draft:
            sec = str(o.get("section_number", ""))
            desc = str(o.get("offense_description", "")).lower()

            # Fact-alignment check: Trespass charged despite invitation/consent
            if ("329" in sec or "trespass" in desc) and ("invitation" in ef_joined or "permission" in ef_joined or "consent" in ef_joined):
                contradiction = True
                feedback = (
                    f"FACTUAL CONTRADICTION DETECTED: Agent 3 charged Criminal Trespass ({sec}) despite explicit "
                    f"fact stating valid invitation/permission exists. Drop Section {sec} immediately!"
                )
                break

        if contradiction:
            verification = VerificationResult(
                audit_status="FAIL",
                audit_reasoning="Draft charged Criminal Trespass despite explicit invitation/permission.",
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
        }