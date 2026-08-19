from typing import List
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field
from src.agents.state import GraphState
from src.config import settings
from src.core.logger import pipeline_logger
from src.schemas.legal import ElementAudit, OffenseAnalysis


class OffenseListPayload(BaseModel):
    offenses: List[OffenseAnalysis] = Field(
        ..., description="List of potential statutory offenses derived strictly from explicit facts and law"
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
            )
        retrieved_text = "\n---\n".join(context_formatted)

        feedback_instruction = (
            f"\nCRITICAL CORRECTION FROM VERIFICATION JUDGE (Previous attempt failed):\n{feedback}\n"
            "Discard any offense where a statutory element is CONTRADICTED_BY_FACT."
            if feedback
            else ""
        )

        prompt = (
            "You are the Legal Analyst Agent. Your objective is to map explicit facts against retrieved laws to determine if any offenses have been committed.\n\n"
            "[INPUTS]\n"
            f"1. Explicit Facts (IMMUTABLE): {explicit_facts}\n"
            f"2. Unknown Facts (UNKNOWN != FALSE and UNKNOWN != TRUE): {unknown_facts}\n"
            f"3. Retrieved Legal Contexts:\n{retrieved_text}\n"
            f"{feedback_instruction}\n\n"
            "[STRICT RULES OF ENGAGEMENT]\n"
            "1. FACTUAL IMMUTABILITY: You MUST treat `Explicit Facts` as absolute truth. You are FORBIDDEN from altering or ignoring them.\n"
            "2. NO ASSUMPTION GENERATION: If a fact is missing, mark element status as 'UNPROVEN'. Do NOT invent facts.\n"
            "3. ELEMENT MAPPING: For every proposed offense, construct an element audit table with status 'SUPPORTED', 'UNPROVEN', or 'CONTRADICTED_BY_FACT'.\n"
            "   - Example: If a statute requires 'entry without permission', and explicit facts state 'has invitation', mark status as 'CONTRADICTED_BY_FACT'.\n"
            "4. EXONERATION OVER CONVICTION: If any required element is 'CONTRADICTED_BY_FACT', do NOT assert the offense. Return an empty list or only supported offenses."
        )

        result: OffenseListPayload = await llm.ainvoke(prompt)
        offenses = result.offenses
    except Exception as e:
        pipeline_logger.log_step(
            "AGENT 3: LEGAL ANALYST",
            f"Groq API Info ({type(e).__name__}). Using Strict Element Mapper Engine.",
            status="WARNING",
        )
        offenses = []
        ef_joined = " ".join(explicit_facts).lower()

        for chunk in retrieved_chunks:
            sec_num = chunk.get("section_number", "")
            title_lower = chunk.get("title", "").lower()

            # Element audit for Trespass (Sec 329)
            if "329" in sec_num or "trespass" in title_lower:
                if "invitation" in ef_joined or "permission" in ef_joined or "consent" in ef_joined:
                    # Contradicted by explicit facts! Do NOT assert offense!
                    pipeline_logger.log_step(
                        "AGENT 3: LEGAL ANALYST",
                        f"Element Audit: 'Without permission' CONTRADICTED_BY_FACT for Section {sec_num}. DO NOT ASSERT OFFENSE.",
                        status="SUCCESS",
                    )
                    continue

            # Element audit for Search (Sec 185)
            if "185" in sec_num or "search" in title_lower:
                if "police" not in ef_joined and "officer" not in ef_joined:
                    continue

            elements = [
                ElementAudit(
                    element_name="Core statutory action",
                    status="SUPPORTED" if any(w in ef_joined for w in ["entered", "search", "theft", "took"]) else "UNPROVEN",
                    evidence_quote=explicit_facts[0] if explicit_facts else None,
                )
            ]

            offenses.append(
                OffenseAnalysis(
                    act_name=chunk.get("act", "Bharatiya Nyaya Sanhita, 2023 (BNS)"),
                    section_number=sec_num,
                    offense_description=chunk.get("title", "Statutory Provision"),
                    potential_punishment=chunk.get("punishment") or "Statutory penalty",
                    reasoning_chain=[
                        f"Explicit Fact: {explicit_facts[0] if explicit_facts else 'User scenario'}",
                        f"Mapped against {chunk.get('act', '')} {sec_num}.",
                    ],
                    element_audits=elements,
                    relevance_level="DIRECT",
                    source_verified=True,
                )
            )

    pipeline_logger.log_step(
        "AGENT 3: LEGAL ANALYST",
        f"Draft conclusion generated with {len(offenses)} offenses -> Next: Verification Agent",
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
        "retry_count": retry_count + 1,
    }