"""Run a procurement review, end to end.

The single place that turns a sourcing event -- and optionally the purchase order
document -- into a stored review. The API endpoint and the Redis worker both call
this, so a review means the same thing however it was triggered. That is the
lesson `contract_service.py` already carries a comment about, where two entry
points scored the same input differently.

Deterministic evaluation runs here rather than inside a graph node, which is the
opposite of where the contract pipeline puts its rules, and deliberately. In the
contract graph the rules live inside `clause_classifier` because relabelling a
clause changes which rules apply, so there is a real dependency on model output.
Here there is none: the event schema is fixed and nothing a model does can change
what a check reads. Running the engine first buys three things -- the retry loop
can never move a value out from under recorded evidence, a total LLM outage still
yields the complete finding set, and `evaluate_procurement` stays a pure function
that the evaluation harness can call without standing a graph up.
"""

import uuid
from typing import Any, Dict, List, Optional

from src.core.bid_integrity import INTEGRITY_LANGUAGE
from src.core.procurement_confidence import estimate_procurement_confidence
from src.core.procurement_evidence import VerificationContext, verify_findings
from src.core.procurement_remediations import build_remediations
from src.core.procurement_rules import POLICY_TEMPLATES, evaluate_procurement, overall_status
from src.core.logger import pipeline_logger
from src.schemas.contract import SEVERITY_ORDER, Citation, ContractType, PartyPosition, Severity
from src.schemas.procurement import (
    CheckFamily,
    CheckStatus,
    DocumentSpanEvidence,
    EMPTY_RULE_SET,
    MsmeStatus,
    ProcurementEvent,
    ProcurementFinding,
    ProcurementSide,
    PolicyRuleSet,
    SourceRef,
)
from src.schemas.procurement_review import AwardReviewResponse, CheckRun

STAGE = "PROCUREMENT REVIEW SERVICE"

# Which side of a purchase order each procurement side sits on. `ContractType.VENDOR`
# and its position pair already exist, so the purchase order goes through the
# contract pipeline unchanged rather than through a second copy of the ruleset.
_POSITION_FOR_SIDE = {
    ProcurementSide.BUYER: PartyPosition.CLIENT,
    ProcurementSide.SUPPLIER: PartyPosition.SERVICE_PROVIDER,
}


def new_review_id() -> str:
    return uuid.uuid4().hex[:16]


def _po_findings_from_contract_review(
    review: Dict[str, Any], side: ProcurementSide
) -> List[ProcurementFinding]:
    """Re-express the purchase order's own red flags as procurement findings.

    Not a re-implementation: the contract pipeline found these, with its own
    rules and its own citations, and this only restates them in the shape the
    procurement response uses so one list can be read end to end. The quote and
    offsets travel with them, so the procurement evidence verifier re-derives
    them against the purchase order text exactly as `verify_quotes` does.
    """
    out: List[ProcurementFinding] = []
    for raw in review.get("findings", []):
        try:
            severity = Severity(raw["severity"])
        except (KeyError, ValueError):
            continue
        out.append(
            ProcurementFinding(
                check_id=f"PO_TERM_{raw['rule_id']}",
                title=f"Purchase order term: {raw.get('title', raw['rule_id'])}",
                severity=severity,
                status=CheckStatus.BREACH,
                family=CheckFamily.PO_TERMS,
                subject_ref=raw.get("clause_number"),
                evidence=[
                    DocumentSpanEvidence(
                        source=SourceRef(kind="PO", id=review.get("contract_id") or ""),
                        quote=raw["matched_quote"],
                        start=raw["match_start"],
                        end=raw["match_end"],
                        note=f"clause {raw.get('clause_number') or '-'}",
                    )
                ],
                citations=[Citation(**c) for c in raw.get("citations", [])],
                harms=[side] if side != ProcurementSide.UNKNOWN else [],
                plain_summary=raw.get("plain_summary", ""),
                why_it_matters=raw.get("why_it_matters", ""),
                detector=raw.get("detector", "rule"),
                source="STATUTE",
            )
        )
    return out


def _overall_risk(findings: List[ProcurementFinding]) -> str:
    actionable = [f for f in findings if f.status == CheckStatus.BREACH and not f.provisional]
    if not actionable:
        return "LOW" if findings else "UNKNOWN"
    worst = max(actionable, key=lambda f: SEVERITY_ORDER[f.severity])
    return worst.severity.value


async def review_award(
    *,
    event: ProcurementEvent,
    rule_set: Optional[PolicyRuleSet] = None,
    side: ProcurementSide = ProcurementSide.BUYER,
    po_bytes: Optional[bytes] = None,
    po_filename: Optional[str] = None,
    review_id: Optional[str] = None,
    include_draft_rules: bool = False,
    run_graph: bool = True,
    persist: bool = True,
) -> Dict[str, Any]:
    """Evaluate an award against policy and statute, and review its purchase order.

    `run_graph=False` skips the statutory-text lookup and the written summary.
    The findings are identical either way -- the graph cannot change them -- which
    is what makes the evaluation harness able to score this function without
    standing Qdrant or Groq up.
    """
    review_id = review_id or new_review_id()
    rule_set = rule_set or EMPTY_RULE_SET.model_copy(deep=True)
    degraded: List[str] = []

    evaluation = evaluate_procurement(
        event, rule_set, side=side, include_draft_rules=include_draft_rules
    )
    outcomes = list(evaluation.outcomes)

    # --- The purchase order, through the existing contract pipeline.
    po_review: Optional[Dict[str, Any]] = None
    po_text = ""
    if po_bytes:
        from src.core.contract_service import review_contract
        from src.core.document_parser import DocumentParseError, parse_document

        try:
            # Parsed here as well as inside the contract pipeline, because the
            # evidence verifier needs the same normalized text the offsets index
            # into. `parse_document` normalizes exactly once and is deterministic,
            # so the two passes cannot disagree -- and a finding whose quote could
            # not be re-checked would be dropped, which is worse than a reparse.
            po_text = parse_document(po_bytes, po_filename or "purchase_order").text
            po_review = await review_contract(
                data=po_bytes,
                filename=po_filename or "purchase_order",
                contract_type=ContractType.VENDOR,
                position=_POSITION_FOR_SIDE.get(side),
                persist=False,
            )
            outcomes.extend(_po_findings_from_contract_review(po_review, side))
        except DocumentParseError as e:
            po_text = ""
            # A purchase order that cannot honestly be read is reported as a gap,
            # not swallowed. The rest of the review still stands.
            degraded.append(f"purchase order could not be parsed: {e}")
        except Exception as e:
            po_text = ""
            degraded.append(f"purchase order review failed: {type(e).__name__}")

    # --- Verification. Anything that cannot be re-derived is dropped, as the
    # contract compiler drops an ungrounded quote, and for the same reason: the
    # reader cannot tell which findings to trust if one of them is wrong.
    context = VerificationContext(event=event, documents={"po": po_text} if po_text else {})
    problems = verify_findings(outcomes, context)
    dropped = sorted(problems)
    if problems:
        pipeline_logger.log_step(
            STAGE,
            f"Review [{review_id}]: dropped {len(problems)} finding(s) whose evidence "
            f"did not re-derive",
            status="WARNING",
            details={"problems": problems},
        )
    kept = [
        o for o in outcomes
        if f"{o.check_id}|{o.subject_ref or ''}" not in problems
    ]

    # --- The graph. Runs after evaluation, never before: nothing it does can
    # change what a check found, which is why the outcomes are read-only inside
    # it. What it adds is the statute's own words and a written summary.
    narrative = None
    statutory_context: Dict[str, Any] = {}
    llm_available = True
    reranker_available = True
    if run_graph:
        from src.agents.procurement_graph import procurement_review_app

        try:
            graph_state = await procurement_review_app.ainvoke({
                "task_id": review_id,
                "event": event,
                "outcomes": kept,
                "side": side.value,
                "retry_count": 0,
                "llm_available": True,
                "reranker_available": True,
                "degraded_nodes": [],
            })
            enriched = graph_state.get("final_state") or {}
            narrative = enriched.get("narrative")
            statutory_context = enriched.get("statutory_context", {})
            llm_available = enriched.get("llm_available", True)
            reranker_available = enriched.get("reranker_available", True)
            degraded.extend(enriched.get("degraded_nodes", []))
        except Exception as e:
            # The review is already complete without the graph. A failure to
            # write it up nicely must not lose the findings.
            degraded.append(f"review write-up unavailable ({type(e).__name__})")
            llm_available = False

    # Confidence is measured on the pre-drop list, so a dropped finding still
    # costs score rather than tidying itself away.
    vendor = event.awarded_vendor
    basis = estimate_procurement_confidence(
        outcomes=outcomes,
        unverified_keys=dropped,
        side=side.value,
        category=event.category,
        msme_status=vendor.msme_status if vendor else MsmeStatus.UNKNOWN,
        ratified_rule_count=len(rule_set.enforceable_rules()),
        total_rule_count=len(rule_set.rules),
        covered_check_kinds=len({r.kind for r in rule_set.rules}),
        available_check_kinds=len(POLICY_TEMPLATES),
        po_review_confidence=(po_review or {}).get("confidence_score"),
        po_document_supplied=bool(po_bytes),
        llm_available=llm_available,
        reranker_available=reranker_available,
        degraded_nodes=degraded,
    )

    breaches = [o for o in kept if o.status == CheckStatus.BREACH]
    indicators = [o for o in kept if o.status == CheckStatus.INDICATOR]
    gaps = [o for o in kept if o.status == CheckStatus.UNDETERMINED]
    breaches.sort(key=lambda f: (-SEVERITY_ORDER[f.severity], f.check_id))
    indicators.sort(key=lambda f: (-SEVERITY_ORDER[f.severity], f.check_id))
    gaps.sort(key=lambda f: (-SEVERITY_ORDER[f.severity], f.check_id))

    risk_counts: Dict[str, int] = {}
    for f in breaches:
        if not f.provisional:
            risk_counts[f.severity.value] = risk_counts.get(f.severity.value, 0) + 1

    status_counts: Dict[str, int] = {}
    for o in kept:
        status_counts[o.status.value] = status_counts.get(o.status.value, 0) + 1

    clarifications = [
        f"{g.title}: {g.what_would_resolve_it}" for g in gaps[:8] if g.what_would_resolve_it
    ]

    response = AwardReviewResponse(
        review_id=review_id,
        status="PARTIAL_SUCCESS" if degraded or dropped else "SUCCESS",
        event_id=event.event_id,
        side=side,
        category=event.category,
        policy_id=rule_set.policy_id if rule_set.rules else None,
        policy_version=rule_set.version if rule_set.rules else None,
        policy_status=rule_set.status.value if rule_set.rules else None,
        overall_status=overall_status(
            type(evaluation)(outcomes=kept)
        ),
        overall_risk=_overall_risk(kept),
        risk_counts=risk_counts,
        status_counts=status_counts,
        confidence_score=basis.score,
        confidence_basis=basis.to_payload(),
        findings=breaches,
        indicators=indicators,
        undetermined_checks=gaps,
        checks_run=[
            CheckRun(
                check_id=o.check_id, title=o.title, status=o.status.value,
                severity=o.severity.value, family=o.family.value,
                subject_ref=o.subject_ref, source=o.source,
                policy_rule_id=o.policy_rule_id,
            )
            for o in kept
        ],
        remediations=build_remediations(breaches + indicators, side),
        narrative=narrative,
        statutory_context=statutory_context,
        po_review=po_review,
        po_confidence=(po_review or {}).get("confidence_score"),
        dropped_findings=dropped,
        degraded_nodes=degraded,
        clarification_questions=clarifications,
    ).model_dump(mode="json")

    pipeline_logger.log_step(
        STAGE,
        f"Review [{review_id}] complete -> {response['overall_status']} "
        f"Breaches [{len(breaches)}] Indicators [{len(indicators)}] "
        f"Gaps [{len(gaps)}] Confidence [{basis.score}]",
        status="SUCCESS",
    )

    if persist:
        from src.core.database import save_award_review

        await save_award_review({
            "review_id": review_id,
            "event_id": event.event_id,
            "policy_id": rule_set.policy_id if rule_set.rules else None,
            "policy_version": rule_set.version if rule_set.rules else None,
            "side": side.value,
            "status": response["status"],
            "event_snapshot": event.model_dump(mode="json"),
            "po_filename": po_filename,
            "po_document_text": po_text or None,
            "confidence_score": basis.score,
            "overall_status": response["overall_status"],
            "overall_risk": response["overall_risk"],
            "review": response,
        })

    return response


__all__ = ["new_review_id", "review_award", "INTEGRITY_LANGUAGE"]
