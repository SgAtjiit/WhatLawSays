"""Procurement compliance endpoints.

Shaped to match `contracts.py` -- same rate-limit helper, same upload sniffing,
same 404-on-no-review, same real DELETE -- so a caller who has used one knows how
the other behaves.

Two differences worth stating. An event that cannot honestly be checked is
refused with a 422 rather than reviewed, for the reason `DocumentParseError`
exists on the contract side: an empty review reads as a clean bill of health. And
`provided_collections` is a required part of the payload, because the difference
between "no approvals" and "approvals were not exported" is the difference
between a breach and a gap, and only the caller knows which it is.
"""

import json
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError

from src.core.database import (
    delete_award_review,
    delete_policy,
    get_award_review,
    get_policy,
    list_policies,
    save_policy,
)
from src.core.logger import pipeline_logger
from src.core.procurement_rules import POLICY_TEMPLATES, STATUTORY_CHECKS
from src.core.procurement_service import new_review_id, review_award
from src.schemas.procurement import (
    KNOWN_COLLECTIONS,
    CheckStatus,
    PolicyCheckKind,
    PolicyRule,
    PolicyRuleSet,
    PolicySetStatus,
    ProcurementEvent,
    ProcurementSide,
    RuleOrigin,
    RuleStatus,
)
from src.schemas.procurement_review import AwardReviewResponse

router = APIRouter()

STAGE = "PROCUREMENT API"

# A review is at most one contract sub-review's worth of LLM calls plus
# retrieval, against one shared key -- the same reasoning as the contract cap.
REVIEW_RATE_LIMIT_PER_MINUTE = 6
_HISTORY: Dict[str, List[float]] = {}


def _enforce_rate_limit(client_ip: str) -> None:
    now = time.time()
    recent = [t for t in _HISTORY.get(client_ip, []) if now - t < 60]
    if len(recent) >= REVIEW_RATE_LIMIT_PER_MINUTE:
        pipeline_logger.log_step(
            STAGE, f"Rate limit exceeded for IP [{client_ip}]", status="WARNING"
        )
        raise HTTPException(
            status_code=429,
            detail=(
                f"Procurement reviews are limited to {REVIEW_RATE_LIMIT_PER_MINUTE} "
                "per minute. Please try again shortly."
            ),
        )
    recent.append(now)
    _HISTORY[client_ip] = recent


def _parse_event(raw: str) -> ProcurementEvent:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"`event` is not valid JSON: {e}")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="`event` must be a JSON object.")
    try:
        event = ProcurementEvent(**payload)
    except ValidationError as e:
        raise HTTPException(
            status_code=422,
            detail="; ".join(
                f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()[:8]
            ),
        )
    if not event.bids and event.award is None:
        # Refused rather than reviewed. A review of an event with nothing in it
        # produces no findings, and no findings reads as a clean event.
        raise HTTPException(
            status_code=422,
            detail=(
                "This event carries neither bids nor an award, so there is nothing to "
                "check. It is refused rather than returned as a review with no findings, "
                "which would read as a clean result."
            ),
        )
    if not event.provided_collections:
        raise HTTPException(
            status_code=422,
            detail=(
                "`provided_collections` is required. It names which parts of the event you "
                "actually supplied, so that an omitted array is reported as a gap rather "
                "than treated as an empty one -- the difference between 'nobody approved "
                "this' and 'the approvals were not exported'. Known collections: "
                + ", ".join(sorted(KNOWN_COLLECTIONS))
            ),
        )
    return event


def _parse_side(raw: Optional[str]) -> ProcurementSide:
    if not raw:
        return ProcurementSide.BUYER
    try:
        return ProcurementSide(raw.strip().upper())
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown side {raw!r}. Valid values: "
            + ", ".join(s.value for s in ProcurementSide),
        )


async def _rule_set_or_none(policy_id: Optional[str]) -> Optional[PolicyRuleSet]:
    if not policy_id:
        return None
    record = await get_policy(policy_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No policy {policy_id!r}.")
    if not record.get("rule_set"):
        raise HTTPException(
            status_code=409, detail=f"Policy {policy_id!r} has no compiled rule set yet."
        )
    return PolicyRuleSet(**record["rule_set"])


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------

@router.post("/awards", response_model=AwardReviewResponse, tags=["Procurement"])
async def review_an_award(
    request: Request,
    event: str = Form(..., description="The sourcing event as a JSON object"),
    policy_id: Optional[str] = Form(None, description="Policy version to enforce"),
    side: Optional[str] = Form("BUYER", description="BUYER or SUPPLIER"),
    include_draft_rules: bool = Form(
        False,
        description=(
            "Enforce rules nobody has ratified. Off by default. What it produces is "
            "marked provisional, excluded from every count, and caps confidence at 0.45."
        ),
    ),
    po_file: Optional[UploadFile] = File(
        None, description="The awarded purchase order: PDF, DOCX or TXT"
    ),
):
    """Check an award against your policy and Indian statute."""
    client_ip = request.client.host if request.client else "127.0.0.1"
    _enforce_rate_limit(client_ip)

    parsed = _parse_event(event)
    rule_set = await _rule_set_or_none(policy_id)
    po_bytes = await po_file.read() if po_file else None

    return await review_award(
        event=parsed,
        rule_set=rule_set,
        side=_parse_side(side),
        po_bytes=po_bytes,
        po_filename=po_file.filename if po_file else None,
        review_id=new_review_id(),
        include_draft_rules=include_draft_rules,
    )


@router.get("/awards/{review_id}", tags=["Procurement"])
async def fetch_review(review_id: str):
    record = await get_award_review(review_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No review {review_id!r}.")
    if not record.get("review"):
        return {
            "review_id": review_id,
            "status": record.get("status"),
            "error": record.get("error"),
            "event_id": record.get("event_id"),
        }
    return record["review"]


@router.delete("/awards/{review_id}", tags=["Procurement"])
async def remove_review(review_id: str):
    """Delete a review and the event snapshot it rests on.

    A real delete. A bid tab carries vendor pricing, PAN and bank details, and a
    retention promise this service cannot keep would be worse than none.
    """
    return {"review_id": review_id, "deleted": await delete_award_review(review_id)}


@router.get("/awards/{review_id}/actions", tags=["Procurement"])
async def get_actions(review_id: str):
    record = await get_award_review(review_id)
    if record is None or not record.get("review"):
        raise HTTPException(status_code=404, detail=f"No completed review {review_id!r}.")
    return {"review_id": review_id, "remediations": record["review"].get("remediations", [])}


@router.get("/awards/{review_id}/report.pdf", tags=["Procurement"])
async def download_award_report(review_id: str):
    """The review as a PDF, leading with what to fix before the order goes out."""
    from src.core.report_export import build_procurement_report_pdf

    record = await get_award_review(review_id)
    if record is None or not record.get("review"):
        raise HTTPException(status_code=404, detail=f"No completed review {review_id!r}.")
    pdf = build_procurement_report_pdf(record["review"])
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="award-review-{review_id}.pdf"'
        },
    )


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

class RuleUpsert(BaseModel):
    rule_id: str
    kind: PolicyCheckKind
    params: Dict[str, Any] = Field(default={})
    status: RuleStatus = RuleStatus.RATIFIED
    note: str = ""


class PolicyUpsert(BaseModel):
    """A rule set authored by hand.

    This is the path that exists before policy compilation does, and remains the
    fallback whenever compilation is unavailable. Rules created here are
    `origin=HUMAN` and need no grounding quote, because a person wrote them.
    """

    org_label: str = ""
    company_id: str = ""
    rules: List[RuleUpsert] = Field(default=[])


@router.post("/policies", tags=["Procurement"])
async def create_policy(payload: PolicyUpsert):
    policy_id = new_review_id()
    rule_set = PolicyRuleSet(
        policy_id=policy_id,
        company_id=payload.company_id,
        org_label=payload.org_label,
        status=PolicySetStatus.DRAFT,
        rules=[
            PolicyRule(
                rule_id=r.rule_id, kind=r.kind, params=r.params,
                status=r.status, origin=RuleOrigin.HUMAN, note=r.note,
            )
            for r in payload.rules
        ],
        not_addressed=[
            k for k in PolicyCheckKind if k not in {r.kind for r in payload.rules}
        ],
    )
    await save_policy({
        "policy_id": policy_id,
        "company_id": payload.company_id,
        "org_label": payload.org_label,
        "version": 1,
        "status": rule_set.status.value,
        "rule_count": len(rule_set.rules),
        "ratified_rule_count": sum(1 for r in rule_set.rules if r.enforceable),
        "rule_set": rule_set.model_dump(mode="json"),
    })
    return rule_set.model_dump(mode="json")


@router.get("/policies", tags=["Procurement"])
async def all_policies(limit: int = 50):
    return {"policies": await list_policies(limit)}


@router.get("/policies/{policy_id}", tags=["Procurement"])
async def fetch_policy(policy_id: str):
    record = await get_policy(policy_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No policy {policy_id!r}.")
    return record.get("rule_set") or {"policy_id": policy_id, "status": record.get("status")}


@router.patch("/policies/{policy_id}/rules/{rule_id}", tags=["Procurement"])
async def ratify_rule(policy_id: str, rule_id: str, payload: Dict[str, Any]):
    """Ratify, edit or reject one drafted rule.

    Editing a rule makes it the person's rather than the model's: `origin` becomes
    HUMAN and the grounding quote is cleared, because the quote evidenced what the
    model read, and that is no longer what the rule says.
    """
    record = await get_policy(policy_id)
    if record is None or not record.get("rule_set"):
        raise HTTPException(status_code=404, detail=f"No policy {policy_id!r}.")
    rule_set = PolicyRuleSet(**record["rule_set"])
    if rule_set.status == PolicySetStatus.ACTIVE:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Policy {policy_id!r} is active, and an active version is immutable so that "
                "past reviews stay re-derivable against the rules that produced them. "
                "Create a new version instead."
            ),
        )

    action = str(payload.get("action", "")).upper()
    target = next((r for r in rule_set.rules if r.rule_id == rule_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"No rule {rule_id!r} in this policy.")

    if action == "RATIFY":
        target.status = RuleStatus.RATIFIED
    elif action == "REJECT":
        target.status = RuleStatus.REJECTED
    elif action == "EDIT":
        target.params = payload.get("params", target.params)
        target.status = RuleStatus.EDITED
        target.origin = RuleOrigin.HUMAN
        target.grounding = None
    else:
        raise HTTPException(
            status_code=422, detail="`action` must be RATIFY, EDIT or REJECT."
        )
    target.note = payload.get("note", target.note)
    target.ratified_by = payload.get("actor")

    await save_policy({
        "policy_id": policy_id,
        "ratified_rule_count": sum(1 for r in rule_set.rules if r.enforceable),
        "rule_set": rule_set.model_dump(mode="json"),
    }, update_only=True)
    return target.model_dump(mode="json")


@router.post("/policies/{policy_id}/activate", tags=["Procurement"])
async def activate_policy(policy_id: str):
    """Freeze a version and put it in force.

    Refused while any rule is still DRAFT. A half-ratified set enforced as though
    it were confirmed is the failure this whole step exists to prevent.
    """
    record = await get_policy(policy_id)
    if record is None or not record.get("rule_set"):
        raise HTTPException(status_code=404, detail=f"No policy {policy_id!r}.")
    rule_set = PolicyRuleSet(**record["rule_set"])
    drafts = [r.rule_id for r in rule_set.drafted_rules()]
    if drafts:
        raise HTTPException(
            status_code=409,
            detail=(
                "These rules have not been reviewed yet: " + ", ".join(drafts)
                + ". Ratify, edit or reject each one before activating -- a rule nobody "
                "confirmed is this system's reading of your policy, not your policy."
            ),
        )
    rule_set.status = PolicySetStatus.ACTIVE
    await save_policy({
        "policy_id": policy_id,
        "status": PolicySetStatus.ACTIVE.value,
        "rule_set": rule_set.model_dump(mode="json"),
    }, update_only=True)
    return rule_set.model_dump(mode="json")


@router.delete("/policies/{policy_id}", tags=["Procurement"])
async def remove_policy(policy_id: str):
    return {"policy_id": policy_id, "deleted": await delete_policy(policy_id)}


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

@router.get("/procurement/meta/checks", tags=["Procurement"])
async def check_catalogue():
    """Everything this system can check, and what each one needs.

    Published rather than kept internal. It is what makes a ratification UI
    buildable, and it is the honest public statement of the system's reach: a
    reader can see what is not on this list and know it was not checked.
    """
    return {
        "statutory_checks": [
            {
                "check_id": spec.check_id,
                "title": spec.title,
                "severity": spec.severity.value,
                "family": spec.family.value,
                "citations": [c.model_dump() for c in spec.citations],
                "requires": list(spec.requires),
            }
            for spec, _ in STATUTORY_CHECKS
        ],
        "policy_kinds": [
            {
                "kind": kind.value,
                "check_id": template.spec.check_id,
                "title": template.spec.title,
                "severity": template.spec.severity.value,
                "parameters": list(template.param_keys),
                "requires": list(template.requires),
            }
            for kind, template in POLICY_TEMPLATES.items()
        ],
        "bid_integrity_signals": _integrity_catalogue(),
    }


def _integrity_catalogue() -> List[Dict[str, Any]]:
    from src.core.bid_integrity import INTEGRITY_LANGUAGE, SPECS

    return [
        {
            "check_id": check_id,
            "title": spec.title,
            "severity": spec.severity.value,
            "reported_as": CheckStatus.INDICATOR.value,
            "note": INTEGRITY_LANGUAGE,
        }
        for check_id, spec in SPECS.items()
    ]


@router.get("/procurement/meta/supported", tags=["Procurement"])
async def supported_options():
    from src.core.document_parser import MAX_FILE_BYTES, SUPPORTED_MEDIA_TYPES

    return {
        "sides": [s.value for s in ProcurementSide],
        "known_collections": sorted(KNOWN_COLLECTIONS),
        "policy_kinds": [k.value for k in PolicyCheckKind],
        "statuses": [s.value for s in CheckStatus],
        "po_media_types": sorted(SUPPORTED_MEDIA_TYPES),
        "max_file_bytes": MAX_FILE_BYTES,
        "rate_limit_per_minute": REVIEW_RATE_LIMIT_PER_MINUTE,
    }
