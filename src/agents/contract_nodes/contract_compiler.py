from src.agents.contract_state import ContractGraphState
from src.core.clause_triage import COLD
from src.core.contract_confidence import estimate_contract_confidence
from src.core.database import save_analysis_record
from src.core.logger import pipeline_logger
from src.core.redlines import build_redlines
from src.schemas.contract import SEVERITY_ORDER, ContractType, PartyPosition, Severity
from src.schemas.contract_review import ClauseReview, ContractReviewResponse

STAGE = "CONTRACT STEP 9: REVIEW COMPILER"


def _overall_risk(findings) -> str:
    if not findings:
        return "LOW"
    worst = max(SEVERITY_ORDER[f.severity] for f in findings)
    return next(s.value for s, v in SEVERITY_ORDER.items() if v == worst)


async def run_contract_compiler(state: ContractGraphState) -> ContractGraphState:
    pipeline_logger.log_step(
        STAGE,
        "Estimating contract-review confidence and finalizing response...",
    )

    clauses = state.get("clauses", [])
    findings = state.get("findings", [])
    document = state.get("document")
    document_text = state.get("document_text", "")
    tiers = state.get("clause_tier", {})
    explanations = state.get("explanations", {})
    position_source = state.get("position_source", "UNKNOWN")
    contract_type = state.get("contract_type", ContractType.UNKNOWN.value)

    analysed = [i for i, tier in tiers.items() if tier != COLD]

    # The verifier already proved every surviving finding quotes the document.
    # Anything that still fails here is dropped rather than reported: a review
    # that shows a quote the contract does not contain is worse than one that
    # shows nothing, because the reader cannot tell which findings to trust.
    grounded = []
    dropped = []
    for finding in findings:
        span = " ".join(document_text[finding.match_start : finding.match_end].split())
        if span == finding.matched_quote:
            grounded.append(finding)
        else:
            dropped.append({
                "rule_id": finding.rule_id,
                "detector": finding.detector,
                "quote": finding.matched_quote[:120],
                "reason": "quote absent from the document at the recorded offsets",
            })

    by_clause = {}
    for finding in grounded:
        by_clause.setdefault(finding.clause_index, []).append(finding)

    # Scored on the PRE-filter list. Computing it on `grounded` hid the very
    # thing the cap exists for: two ungrounded findings were dropped and the
    # review still reported 0.95 with grounding 1.0 and no cap applied.
    confidence = estimate_contract_confidence(
        clauses=clauses,
        findings=findings,
        document_text=document_text,
        analysed_indices=analysed,
        position_source=position_source,
        contract_type=contract_type,
        llm_available=state.get("llm_available", True),
        reranker_available=state.get("reranker_available", True),
        degraded_nodes=state.get("degraded_nodes", []),
    )

    clause_reviews = []
    for clause in clauses:
        explanation = explanations.get(clause.index, {})
        citations = []
        seen = set()
        for finding in by_clause.get(clause.index, []):
            for citation in finding.citations:
                key = (citation.act, citation.section_number)
                if key not in seen:
                    seen.add(key)
                    citations.append(citation)
        # Retrieved sections are offered as context only where the clause has a
        # finding: a section list attached to an unremarkable clause reads as an
        # accusation the review is not making.
        clause_reviews.append(
            ClauseReview(
                index=clause.index,
                number=clause.number,
                heading=clause.heading,
                category=clause.category,
                tier=tiers.get(clause.index, COLD),
                text=clause.text,
                start_offset=clause.start_offset,
                end_offset=clause.end_offset,
                page=clause.page,
                plain_english=explanation.get("plain_english", ""),
                obligations=explanation.get("obligations", []),
                watch_outs=explanation.get("watch_outs", []),
                findings=by_clause.get(clause.index, []),
                citations=citations,
            )
        )

    risk_counts = {
        s.value: sum(1 for f in grounded if f.severity is s)
        for s in Severity
        if any(f.severity is s for f in grounded)
    }

    degraded = state.get("degraded_nodes", [])
    if not state.get("grounding_passed", True):
        status = "PARTIAL_SUCCESS"
    elif degraded or not state.get("llm_available", True):
        status = "PARTIAL_SUCCESS"
    else:
        status = "SUCCESS"

    clarifications = []
    if position_source == "UNKNOWN":
        clarifications.append(
            "Which side of this contract are you on? The same clause can be a serious "
            "risk to one party and routine to the other, so severities are unweighted "
            "until you say."
        )
    if contract_type == ContractType.UNKNOWN.value:
        clarifications.append(
            "What kind of contract is this? Knowing the type lets the review check it "
            "against the protections that kind of contract should contain."
        )

    response = ContractReviewResponse(
        status=status,
        contract_type=ContractType(contract_type),
        position=PartyPosition(state.get("position", PartyPosition.UNKNOWN.value)),
        position_source=position_source,
        party_names=state.get("party_names", {}),
        governing_law=state.get("governing_law"),
        confidence_score=confidence.score,
        confidence_basis=confidence.to_payload(),
        overall_risk=_overall_risk(grounded),
        risk_counts=risk_counts,
        clause_count=len(clauses),
        analysed_clause_count=len(analysed),
        clauses=clause_reviews,
        findings=grounded,
        missing_clauses=state.get("missing_clauses", []),
        consistency_issues=state.get("consistency_findings", []),
        # INFO means the clause does not work against this reader, so telling
        # them to negotiate it away is advice against their own interest.
        redlines=[
            r.model_dump(mode="json")
            for r in build_redlines([f for f in grounded if SEVERITY_ORDER[f.severity] > 0])
        ],
        extraction_warnings=list(document.extraction_warnings) if document else [],
        degraded_nodes=list(degraded),
        clarification_questions=clarifications,
    )
    payload = response.model_dump(mode="json")

    pipeline_logger.log_step(
        STAGE,
        f"Review complete! Status: [{status}] | Type: [{contract_type}] | "
        f"Risk: [{response.overall_risk}] | Findings: {len(grounded)} | "
        f"Confidence: {confidence.score:.2f}",
        details={
            "risk_counts": risk_counts,
            "missing_clauses": len(response.missing_clauses),
            "consistency_issues": len(response.consistency_issues),
            "analysed_clauses": f"{len(analysed)}/{len(clauses)}",
            "llm_calls_used": state.get("llm_calls_used", 0),
            "dropped_ungrounded": len(dropped),
            "confidence_components": {
                k: round(v, 3) for k, v in confidence.components.items()
            },
            "confidence_caps_applied": confidence.caps_applied,
        },
        status="SUCCESS",
    )

    await save_analysis_record(
        task_id=state.get("task_id", "contract-local"),
        scenario_text=f"[CONTRACT REVIEW] {document.filename if document else 'uploaded contract'}",
        status=status,
        confidence_score=confidence.score,
        response_payload=payload,
    )

    return {
        **state,
        "findings": grounded,
        "confidence_score": confidence.score,
        "confidence_basis": confidence.to_payload(),
        "final_response": payload,
    }
