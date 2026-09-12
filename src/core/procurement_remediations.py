"""What to do about each finding, before the order goes out.

The sibling of `redlines.py`, and written for the same reasons. The mapping is
static, so the same finding always produces the same action and it is reviewable
in one place rather than regenerated per request. And it is written as an action
with an owner rather than as drafting to paste unread, because what actually gets
a purchase order changed is knowing who has to do what and what to accept if they
refuse.

The one structural difference is that this file answers to two readers. The
buyer-side action on an MSMED payment term is "cut it to 45 days before you
release the order". The supplier-side action on the same finding is "the term is
void to that extent and interest accrues whatever you signed". Same finding, same
statute, opposite instruction -- which is the whole reason the side is declared.

Findings at INFO carry no action, exactly as `build_redlines` filters them out:
telling somebody to spend negotiating capital on something that does not matter
is advice against their own interest.
"""

from typing import Any, Dict, List, Sequence, Tuple

from src.schemas.contract import SEVERITY_ORDER, Severity
from src.schemas.procurement import CheckStatus, ProcurementSide

# check_id -> (action, what good looks like, what to accept if refused)
Remediation = Tuple[str, str, str]

BUYER_ACTIONS: Dict[str, Remediation] = {
    "MSMED_TERM_EXCEEDS_STATUTORY_CAP": (
        "Cut the payment term to 45 days from acceptance before the order is released, and "
        "confirm it is agreed in writing.",
        "Payment shall be made within 45 days of acceptance of the goods or services, as "
        "agreed in writing between the parties.",
        "There is nothing to settle for. The proviso to section 15 is a ceiling, not a "
        "default, and a longer term is void to that extent whatever both sides agree.",
    ),
    "MSMED_PAYMENT_OVERDUE": (
        "Release the payment now and have finance compute the section 16 interest rather "
        "than wait for the supplier to raise it.",
        "A dated calculation of interest at three times the RBI bank rate, compounded "
        "monthly from the appointed day, attached to the payment advice.",
        "If the payment cannot be released this period, record the accrued interest as a "
        "liability -- it is accruing whether or not anyone books it.",
    ),
    "MSMED_INTEREST_QUANTUM": (
        "Supply the RBI bank rate series covering the delay so the exposure can be quantified.",
        "The notified bank rate for each month of the delay period.",
        "Failing that, have finance compute it from the RBI notifications directly.",
    ),
    "RELATED_PARTY_AWARD_UNAPPROVED": (
        "Hold the order until the section 188 approval is obtained and minuted.",
        "A board resolution approving the transaction, and where the prescribed thresholds "
        "are crossed, a shareholders' resolution.",
        "If the ordinary-course and arm's-length carve-outs are being relied on instead, "
        "minute the basis for each before the order is released, not afterwards.",
    ),
    "RELATED_PARTY_AUDIT_COMMITTEE_APPROVAL": (
        "Obtain audit committee approval before the order is released.",
        "An audit committee resolution referencing this transaction specifically.",
        "An omnibus approval, where the committee has granted one that genuinely covers "
        "this transaction type and value.",
    ),
    "VENDOR_PROCESSES_DATA_WITHOUT_DPA": (
        "Execute a data processing agreement before any personal data reaches the vendor.",
        "Processing limited to the stated purpose, on the company's instructions, with "
        "deletion on termination and a breach-notification obligation.",
        "At minimum, a written instruction limiting the purpose and prohibiting onward "
        "transfer, pending a full agreement.",
    ),
    "MIN_QUOTES_BY_VALUE": (
        "Obtain the missing quotes before awarding, or have the shortfall approved as a "
        "documented exception.",
        "The policy minimum, from vendors capable of the scope.",
        "A written exception approved at the level policy requires, recording why the "
        "market could not supply more.",
    ),
    "APPROVAL_AUTHORITY": (
        "Route the award to the approver the delegation of authority names before issuing.",
        "Approval at or above the level the value requires.",
        "Nothing. An approval below the delegated limit is not an approval of this purchase.",
    ),
    "APPROVAL_BEFORE_COMMITMENT": (
        "Stop issuing orders ahead of approval. Where this one has gone out, have it ratified "
        "explicitly and record that it was retrospective.",
        "Purchase orders issued only after the final approval timestamp.",
        "A minuted retrospective ratification that says plainly it is retrospective.",
    ),
    "APPROVED_VENDOR_REQUIRED": (
        "Complete vendor onboarding before the order, or record an approved exception.",
        "Financial, capability and compliance checks completed and the vendor added to the master.",
        "A time-limited exception naming who accepted the unassessed risk.",
    ),
    "LOWEST_RESPONSIVE_AWARD": (
        "Record why the lower bid was not taken, and have it approved.",
        "A written comparison on the grounds actually used -- capability, lead time, "
        "total cost of ownership -- signed by the approver.",
        "If no reason can be given, re-examine the award.",
    ),
    "PO_EXCEEDS_AWARDED_VALUE": (
        "Reduce the order to the awarded value, or re-approve at the higher figure.",
        "A purchase order matching the award, or a fresh approval covering the increase.",
        "A documented variation approved at the level the new total requires.",
    ),
    "SPLIT_PO_AVOIDANCE": (
        "Consolidate the requirement and take it through the process the combined value "
        "requires.",
        "One competitive event covering the whole requirement.",
        "If the orders are genuinely unrelated, record why -- different requirement, "
        "different timing, unforeseeable at the first order.",
    ),
    "PAYMENT_TERMS_CAP": (
        "Bring the payment term back inside policy before issuing.",
        "Terms at or under the policy ceiling.",
        "A treasury-approved exception, where the commercial gain is quantified.",
    ),
    "SINGLE_SOURCE_JUSTIFICATION": (
        "Record the justification and have it approved before the order goes out.",
        "A note naming why no alternative exists -- proprietary part, incumbent mid-project, "
        "genuine emergency -- approved at the level policy requires.",
        "Nothing. A reason written after the question is asked is not a justification.",
    ),
    "LATE_BID_REJECTION": (
        "Exclude the late bid and re-evaluate, or cancel and re-tender.",
        "Bids received after the deadline recorded as late and not evaluated.",
        "If the late bid is to stand, extend the deadline for every bidder and take fresh bids.",
    ),
    "MANDATORY_BID_WINDOW": (
        "Extend the deadline to the policy minimum and notify every invited bidder.",
        "The full response window policy requires.",
        "A recorded urgency exception, approved before the enquiry goes out rather than after.",
    ),
    "BUDGET_AVAILABILITY": (
        "Obtain the budget increase before committing, not at invoice.",
        "An approved budget covering the award value.",
        "Rescope the requirement to what the budget covers.",
    ),
    "SCOPE_DRIFT": (
        "Remove the untendered lines from the order, or price them competitively.",
        "Every ordered line traceable to the enquiry.",
        "A documented variation with at least a benchmark against the tendered rates.",
    ),
    "RATE_CONTRACT_ADHERENCE": (
        "Check the ordered unit prices against the rate contract before release.",
        "Ordered prices at or below the contracted rates.",
        "A recorded reason where a line genuinely falls outside the contract's scope.",
    ),
    "NEAR_IDENTICAL_TOTALS": (
        "Ask the bidders how their prices were arrived at before releasing the award.",
        "An explanation that accounts for the closeness -- a shared published price list, "
        "a rate contract, a common upstream distributor.",
        "If no explanation holds up, widen the bid list and re-tender rather than treating "
        "this as a finding against anyone.",
    ),
    "IDENTICAL_UNIT_PRICES": (
        "Ask where the line pricing came from before releasing the award.",
        "A source for the identical rates -- a price list, a rate contract, a shared BOQ.",
        "Widen the bid list on the next event for this category.",
    ),
    "SHARED_IDENTIFIERS": (
        "Establish whether the bidders are independent before releasing the award.",
        "Ownership and directorship confirmation for each, and a declaration of any "
        "relationship between them.",
        "If they are related, treat the event as having had one bidder and re-run it.",
    ),
    "CONSTANT_SPREAD": (
        "Ask how the bids were priced before releasing the award.",
        "An explanation for the regular stepping between bids.",
        "Widen the bid list and re-tender.",
    ),
    "COVER_BIDDING": (
        "Confirm the high bidder actually intended to compete.",
        "A bid the vendor can explain on its own cost base.",
        "Remove non-competing bidders from the list so the quote count reflects real competition.",
    ),
    "ROTATING_WINNERS": (
        "Review the bid list for this category and bring in vendors from outside it.",
        "New entrants invited to the next event.",
        "If the supplier base is genuinely this narrow, record that -- it changes how the "
        "quote-count requirement should be read.",
    ),
    "SINGLE_RESPONSIVE_BID": (
        "Record this as the single-source award it effectively was, and apply the "
        "single-source controls.",
        "Single-source justification and the approval that goes with it.",
        "Re-tender with requirements the market can actually meet, if the "
        "disqualifications were on technicalities.",
    ),
}

# Only where the instruction genuinely differs. Everything else falls through to
# the buyer action, which is usually the right advice for either reader.
SUPPLIER_ACTIONS: Dict[str, Remediation] = {
    "MSMED_TERM_EXCEEDS_STATUTORY_CAP": (
        "Push back on the payment term before you sign, citing section 15. You do not lose "
        "the protection by having agreed to a longer period.",
        "Payment within 45 days of acceptance, agreed in writing.",
        "If the buyer will not amend it, sign and keep the correspondence. The term is void "
        "to the extent it exceeds 45 days, and interest under section 16 runs regardless of "
        "what the order says.",
    ),
    "MSMED_PAYMENT_OVERDUE": (
        "Raise the delay in writing now. Interest has been accruing from the appointed day "
        "without you having to ask for it.",
        "A dated statement of principal and interest at three times the RBI bank rate, "
        "compounded monthly from the appointed day.",
        "If the buyer disputes it, the MSME Samadhaan facilitation route exists for exactly "
        "this and does not require you to sue.",
    ),
    "PAYMENT_TERMS_CAP": (
        "The buyer's own policy caps this term. Say so -- you are asking them to follow "
        "their own rule, not to make an exception for you.",
        "Terms at or under the buyer's policy ceiling.",
        "Ask for a milestone or advance structure instead.",
    ),
}

_GENERIC: Remediation = (
    "Review this before the order is released.",
    "A recorded decision by whoever owns this control.",
    "If it is being accepted, record who accepted it and why.",
)


def build_remediations(
    findings: Sequence[Any], side: ProcurementSide = ProcurementSide.BUYER
) -> List[Dict[str, Any]]:
    """One action per finding worth acting on, worst first.

    Collapsed by `check_id`: the action is about the control that failed, not
    about each place it shows up. Indicators keep their own wording, which asks a
    question rather than instructing a fix -- there may be nothing to fix.
    """
    table = dict(BUYER_ACTIONS)
    if side == ProcurementSide.SUPPLIER:
        table.update(SUPPLIER_ACTIONS)

    seen: Dict[str, Dict[str, Any]] = {}
    for f in findings:
        if f.status not in {CheckStatus.BREACH, CheckStatus.INDICATOR}:
            continue
        if SEVERITY_ORDER[f.severity] <= SEVERITY_ORDER[Severity.INFO]:
            continue
        if f.check_id in seen:
            continue
        action, good, fallback = table.get(f.check_id, _GENERIC)
        seen[f.check_id] = {
            "check_id": f.check_id,
            "title": f.title,
            "severity": f.severity.value,
            "status": f.status.value,
            "is_indicator": f.status == CheckStatus.INDICATOR,
            "action": action,
            "what_good_looks_like": good,
            "if_refused": fallback,
            "subject_ref": f.subject_ref,
        }

    return sorted(
        seen.values(),
        key=lambda r: (-SEVERITY_ORDER[Severity(r["severity"])], r["check_id"]),
    )


def missing_actions(check_ids: Sequence[str]) -> List[str]:
    """Check ids with no hand-written action. Used by the tests, not at runtime."""
    return [c for c in check_ids if c not in BUYER_ACTIONS]


__all__ = ["BUYER_ACTIONS", "SUPPLIER_ACTIONS", "build_remediations", "missing_actions"]
