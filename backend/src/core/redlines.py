"""What to ask for on a clause the review flagged.

Written as negotiation asks rather than drafting to paste unread. Two reasons.
A replacement clause is only safe in context a reviewer of this kind does not
have -- the rest of the agreement, the commercial deal, what the parties
actually agreed. And the thing that gets a term changed is knowing what to ask
for and what to settle for, which is a conversation rather than a paragraph.

Each ask is tied to the rule that fired, so the mapping is deterministic: the
same finding always produces the same ask, and it is reviewable in one place
rather than regenerated per request.
"""

from typing import Any, Dict, List, Optional, Sequence

from src.schemas.contract import SEVERITY_ORDER, Severity
from src.schemas.contract_review import Redline

# rule_id -> (ask, suggested wording, fallback)
REDLINES: Dict[str, tuple] = {
    "NON_COMPETE_POST_TERM": (
        "Ask for this clause to be deleted, or cut back so that it only applies "
        "while you are still employed.",
        "The Employee shall not engage in any competing business during the "
        "subsistence of this Agreement. No restriction shall apply after the "
        "termination of employment.",
        "If it will not be removed, ask for the period to be cut to six months, "
        "the geography limited to the specific city, and the restriction to name "
        "particular named competitors rather than any competing business.",
    ),
    "EMPLOYMENT_BOND": (
        "Ask for the bond to be removed, or tied to training costs the employer "
        "can actually document.",
        "Where the Company has incurred certified external training expenditure "
        "on the Employee, the Employee shall on early resignation repay that "
        "documented expenditure, reduced proportionately for each completed month "
        "of service.",
        "At minimum ask for the amount to reduce month by month over the bond "
        "period, and for the figure to be backed by receipts.",
    ),
    "UNILATERAL_ARBITRATOR": (
        "Ask for the arbitrator to be appointed jointly, or by an arbitral "
        "institution.",
        "Any dispute shall be referred to a sole arbitrator appointed by mutual "
        "written agreement of the parties, failing which by an arbitral "
        "institution agreed between them.",
        "If they insist on appointing, ask for a panel of three with one "
        "appointee each and a jointly chosen presiding arbitrator.",
    ),
    "OUSTER_OF_LEGAL_REMEDY": (
        "Ask for the restriction on going to court to be removed, and for any "
        "shortened time limit to be deleted.",
        "Nothing in this Agreement shall restrict either party from pursuing any "
        "remedy available to it in law, within the period allowed by the "
        "Limitation Act, 1963.",
        "If an arbitration clause is the real intention, ask for it to say so "
        "plainly instead of barring proceedings generally.",
    ),
    "PENALTY_STIPULATION": (
        "Ask for the fixed sum to be replaced with actual proven loss, or for it "
        "to be capped.",
        "In the event of delay the defaulting party shall compensate the other "
        "for loss actually suffered and proven, subject to a maximum of [X]% of "
        "the amount then outstanding.",
        "If a fixed figure is unavoidable, ask for it to be mutual so that it "
        "applies to both sides' defaults.",
    ),
    "UNCAPPED_INDEMNITY": (
        "Ask for a financial cap on the indemnity and for indirect losses to be "
        "carved out.",
        "The indemnifying party's aggregate liability under this indemnity shall "
        "not exceed the total fees paid under this Agreement in the twelve months "
        "preceding the claim, and shall exclude indirect, incidental and "
        "consequential loss and loss of profit.",
        "If no cap is accepted, ask at least for it to be mutual and limited to "
        "third-party claims caused by your own proven breach.",
    ),
    "UNILATERAL_TERMINATION": (
        "Ask for the termination right to be mutual, on the same notice.",
        "Either party may terminate this Agreement by giving the other not less "
        "than sixty days prior written notice.",
        "If they keep a shorter notice period, ask for a payment in lieu covering "
        "the difference.",
    ),
    "UNILATERAL_AMENDMENT": (
        "Ask for changes to require your written agreement, or for a right to "
        "exit without penalty if you reject one.",
        "No amendment to this Agreement shall be effective unless made in writing "
        "and signed by both parties. Where a change is required by law, the other "
        "party may terminate without penalty within thirty days of notice of it.",
        "At minimum ask for thirty days' advance written notice of any change, "
        "sent to you directly rather than posted to a website.",
    ),
    "AUTO_RENEWAL": (
        "Ask for the renewal to require a positive opt-in, or for the "
        "cancellation window to be widened.",
        "This Agreement shall expire at the end of the then current term unless "
        "the parties agree in writing to renew it.",
        "If automatic renewal stays, ask for written notice to be sent to you at "
        "least thirty days before the cancellation deadline.",
    ),
    "BROAD_IP_ASSIGNMENT": (
        "Ask for the assignment to be narrowed to work actually made for this "
        "engagement, and attach a schedule of what you already own.",
        "The Employee assigns to the Company intellectual property created in the "
        "course of the Employee's duties and using Company resources. Material "
        "listed in Schedule [X], and anything created outside working hours "
        "without Company resources and unrelated to the Company's business, "
        "remains the property of the Employee.",
        "At minimum ask to exclude work unrelated to the employer's business and "
        "created on your own time and equipment.",
    ),
    "PERPETUAL_CONFIDENTIALITY": (
        "Ask for a fixed term, with genuine trade secrets handled separately.",
        "The obligations of confidentiality shall continue for three years after "
        "termination, save in respect of trade secrets, which shall continue for "
        "so long as they remain trade secrets.",
        "If perpetual stays, ask for clear carve-outs for information that becomes "
        "public, is independently developed, or must be disclosed by law.",
    ),
    "FOREIGN_EXCLUSIVE_JURISDICTION": (
        "Ask for Indian law and an Indian forum, or for arbitration seated in India.",
        "This Agreement shall be governed by the laws of India and the courts at "
        "[your city] shall have exclusive jurisdiction.",
        "If foreign governing law is fixed, ask at least for arbitration seated in "
        "India so enforcement does not require litigating abroad.",
    ),
    "EXCESSIVE_SECURITY_DEPOSIT": (
        "Ask for the deposit to be reduced, and for refund terms in writing.",
        "The Lessee shall pay an interest-free security deposit equivalent to two "
        "months rent, refundable within thirty days of vacating, less only "
        "deductions supported by an itemised written account.",
        "If the amount will not move, insist on a fixed refund deadline and a "
        "written itemisation of any deduction.",
    ),
    "LOCK_IN_WITHOUT_EXIT": (
        "Ask for an exit on notice, and for the lock-in to fall away if the other "
        "side is in breach.",
        "The Lessee may terminate during the lock-in period by giving two months "
        "notice and paying one month's rent. The lock-in shall not apply where the "
        "Lessor is in breach or the premises become uninhabitable.",
        "At minimum ask for the lock-in to be mutual, so the landlord cannot evict "
        "you during it either.",
    ),
    "ONE_SIDED_ASSIGNMENT": (
        "Ask for the consent requirement to apply both ways.",
        "Neither party shall assign this Agreement without the prior written "
        "consent of the other, such consent not to be unreasonably withheld.",
        "If they need to assign to group companies, ask for written notice to you "
        "and a right to terminate if you object.",
    ),
    "DATA_SHARING_WITHOUT_CONSENT": (
        "Ask for the purposes to be listed specifically, and for a way to withdraw "
        "consent.",
        "Personal data shall be processed only for the purposes listed in Schedule "
        "[X]. Consent may be withdrawn at any time by written notice, and data "
        "shall be deleted within thirty days of withdrawal or of termination.",
        "At minimum ask for the categories of third party to be named rather than "
        "described as affiliates and partners.",
    ),
    "UNFAIR_TERM_WAIVER": (
        "Ask for the waiver to be deleted.",
        "Nothing in this Agreement shall exclude or limit any right or remedy "
        "available to either party under applicable law.",
        "If it stays, note that a waiver of statutory rights is generally "
        "ineffective, so it is worth confirming in writing what remedies survive.",
    ),
}

_GENERIC = (
    "Raise this clause with the other side and ask for it to be made mutual, "
    "bounded, or removed.",
    None,
    None,
)


def redline_for(finding: Any) -> Optional[Redline]:
    rule_id = getattr(finding, "rule_id", None) or (
        finding.get("rule_id") if isinstance(finding, dict) else None
    )
    if not rule_id:
        return None

    def attr(name, default=None):
        if isinstance(finding, dict):
            return finding.get(name, default)
        return getattr(finding, name, default)

    severity = attr("severity", Severity.MEDIUM)
    if not isinstance(severity, Severity):
        severity = Severity(str(severity))

    ask, wording, fallback = REDLINES.get(rule_id, _GENERIC)
    return Redline(
        rule_id=rule_id,
        clause_index=attr("clause_index"),
        clause_number=attr("clause_number"),
        title=attr("title", rule_id),
        severity=severity,
        ask=ask,
        suggested_wording=wording,
        fallback=fallback,
        source="rule" if rule_id in REDLINES else "generic",
    )


def build_redlines(findings: Sequence[Any]) -> List[Redline]:
    """One redline per finding, worst first, with duplicates collapsed.

    A rule that fires on three clauses produces one ask, not three: the
    negotiation is about the term, not about each place it appears.
    """
    seen, redlines = set(), []
    for finding in findings or []:
        redline = redline_for(finding)
        if redline is None or redline.rule_id in seen:
            continue
        seen.add(redline.rule_id)
        redlines.append(redline)
    redlines.sort(key=lambda r: (-SEVERITY_ORDER[r.severity], r.rule_id))
    return redlines
