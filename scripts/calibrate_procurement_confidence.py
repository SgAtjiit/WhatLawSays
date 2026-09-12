"""Does the procurement confidence score mean anything?

Not calibration in the strict sense -- "when it says 0.7 it is right 70% of the
time" needs far more labelled reviews than sixteen events on which the checks are
near-perfect. That remains unfitted, and the score is still an estimate.

What this measures is **reliability**: each labelled event is reviewed under a
series of deliberate degradations, and the score has to move the right way by the
right amount. A number that reports a crippled review as confidently as a healthy
one is not measuring anything, and the failure is silent -- it still looks like a
number.

Observed quality is the F1 of the deterministic outcomes against the answer key
under each condition, so "quality" here means what the review actually got right,
not how it felt about itself.

`tests/test_procurement_calibration.py` asserts the ordering and the caps, so an
estimator change that makes a degraded review over-confident fails the build.
"""

import argparse
import copy
import json
import pathlib
import sys
from typing import Dict, List, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from scripts.evaluate_procurement_review import FIXTURES, POLICY, SCORED, key  # noqa: E402
from src.core.procurement_confidence import (  # noqa: E402
    DEGRADED_LLM_CAP,
    DEGRADED_RERANKER_CAP,
    NO_MSME_STATUS_CAP,
    STATUTE_ONLY_CAP,
    UNDETERMINED_HEAVY_CAP,
    UNRATIFIED_POLICY_CAP,
    UNVERIFIED_EVIDENCE_CAP,
    estimate_procurement_confidence,
)
from src.core.procurement_evidence import VerificationContext, verify_findings  # noqa: E402
from src.core.procurement_rules import POLICY_TEMPLATES, evaluate_procurement  # noqa: E402
from src.schemas.procurement import (  # noqa: E402
    EMPTY_RULE_SET,
    MsmeStatus,
    PolicyRuleSet,
    ProcurementEvent,
    ProcurementSide,
    RuleStatus,
)

CONDITIONS = [
    "full",
    "reranker_down",
    "llm_down",
    "msme_unknown",
    "partial_event",
    "unratified_policy",
    "no_policy",
    "unverifiable_evidence",
]

# Conditions the caps are asserted against, and the ceiling each must respect.
CAPS: Dict[str, float] = {
    "llm_down": DEGRADED_LLM_CAP,
    "reranker_down": DEGRADED_RERANKER_CAP,
    "unverifiable_evidence": UNVERIFIED_EVIDENCE_CAP,
    "unratified_policy": UNRATIFIED_POLICY_CAP,
    "msme_unknown": NO_MSME_STATUS_CAP,
    "partial_event": UNDETERMINED_HEAVY_CAP,
    "no_policy": STATUTE_ONLY_CAP,
}

MAX_CALIBRATION_ERROR = 0.35


def _unratified(policy: PolicyRuleSet) -> PolicyRuleSet:
    degraded = policy.model_copy(deep=True)
    for rule in degraded.rules:
        rule.status = RuleStatus.DRAFT
    return degraded


def _apply(condition: str, payload: dict) -> Tuple[dict, dict]:
    """Return the degraded event payload and the estimator overrides it implies."""
    payload = copy.deepcopy(payload)
    overrides: Dict[str, object] = {}

    if condition == "msme_unknown":
        for bid in payload.get("bids", []):
            bid["vendor"]["msme_status"] = "UNKNOWN"
            bid["vendor"].pop("udyam_number", None)
    elif condition == "partial_event":
        # The caller stops declaring what it supplied. Nothing is removed -- the
        # data is still there -- but the system may no longer treat an empty
        # collection as a real negative, which is exactly the point.
        payload["provided_collections"] = ["bids"]
    elif condition == "llm_down":
        overrides["llm_available"] = False
    elif condition == "reranker_down":
        overrides["reranker_available"] = False
    return payload, overrides


def _score_one(name: str, condition: str, labels: dict) -> Tuple[float, float]:
    payload = json.loads((FIXTURES / "events" / f"{name}.json").read_text())
    payload, overrides = _apply(condition, payload)
    event = ProcurementEvent(**payload)

    policy = POLICY
    include_drafts = False
    if condition == "unratified_policy":
        policy = _unratified(POLICY)
        include_drafts = True
    elif condition == "no_policy":
        policy = EMPTY_RULE_SET.model_copy(deep=True)

    evaluation = evaluate_procurement(
        event, policy, side=ProcurementSide.BUYER, include_draft_rules=include_drafts
    )
    problems = verify_findings(evaluation.outcomes, VerificationContext(event=event))
    unverified: List[str] = sorted(problems)
    if condition == "unverifiable_evidence" and evaluation.outcomes:
        # Corrupt one finding's evidence the way a normalisation bug would.
        unverified = [f"{evaluation.outcomes[0].check_id}|{evaluation.outcomes[0].subject_ref or ''}"]

    vendor = event.awarded_vendor
    report = estimate_procurement_confidence(
        outcomes=evaluation.outcomes,
        unverified_keys=unverified,
        side=ProcurementSide.BUYER.value,
        category=event.category,
        msme_status=vendor.msme_status if vendor else MsmeStatus.UNKNOWN,
        ratified_rule_count=len(policy.enforceable_rules()),
        total_rule_count=len(policy.rules),
        covered_check_kinds=len({r.kind for r in policy.rules}),
        available_check_kinds=len(POLICY_TEMPLATES),
        **overrides,
    )

    expected = {key(*e) for e in labels[name]["expected"]}
    spoken_for = {c for c, _, _ in expected}
    actual = {
        key(o.check_id, o.subject_ref, o.status.value)
        for o in evaluation.outcomes
        if o.status in SCORED and o.check_id in spoken_for
    }
    tp = len(expected & actual)
    fp = len(actual - expected)
    fn = len(expected - actual)
    if not expected and not actual:
        observed = 1.0
    else:
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        observed = (
            2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        )
    return report.score, observed


def calibrate(verbose: bool = False) -> Dict[str, Dict[str, float]]:
    labels = json.loads((FIXTURES / "labels.json").read_text())
    table: Dict[str, Dict[str, float]] = {}

    for condition in CONDITIONS:
        predicted: List[float] = []
        observed: List[float] = []
        for name in sorted(labels):
            p, o = _score_one(name, condition, labels)
            predicted.append(p)
            observed.append(o)
            if verbose:
                print(f"  {condition:22s} {name:44s} predicted {p:.3f}  observed {o:.3f}")
        table[condition] = {
            "predicted": sum(predicted) / len(predicted),
            "observed": sum(observed) / len(observed),
            "max_predicted": max(predicted),
        }
    return table


def expected_calibration_error(table: Dict[str, Dict[str, float]]) -> float:
    return sum(abs(v["predicted"] - v["observed"]) for v in table.values()) / len(table)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    table = calibrate(args.verbose)

    print()
    print(f"{'condition':24s} {'predicted':>10s} {'observed':>10s}")
    for condition in CONDITIONS:
        row = table[condition]
        capped = "  capped" if condition in CAPS else ""
        print(f"{condition:24s} {row['predicted']:10.3f} {row['observed']:10.3f}{capped}")

    error = expected_calibration_error(table)
    print(f"\nmean |predicted - observed| across conditions: {error:.3f}")
    if error > MAX_CALIBRATION_ERROR:
        print(f"[NOTE] above {MAX_CALIBRATION_ERROR}. Read as a diagnostic on sixteen "
              "events, not as a fitted calibration.")

    problems = []
    full = table["full"]["predicted"]
    for condition, row in table.items():
        if condition == "full":
            continue
        if row["predicted"] > full + 1e-9:
            problems.append(f"{condition} scores above an undegraded review")
        ceiling = CAPS.get(condition)
        if ceiling is not None and row["max_predicted"] > ceiling + 1e-9:
            problems.append(
                f"{condition} reached {row['max_predicted']:.3f}, above its {ceiling} cap"
            )

    if problems:
        print("\n[FAIL] " + "\n       ".join(problems))
        raise SystemExit(1)
    print("\n[PASS] every degradation moves the score the right way.")


if __name__ == "__main__":
    main()
