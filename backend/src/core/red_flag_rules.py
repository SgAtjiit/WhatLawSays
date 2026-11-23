"""Deterministic red-flag detection over contract clauses.

Rules first, model second. A model asked to "find the red flags" produces
findings that cannot be reproduced, audited, or regression-tested, which is the
opposite of what the rest of this codebase is built for. So the dangerous
patterns that can be recognised from the text are recognised by pattern, and the
model's later job is to explain what a rule found, not to decide whether it is
there.

Two properties make a finding trustworthy:

* **It quotes the document.** Every finding carries the offsets of the span that
  triggered it, so the grounding verifier can prove the quote is real -- the same
  guarantee the statutory pipeline gives for section citations.
* **It carries its own citation.** Retrieval cannot be relied on to rediscover
  the governing provision, because contracts and statutes are written in
  different registers. Measured against the indexed corpus, "restraint of trade
  void agreement" puts Contract Act s.27 at rank 1, while "employee shall not
  join a competing business for two years" does not return it at all. A rule that
  waited for retrieval to find s.27 would simply never fire.
"""

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from src.core.pattern_utils import compile_loose
from src.core.acts import (
    ACT_ARBITRATION,
    ACT_CONSUMER,
    ACT_CONTRACT,
    ACT_DPDP,
    ACT_TRANSFER_OF_PROPERTY,
)
from src.schemas.contract import (
    SEVERITY_ORDER,
    WEAKER_POSITIONS,
    Citation,
    Clause,
    ClauseCategory,
    PartyPosition,
    RedFlagFinding,
    Severity,
)

_FLAGS = re.I | re.S


def _p(pattern: str) -> re.Pattern:
    """Compile a rule pattern, tolerating the line wrapping every contract has."""
    return compile_loose(pattern, _FLAGS)


# Every label a contract uses for the side that drafted it. Kept in one place
# because a missing label fails silently: the rule simply never fires, and an
# absent red flag reads exactly like a clean contract. Two real misses -- a lease
# saying "Lessor" and a SaaS agreement saying "Provider" -- were each found only
# by adding a fixture that should have tripped the rule.
PARTY = (
    "(?:company|employer|landlord|lessor|licensor|lender|client|customer|"
    "provider|supplier|vendor|service provider|principal|bank|platform|"
    "first party|second party|disclosing party)"
)


@dataclass(frozen=True)
class RedFlagRule:
    rule_id: str
    title: str
    severity: Severity
    plain_summary: str
    why_it_matters: str
    # The span of the first `require_any` hit becomes the finding's quote, so
    # these patterns should match the operative words, not a whole paragraph.
    require_any: Tuple[re.Pattern, ...]
    require_all: Tuple[re.Pattern, ...] = ()
    exclude_any: Tuple[re.Pattern, ...] = ()
    categories: Tuple[ClauseCategory, ...] = ()
    harms: Tuple[PartyPosition, ...] = ()
    citations: Tuple[Citation, ...] = ()
    # True where the clause is unenforceable or void whoever it favours. Such a
    # finding still matters to the party it benefits, who would otherwise plan
    # around a protection that would not survive a challenge.
    void_regardless: bool = False


def _cite(act: str, section: str, note: str) -> Citation:
    return Citation(act=act, section_number=section, note=note)


def _shift(severity: Severity, steps: int) -> Severity:
    order = SEVERITY_ORDER[severity] + steps
    order = max(0, min(4, order))
    return next(s for s, value in SEVERITY_ORDER.items() if value == order)


# ---------------------------------------------------------------------------
# The ruleset
# ---------------------------------------------------------------------------

RULES: Tuple[RedFlagRule, ...] = (
    RedFlagRule(
        rule_id="NON_COMPETE_POST_TERM",
        title="Post-employment non-compete",
        severity=Severity.HIGH,
        categories=(ClauseCategory.NON_COMPETE,),
        harms=(PartyPosition.EMPLOYEE, PartyPosition.SERVICE_PROVIDER),
        void_regardless=True,
        # Real drafting is verbose: "shall not engage in any activity whatsoever
        # which may in the reasonable opinion of the Company be considered to
        # compete with ..." puts ~95 characters between the verb and "compete".
        # A tight gap here made the single most important rule in the set fail
        # silently on ordinary commercial wording, which reads as a clean contract.
        require_any=(
            _p(r"shall not[^.]{0,200}?(?:engage|work|join|be employed|accept employment|carry on|participate|render|provide|associate|be concerned|be interested|set up|establish)[^.]{0,200}?(?:compet\w+|similar business|similar capacity|similar trade)"),
            _p(r"non[- ]?compet\w*[^.]{0,160}?(?:after|following|post)[^.]{0,60}?(?:termination|resignation|separation|cessation)"),
            _p(r"restrain\w*[^.]{0,120}?from[^.]{0,120}?(?:trade|profession|business|employment)"),
            # The category gate has already established this is a non-compete
            # clause, and require_all establishes that it bites after the contract
            # ends. A bare restraint verb is then enough.
            _p(r"shall not[^.]{0,120}?(?:compete|solicit business|carry on any (?:similar|competing))"),
        ),
        require_all=(
            # "after you leave the Company" is how an offer letter actually says
            # this, and knowing only "leaving" missed it entirely.
            _p(r"(?:after|following|post|subsequent to|upon|once)[^.]{0,60}?(?:termination|terminating|resignation|resign\w*|separation|cessation|expiry|leav(?:e|es|ing)|exit\w*|depart\w*)"),
        ),
        citations=(
            _cite(ACT_CONTRACT, "Section 27",
                  "Every agreement restraining anyone from exercising a lawful "
                  "profession, trade or business is void to that extent. Indian law "
                  "has no 'reasonableness' exception for restraints operating after "
                  "the contract ends."),
        ),
        plain_summary="This stops you working for a competitor after you leave.",
        why_it_matters=(
            "Under Indian law a restraint that bites after the contract ends is void, "
            "not merely hard to enforce. It can still be used to threaten you, and to "
            "withhold a relieving letter, so it is worth negotiating out even though a "
            "court is unlikely to uphold it."
        ),
    ),
    RedFlagRule(
        rule_id="EMPLOYMENT_BOND",
        title="Employment bond or training-cost clawback",
        severity=Severity.HIGH,
        categories=(ClauseCategory.BOND, ClauseCategory.LIQUIDATED_DAMAGES, ClauseCategory.TERM),
        harms=(PartyPosition.EMPLOYEE,),
        require_any=(
            _p(r"(?:minimum|mandatory)[^.]{0,40}?(?:service|employment)[^.]{0,40}?(?:period|term)"),
            _p(r"(?:refund|reimburse|repay)[^.]{0,80}?(?:training|recruitment|onboarding|joining)[^.]{0,40}?(?:cost|expense|bonus)"),
            _p(r"bond[^.]{0,60}?(?:amount|value|of (?:Rs|INR|₹))"),
            _p(r"(?:shall|must) (?:serve|remain in (?:the )?(?:service|employment))[^.]{0,60}?(?:for|a period of)[^.]{0,30}?(?:year|month)"),
        ),
        citations=(
            _cite(ACT_CONTRACT, "Section 27",
                  "A bond restraining the employee from leaving is a restraint of trade; "
                  "courts uphold one only so far as it recovers actual, proven training "
                  "expenditure."),
            _cite(ACT_CONTRACT, "Section 74",
                  "Only reasonable compensation for actual loss is recoverable, whatever "
                  "figure the bond names."),
        ),
        plain_summary="You owe money if you leave before a fixed period.",
        why_it_matters=(
            "The employer must prove what it actually spent on you. A round figure "
            "unconnected to real training cost is usually reduced or refused, but you "
            "may have to litigate to get there."
        ),
    ),
    RedFlagRule(
        rule_id="UNILATERAL_ARBITRATOR",
        title="Arbitrator chosen by one side alone",
        severity=Severity.CRITICAL,
        categories=(ClauseCategory.DISPUTE_RESOLUTION,),
        void_regardless=True,
        require_any=(
            _p(rf"(?:sole )?arbitrator[^.]{{0,100}}?(?:appointed|nominated|selected)[^.]{{0,80}}?(?:by|at the (?:sole )?discretion of)[^.]{{0,60}}?(?:the )?{PARTY}"),
            _p(rf"{PARTY}[^.]{{0,60}}?(?:shall|may|will)[^.]{{0,40}}?(?:appoint|nominate)[^.]{{0,40}}?(?:the )?(?:sole )?arbitrator"),
        ),
        citations=(
            _cite(ACT_ARBITRATION, "Section 12",
                  "A person whose relationship with a party falls in the Seventh Schedule "
                  "is ineligible to act as arbitrator, and an ineligible person cannot "
                  "validly appoint one either."),
        ),
        plain_summary="The other side picks the person who decides your disputes.",
        why_it_matters=(
            "A tribunal appointed unilaterally is open to challenge, so you could win "
            "the challenge and still have lost years. Insist on a jointly appointed "
            "arbitrator or an institutional appointment."
        ),
    ),
    RedFlagRule(
        rule_id="OUSTER_OF_LEGAL_REMEDY",
        title="Right to sue restricted or time-barred early",
        severity=Severity.HIGH,
        # No category gate. The evaluation set has a loan that buries "shall not
        # be entitled to institute any suit" under the heading WAIVER; the words
        # are specific enough to stand on their own wherever they appear.
        categories=(),
        void_regardless=True,
        require_any=(
            _p(r"shall not[^.]{0,60}?(?:be entitled to|have the right to)[^.]{0,40}?(?:institute|file|bring)[^.]{0,30}?(?:any )?(?:suit|proceeding|claim|action)"),
            _p(r"(?:waive|relinquish)[^.]{0,60}?(?:right|remedy)[^.]{0,60}?(?:legal|judicial|court|proceeding)"),
            _p(r"no claim[^.]{0,60}?(?:shall|may) (?:be|lie)[^.]{0,40}?(?:after|unless)[^.]{0,40}?(?:\d{1,3}\s*(?:day|month)s?)"),
        ),
        citations=(
            _cite(ACT_CONTRACT, "Section 28",
                  "An agreement that absolutely restricts a party from enforcing rights "
                  "through the ordinary tribunals, or that shortens the limitation period, "
                  "is void to that extent. Arbitration agreements are the express exception."),
        ),
        plain_summary="This limits your ability to take a dispute to court.",
        why_it_matters=(
            "Contracting out of the courts, or cutting the limitation period down to a "
            "few weeks, is void under s.28 -- but only if you know to say so."
        ),
    ),
    RedFlagRule(
        rule_id="PENALTY_STIPULATION",
        title="Penalty stated as a fixed sum",
        severity=Severity.MEDIUM,
        categories=(ClauseCategory.LIQUIDATED_DAMAGES, ClauseCategory.PAYMENT),
        require_any=(
            _p(r"penalt(?:y|ies)[^.]{0,60}?(?:of|at)[^.]{0,30}?(?:Rs\.?|INR|₹)\s?[\d,]+"),
            _p(r"(?:Rs\.?|INR|₹)\s?[\d,]+[^.]{0,40}?per day[^.]{0,40}?(?:delay|default|breach)"),
            _p(r"liquidated damages[^.]{0,60}?(?:Rs\.?|INR|₹)\s?[\d,]+"),
        ),
        citations=(
            _cite(ACT_CONTRACT, "Section 74",
                  "Where a sum is named as payable on breach, only reasonable "
                  "compensation up to that sum is recoverable -- and actual loss must "
                  "still be shown."),
        ),
        plain_summary="A fixed sum is payable if this is breached.",
        why_it_matters=(
            "The named figure is a ceiling, not an entitlement. Whoever claims it must "
            "still show real loss, so an alarming number is often worth far less than it "
            "appears."
        ),
    ),
    RedFlagRule(
        rule_id="UNCAPPED_INDEMNITY",
        title="Indemnity with no financial ceiling",
        severity=Severity.HIGH,
        categories=(ClauseCategory.INDEMNITY,),
        require_any=(
            _p(r"indemnif\w+[^.]{0,160}?(?:any and all|all|each and every)[^.]{0,80}?(?:claim|loss|damage|liabilit)"),
            _p(r"(?:defend|hold)[^.]{0,30}?harmless[^.]{0,160}?(?:any and all|all)[^.]{0,60}?(?:claim|loss|liabilit)"),
        ),
        exclude_any=(
            _p(r"indemnit\w+[^.]{0,80}?(?:shall not exceed|capped at|limited to)"),
            _p(r"(?:aggregate|total)[^.]{0,40}?liabilit\w+[^.]{0,60}?(?:shall not exceed|capped|limited to)"),
        ),
        plain_summary="You cover the other side's losses without any upper limit.",
        why_it_matters=(
            "An uncapped indemnity can exceed everything the contract is worth to you. "
            "Ask for a cap tied to the fees paid, and for it to exclude indirect losses."
        ),
    ),
    RedFlagRule(
        rule_id="UNILATERAL_TERMINATION",
        title="Only one side can terminate at will",
        severity=Severity.HIGH,
        categories=(ClauseCategory.TERMINATION, ClauseCategory.NOTICE_PERIOD),
        require_any=(
            _p(rf"{PARTY}[^.]{{0,80}}?may[^.]{{0,60}}?terminate[^.]{{0,80}}?(?:without (?:assigning any )?(?:cause|reason|notice)|at its (?:sole )?discretion|forthwith)"),
            _p(r"terminate[^.]{0,60}?(?:without (?:assigning any )?(?:cause|reason)|at any time without notice)"),
        ),
        plain_summary="The other side can end this at any time, without a reason.",
        why_it_matters=(
            "Check whether you have the same right on the same notice. An asymmetric "
            "termination right is the single most common one-sided term, and the easiest "
            "to get made mutual."
        ),
    ),
    RedFlagRule(
        rule_id="UNILATERAL_AMENDMENT",
        title="Terms changeable by one side alone",
        severity=Severity.HIGH,
        # Unilateral variation of the price is the textbook case -- CPA s.2(46)
        # names it -- and it lives in the payment or interest clause, not under
        # a heading called AMENDMENT.
        categories=(
            ClauseCategory.AMENDMENT, ClauseCategory.PAYMENT, ClauseCategory.RENT,
            ClauseCategory.SALARY, ClauseCategory.TERM, ClauseCategory.OTHER,
        ),
        require_any=(
            _p(r"(?:may|reserves the right to)[^.]{0,80}?(?:amend|modify|alter|revise|change|vary)[^.]{0,80}?(?:these terms|this agreement|the policy|any (?:term|provision)|the (?:rate|fee|price|charge|rent|interest)s?(?: of interest)?)[^.]{0,80}?(?:at any time|without (?:prior )?notice|at its (?:sole )?discretion)"),
            _p(r"(?:at its sole discretion)[^.]{0,60}?(?:amend|modify|revise|change|vary)[^.]{0,60}?(?:terms|agreement|rate|fee|price|interest)"),
        ),
        plain_summary="The other side can rewrite the deal after you have signed it.",
        why_it_matters=(
            "Whatever you agreed today can be replaced tomorrow. At minimum require "
            "written notice and a right to exit without penalty if you reject a change."
        ),
    ),
    RedFlagRule(
        rule_id="AUTO_RENEWAL",
        title="Automatic renewal with a short opt-out window",
        severity=Severity.MEDIUM,
        categories=(ClauseCategory.RENEWAL, ClauseCategory.TERM),
        require_any=(
            _p(r"auto(?:matic)?(?:ally)?[^.]{0,30}?renew\w*"),
            _p(r"renew\w*[^.]{0,60}?unless[^.]{0,80}?notice"),
            _p(r"deemed to (?:be )?(?:renewed|extended)"),
        ),
        plain_summary="This renews itself unless you cancel in time.",
        why_it_matters=(
            "Diarise the cancellation deadline the day you sign. Missing it by a day "
            "commits you to another full term."
        ),
    ),
    RedFlagRule(
        rule_id="BROAD_IP_ASSIGNMENT",
        title="Assignment of IP beyond the work itself",
        severity=Severity.HIGH,
        categories=(ClauseCategory.IP_ASSIGNMENT,),
        harms=(PartyPosition.EMPLOYEE, PartyPosition.SERVICE_PROVIDER),
        require_any=(
            _p(r"assign\w*[^.]{0,120}?(?:all|any and all)[^.]{0,80}?(?:intellectual property|invention|work|copyright)[^.]{0,120}?(?:whether or not|regardless of whether|created (?:before|prior)|outside)"),
            _p(r"(?:pre[- ]?existing|background|prior)[^.]{0,40}?(?:intellectual property|IP|invention)[^.]{0,80}?(?:shall (?:vest|belong)|assign\w*)"),
            _p(r"\b(?:all|any)\b[^.]{0,60}?(?:invention|creation|work)[^.]{0,80}?(?:during (?:and after )?the (?:term|employment))[^.]{0,120}?(?:whether or not[^.]{0,60}?(?:related|connected|during working hours))"),
        ),
        plain_summary="This may take ownership of work you did on your own time.",
        why_it_matters=(
            "Narrow it to work actually made for this engagement, and attach a schedule "
            "listing anything you built beforehand that you want to keep."
        ),
    ),
    RedFlagRule(
        rule_id="PERPETUAL_CONFIDENTIALITY",
        title="Confidentiality lasting forever",
        severity=Severity.MEDIUM,
        categories=(ClauseCategory.CONFIDENTIALITY,),
        harms=(PartyPosition.RECEIVING_PARTY, PartyPosition.EMPLOYEE, PartyPosition.SERVICE_PROVIDER),
        require_any=(
            _p(r"confidential\w*[^.]{0,120}?(?:in perpetuity|perpetual|for all time|indefinitely|shall survive[^.]{0,40}?(?:indefinitely|perpetual))"),
            _p(r"(?:obligations?[^.]{0,40}?confidential\w*|confidential\w*[^.]{0,40}?obligations?)[^.]{0,80}?survive[^.]{0,60}?(?:indefinitely|in perpetuity|without limit)"),
        ),
        plain_summary="Your confidentiality duty never ends.",
        why_it_matters=(
            "Perpetual duties are hard to comply with years later when you no longer "
            "remember what was covered. Three to five years is the usual commercial norm, "
            "with genuine trade secrets carved out separately."
        ),
    ),
    RedFlagRule(
        rule_id="FOREIGN_EXCLUSIVE_JURISDICTION",
        title="Disputes sent to a foreign court",
        severity=Severity.MEDIUM,
        categories=(ClauseCategory.GOVERNING_LAW, ClauseCategory.DISPUTE_RESOLUTION),
        require_any=(
            _p(r"(?:exclusive )?jurisdiction[^.]{0,80}?courts? (?:of|at|in)\s+(?:Singapore|London|New York|Delaware|California|Dubai|Hong Kong|England|the United States|the State of)"),
            _p(r"governed by[^.]{0,60}?laws? of[^.]{0,40}?(?:Singapore|England|New York|Delaware|California|the State of|the United States)"),
        ),
        plain_summary="Any dispute has to be fought in another country.",
        why_it_matters=(
            "The cost of enforcing your rights abroad usually exceeds what an individual "
            "or small business can justify, which makes the clause a practical bar to any "
            "claim, whatever the contract says you are owed."
        ),
    ),
    RedFlagRule(
        rule_id="EXCESSIVE_SECURITY_DEPOSIT",
        title="Large or non-refundable security deposit",
        severity=Severity.MEDIUM,
        # No category gate: deposit terms live in a schedule as often as in a
        # clause of their own, and the wording below names its own subject.
        categories=(),
        harms=(PartyPosition.TENANT,),
        require_any=(
            _p(r"security deposit[^.]{0,120}?(?:non[- ]?refundable|shall (?:stand )?forfeit\w*|shall not be refunded)"),
            _p(r"(?:deposit|advance)[^.]{0,60}?equivalent to[^.]{0,40}?(?:six|seven|eight|nine|ten|eleven|twelve|\b(?:[6-9]|1[0-2])\b)\s*months?"),
        ),
        citations=(
            _cite(ACT_TRANSFER_OF_PROPERTY, "Section 108",
                  "Sets the default rights and liabilities of lessor and lessee, which "
                  "apply wherever the lease itself is silent or unenforceable."),
        ),
        plain_summary="The deposit is unusually large, or you may not get it back.",
        why_it_matters=(
            "Fix the refund timeline in days, list exactly what may be deducted, and "
            "require an itemised account for any deduction."
        ),
    ),
    RedFlagRule(
        rule_id="LOCK_IN_WITHOUT_EXIT",
        title="Lock-in period with no way out",
        severity=Severity.MEDIUM,
        categories=(ClauseCategory.LOCK_IN, ClauseCategory.TERM, ClauseCategory.TERMINATION),
        harms=(PartyPosition.TENANT, PartyPosition.CLIENT, PartyPosition.BORROWER),
        require_any=(
            _p(r"lock[- ]?in[^.]{0,100}?(?:period|term)"),
            _p(r"shall not[^.]{0,60}?(?:vacate|terminate|exit)[^.]{0,80}?(?:before|prior to)[^.]{0,60}?(?:month|year)"),
        ),
        plain_summary="You are committed for a minimum period whatever happens.",
        why_it_matters=(
            "Ask for an exit on notice with a defined payment, and for the lock-in to "
            "fall away if the other side is in breach."
        ),
    ),
    RedFlagRule(
        rule_id="ONE_SIDED_ASSIGNMENT",
        title="Only one side may transfer the contract",
        severity=Severity.LOW,
        categories=(ClauseCategory.ASSIGNMENT,),
        require_any=(
            _p(r"(?:shall not|may not)[^.]{0,60}?assign[^.]{0,120}?without[^.]{0,60}?(?:prior )?(?:written )?consent"),
        ),
        require_all=(
            # Any free assignment right anywhere in the clause establishes the
            # asymmetry. Naming the counterparty here is what made this rule miss
            # "The Provider may assign this Agreement ... without restriction".
            _p(r"(?:may|shall be entitled to|is entitled to)[^.]{0,60}?assign"),
        ),
        plain_summary="They can hand this contract to someone else; you cannot.",
        why_it_matters=(
            "You could end up dealing with a party you never chose. Ask for the same "
            "consent requirement to apply both ways, or at least for notice."
        ),
    ),
    RedFlagRule(
        rule_id="DATA_SHARING_WITHOUT_CONSENT",
        title="Personal data shared with third parties",
        severity=Severity.MEDIUM,
        categories=(ClauseCategory.DATA_PROTECTION, ClauseCategory.CONFIDENTIALITY),
        require_any=(
            _p(r"(?:personal (?:data|information)|your data)[^.]{0,120}?(?:shar\w*|disclos\w*|transfer\w*)[^.]{0,80}?(?:third part|affiliate|partner|vendor)"),
            _p(r"consent[^.]{0,60}?(?:to the)?[^.]{0,60}?(?:processing|sharing)[^.]{0,80}?(?:personal (?:data|information))"),
        ),
        citations=(
            _cite(ACT_DPDP, "Section 6",
                  "Consent must be free, specific, informed, unconditional and "
                  "unambiguous, and limited to the data necessary for the stated purpose."),
            _cite(ACT_DPDP, "Section 8",
                  "The Data Fiduciary stays accountable for processing done by any "
                  "processor it engages."),
        ),
        plain_summary="Your personal data can be passed to other companies.",
        why_it_matters=(
            "Blanket consent buried in a contract does not meet the DPDP standard. The "
            "purposes must be specific, and you must be able to withdraw consent."
        ),
    ),
    RedFlagRule(
        rule_id="UNFAIR_TERM_WAIVER",
        title="Waiver of statutory or consumer rights",
        severity=Severity.HIGH,
        categories=(),
        require_any=(
            _p(r"waive[^.]{0,100}?(?:all|any)[^.]{0,60}?(?:statutory|legal|consumer)[^.]{0,40}?rights?"),
            _p(r"(?:shall have no|hereby (?:waives?|forgoes?))[^.]{0,60}?(?:remedy|recourse|claim)[^.]{0,60}?(?:under (?:any )?law|statutory)"),
        ),
        citations=(
            _cite(ACT_CONSUMER, "Section 2",
                  "Defines an 'unfair contract' -- including terms imposing excessive "
                  "security, disproportionate penalties, unilateral termination and "
                  "assignment prejudicing the other party."),
        ),
        void_regardless=True,
        plain_summary="This asks you to give up rights the law gives you.",
        why_it_matters=(
            "Statutory rights generally cannot be contracted away, so the clause is "
            "likely ineffective -- but it signals how the rest of the contract is drafted."
        ),
    ),
)


def _rule_applies_to(rule: RedFlagRule, clause: Clause) -> bool:
    return not rule.categories or clause.category in rule.categories


def _severity_for(
    rule: RedFlagRule, position: PartyPosition
) -> Optional[Severity]:
    """Severity of this rule for the reviewing party, or None to not report it."""
    if position == PartyPosition.UNKNOWN or not rule.harms:
        return rule.severity
    if position in rule.harms:
        # The weaker side has less ability to negotiate the term away, so the
        # same clause carries more practical risk for them.
        return _shift(rule.severity, 1) if position in WEAKER_POSITIONS else rule.severity
    if rule.void_regardless:
        # Favoured by it, but it would not survive a challenge -- worth knowing,
        # since planning around an unenforceable protection is its own risk.
        return _shift(rule.severity, -1)
    return Severity.INFO


def evaluate_clause(
    clause: Clause,
    position: PartyPosition = PartyPosition.UNKNOWN,
    rules: Sequence[RedFlagRule] = RULES,
) -> List[RedFlagFinding]:
    """Run every applicable rule over one clause."""
    findings: List[RedFlagFinding] = []
    # Match the body, not the heading. "3. SECURITY DEPOSIT" otherwise supplies
    # the first hit for a deposit rule, and the finding quotes the title of the
    # clause instead of the term that makes it a problem.
    body_start = max(clause.body_offset - clause.start_offset, 0)
    text = clause.text[body_start:]

    for rule in rules:
        if not _rule_applies_to(rule, clause):
            continue
        # The longest match is the most specific one. Without this the bond rule
        # quotes the clause heading ("MINIMUM SERVICE PERIOD") rather than the
        # obligation it names, because the heading sits earlier in the text.
        matches = [m for p in rule.require_any for m in [p.search(text)] if m]
        if not matches:
            continue
        hit = max(matches, key=lambda m: len(m.group(0)))
        if any(not p.search(text) for p in rule.require_all):
            continue
        if any(p.search(text) for p in rule.exclude_any):
            continue

        severity = _severity_for(rule, position)
        if severity is None:
            continue

        quote = " ".join(hit.group(0).split())
        findings.append(
            RedFlagFinding(
                rule_id=rule.rule_id,
                title=rule.title,
                severity=severity,
                clause_index=clause.index,
                clause_number=clause.number,
                matched_quote=quote,
                match_start=clause.body_offset + hit.start(),
                match_end=clause.body_offset + hit.end(),
                harms=list(rule.harms),
                citations=list(rule.citations),
                plain_summary=rule.plain_summary,
                why_it_matters=rule.why_it_matters,
                detector="rule",
            )
        )
    return findings


def evaluate_clauses(
    clauses: Sequence[Clause],
    position: PartyPosition = PartyPosition.UNKNOWN,
    rules: Sequence[RedFlagRule] = RULES,
) -> List[RedFlagFinding]:
    """Run the ruleset across a whole contract, worst findings first."""
    findings: List[RedFlagFinding] = []
    for clause in clauses:
        findings.extend(evaluate_clause(clause, position, rules))
    findings.sort(
        key=lambda f: (-SEVERITY_ORDER[f.severity], f.clause_index or 0, f.rule_id)
    )
    return findings


def verify_quotes(findings: Sequence[RedFlagFinding], document_text: str) -> List[str]:
    """Confirm every finding's quote really is at the offsets it claims.

    Rule findings are quoted out of the document by construction, so a failure
    here means an offset bug rather than a hallucination. Running it now means
    the check is already in place, and already tested, when Phase 3 starts
    admitting model-proposed findings that genuinely can invent a quote.
    """
    problems = []
    for finding in findings:
        span = " ".join(document_text[finding.match_start : finding.match_end].split())
        if span != finding.matched_quote:
            problems.append(
                f"{finding.rule_id} @ [{finding.match_start}:{finding.match_end}] "
                f"quotes {finding.matched_quote[:60]!r} but the document reads {span[:60]!r}"
            )
    return problems
