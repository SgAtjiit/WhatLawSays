"""Decide how much analysis each clause is worth.

A 20-page contract runs to 60-120 clauses. Sending every clause down the
expensive path -- statutory retrieval, a plain-language pass, a model red-flag
pass -- would cost hundreds of LLM calls per review. Measured against this
project's Groq key, 40 concurrent structured-output calls rate-limit 45% of the
time, so that is not merely expensive but unreliable.

Triage is deterministic and runs before any model call. **Rules decide the tier;
the model never decides its own budget.** The tier is also never lowered by a
model, and no tier suppresses a deterministic finding: a COLD clause carrying a
rule finding still reports that finding in full, it simply gets no model prose.

The caps are what make cost a function of the caps rather than of the contract.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

from src.schemas.contract import (
    SEVERITY_ORDER,
    WEAKER_POSITIONS,
    Clause,
    ClauseCategory,
    PartyPosition,
    RedFlagFinding,
    Severity,
)

HOT = "HOT"
WARM = "WARM"
COLD = "COLD"

# Categories where the dangerous terms live, and where the statute has something
# specific to say. These earn retrieval and a model red-flag pass.
HOT_CATEGORIES = frozenset({
    ClauseCategory.NON_COMPETE,
    ClauseCategory.NON_SOLICIT,
    ClauseCategory.INDEMNITY,
    ClauseCategory.LIABILITY,
    ClauseCategory.LIQUIDATED_DAMAGES,
    ClauseCategory.TERMINATION,
    ClauseCategory.DISPUTE_RESOLUTION,
    ClauseCategory.IP_ASSIGNMENT,
    ClauseCategory.BOND,
    ClauseCategory.LOCK_IN,
    ClauseCategory.SECURITY_DEPOSIT,
    ClauseCategory.DATA_PROTECTION,
    ClauseCategory.ASSIGNMENT,
    ClauseCategory.AMENDMENT,
})

# Ordinary commercial terms. Worth explaining in plain words, but they rarely
# turn on a statutory provision, so they skip retrieval.
WARM_CATEGORIES = frozenset({
    ClauseCategory.PAYMENT,
    ClauseCategory.SALARY,
    ClauseCategory.RENT,
    ClauseCategory.TERM,
    ClauseCategory.NOTICE_PERIOD,
    ClauseCategory.CONFIDENTIALITY,
    ClauseCategory.RENEWAL,
    ClauseCategory.WARRANTY,
    ClauseCategory.FORCE_MAJEURE,
    ClauseCategory.GOVERNING_LAW,
    ClauseCategory.MAINTENANCE,
    ClauseCategory.PROBATION,
    ClauseCategory.WORKING_HOURS,
    ClauseCategory.LEAVE,
})

HOT_CAP = 24
WARM_CAP = 60

# Below this, a clause is a heading, a signature line or a cross-reference stub.
# Applied to WARM only. Brevity does not mean unimportance in a contract -- "The
# Employee shall not compete for two years after leaving." is 56 characters and
# void under Contract Act s.27 -- so a statute-bearing clause is never demoted
# for being short.
MIN_ANALYSABLE_CHARS = 120


@dataclass
class TriageResult:
    tiers: Dict[int, str] = field(default_factory=dict)
    basis: Dict[int, List[str]] = field(default_factory=dict)
    hot: List[int] = field(default_factory=list)
    warm: List[int] = field(default_factory=list)
    cold: List[int] = field(default_factory=list)

    def to_payload(self) -> Dict[str, object]:
        return {
            "hot": len(self.hot),
            "warm": len(self.warm),
            "cold": len(self.cold),
            "hot_cap": HOT_CAP,
            "warm_cap": WARM_CAP,
        }


def _worst_severity(findings: Sequence[RedFlagFinding]) -> int:
    return max((SEVERITY_ORDER[f.severity] for f in findings), default=-1)


def triage_clauses(
    clauses: Sequence[Clause],
    rule_findings: Sequence[RedFlagFinding] = (),
    position: PartyPosition = PartyPosition.UNKNOWN,
    hot_cap: int = HOT_CAP,
    warm_cap: int = WARM_CAP,
) -> TriageResult:
    """Assign every clause a tier, with an auditable reason for each."""
    by_clause: Dict[int, List[RedFlagFinding]] = {}
    for finding in rule_findings:
        if finding.clause_index is not None:
            by_clause.setdefault(finding.clause_index, []).append(finding)

    weaker = position in WEAKER_POSITIONS
    result = TriageResult()
    candidates: List[Tuple[int, int, str, List[str]]] = []

    for clause in clauses:
        found = by_clause.get(clause.index, [])
        worst = _worst_severity(found)
        reasons: List[str] = []
        tier = COLD

        if worst >= SEVERITY_ORDER[Severity.HIGH]:
            tier = HOT
            reasons.append("carries a HIGH or CRITICAL rule finding")
        elif clause.category in HOT_CATEGORIES:
            tier = HOT
            reasons.append(f"category {clause.category.value} is statute-bearing")
        elif weaker and found and clause.category in WARM_CATEGORIES:
            # The weaker side's ordinary clause is where asymmetry hides, and
            # _severity_for has already escalated it a step for exactly that reason.
            tier = HOT
            reasons.append(f"ordinary clause carrying a finding, reviewed as {position.value}")
        elif found:
            tier = WARM
            reasons.append("carries a rule finding")
        elif clause.category in WARM_CATEGORIES:
            tier = WARM
            reasons.append(f"category {clause.category.value} is an ordinary commercial term")
        else:
            reasons.append(f"category {clause.category.value} with no rule finding")

        if tier == WARM and len(clause.text) < MIN_ANALYSABLE_CHARS and not found:
            tier = COLD
            reasons.append(f"under {MIN_ANALYSABLE_CHARS} characters")

        candidates.append((clause.index, worst, tier, reasons))

    # Apply the caps worst-first, so what survives is what matters most.
    def demote(tier_name: str, cap: int, next_tier: str) -> None:
        members = [c for c in candidates if c[2] == tier_name]
        if len(members) <= cap:
            return
        members.sort(key=lambda c: (-c[1], c[0]))
        for index, _, _, reasons in members[cap:]:
            position_in_list = next(i for i, c in enumerate(candidates) if c[0] == index)
            severity, _, existing = candidates[position_in_list][1], None, candidates[position_in_list][3]
            existing.append(f"demoted to {next_tier}: over the {tier_name} cap of {cap}")
            candidates[position_in_list] = (index, severity, next_tier, existing)

    demote(HOT, hot_cap, WARM)
    demote(WARM, warm_cap, COLD)

    for index, _, tier, reasons in candidates:
        result.tiers[index] = tier
        result.basis[index] = reasons
        {HOT: result.hot, WARM: result.warm, COLD: result.cold}[tier].append(index)

    for bucket in (result.hot, result.warm, result.cold):
        bucket.sort()
    return result
