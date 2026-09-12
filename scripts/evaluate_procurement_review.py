"""Score the deterministic procurement spine against the labelled set.

The sibling of `evaluate_contract_review.py`, and scored the same way: the
deterministic spine only. Model prose is not held to an answer key, because it
is not reproducible enough to have one; its quality is checked by evidence
verification instead.

The match key is `(check_id, subject_ref, status)`. Two deliberate choices there:

* **subject_ref is in the key.** The right check on the wrong vendor or the wrong
  line item is a normalisation bug wearing a correct answer's clothes -- the same
  reasoning that puts clause_number in the contract harness's key.
* **status is in the key.** Reporting BREACH where the answer key says
  UNDETERMINED is not a near miss, it is the specific failure this whole feature
  exists to prevent. It counts as a false positive *and* a false negative, which
  is what it deserves.
"""

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.core.procurement_evidence import VerificationContext, verify_findings  # noqa: E402
from src.core.procurement_rules import evaluate_procurement  # noqa: E402
from src.schemas.procurement import (  # noqa: E402
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

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "procurement_eval"

MIN_PRECISION = 0.90
MIN_RECALL = 0.90
MAX_CLEAN_EVENT_FINDINGS = 0
MAX_EVIDENCE_FAILURES = 0
# Zero tolerance, each for its own reason. Selling UNKNOWN as either FALSE or
# TRUE is the failure mode this feature is built against; selling a statistical
# pattern as a breach names real companies as having done something they may not
# have done.
MAX_UNDETERMINED_SOLD_AS_PASS = 0
MAX_UNDETERMINED_SOLD_AS_BREACH = 0
MAX_INDICATOR_SOLD_AS_BREACH = 0

# The policy every labelled event is scored against. Fixed here rather than per
# event, so a check that stops firing cannot be hidden by a rule set that quietly
# stopped enabling it.
POLICY = PolicyRuleSet(
    policy_id="EVAL", org_label="Evaluation", status=PolicySetStatus.ACTIVE,
    rules=[
        PolicyRule(rule_id=f"R{i}", kind=kind, params=params,
                   status=RuleStatus.RATIFIED, origin=RuleOrigin.HUMAN)
        for i, (kind, params) in enumerate([
            (PolicyCheckKind.MIN_QUOTES_BY_VALUE, {"above_value": 500000, "min_quotes": 3}),
            (PolicyCheckKind.APPROVAL_AUTHORITY, {"above_value": 500000, "required_role": "CFO"}),
            (PolicyCheckKind.APPROVAL_BEFORE_COMMITMENT, {}),
            (PolicyCheckKind.APPROVED_VENDOR_REQUIRED, {}),
            (PolicyCheckKind.LOWEST_RESPONSIVE_AWARD, {}),
            (PolicyCheckKind.PO_EXCEEDS_AWARDED_VALUE, {"tolerance_pct": 0}),
            (PolicyCheckKind.SPLIT_PO_AVOIDANCE, {"window_days": 30, "threshold": 500000}),
            (PolicyCheckKind.PAYMENT_TERMS_CAP, {"max_days": 60}),
            (PolicyCheckKind.SINGLE_SOURCE_JUSTIFICATION, {}),
            (PolicyCheckKind.LATE_BID_REJECTION, {}),
            (PolicyCheckKind.MANDATORY_BID_WINDOW, {"min_days": 7}),
            (PolicyCheckKind.BUDGET_AVAILABILITY, {}),
            (PolicyCheckKind.SCOPE_DRIFT, {}),
            (PolicyCheckKind.RATE_CONTRACT_ADHERENCE, {"tolerance_pct": 0}),
        ])
    ],
)

# Statuses the answer key speaks about. PASS and NOT_EVALUATED are outcomes the
# key does not assert, so they are neither scored nor penalised.
SCORED = {
    CheckStatus.BREACH, CheckStatus.INDICATOR,
    CheckStatus.UNDETERMINED, CheckStatus.NOT_APPLICABLE,
}


def key(check_id, subject_ref, status):
    return (check_id, subject_ref or None, status)


def run_one(name, event_payload):
    event = ProcurementEvent(**event_payload)
    evaluation = evaluate_procurement(event, POLICY, side=ProcurementSide.BUYER)
    problems = verify_findings(evaluation.outcomes, VerificationContext(event=event))
    return event, evaluation, problems


def evaluate(verbose=False):
    labels = json.loads((FIXTURES / "labels.json").read_text())
    tp = fp = fn = 0
    clean_findings = 0
    evidence_failures = 0
    sold_as_pass = sold_as_breach = indicator_as_breach = 0
    per_check = {}
    rows = []

    for name in sorted(labels):
        meta = labels[name]
        payload = json.loads((FIXTURES / "events" / f"{name}.json").read_text())
        event, evaluation, problems = run_one(name, payload)
        evidence_failures += len(problems)

        expected = {key(*e) for e in meta["expected"]}
        actual_all = {
            key(o.check_id, o.subject_ref, o.status.value)
            for o in evaluation.outcomes if o.status in SCORED
        }
        # Only score check_ids the key speaks about for this event. The key does
        # not claim to enumerate every NOT_APPLICABLE the engine will emit.
        spoken_for = {c for c, _, _ in expected}
        actual = {k for k in actual_all if k[0] in spoken_for}

        hits = expected & actual
        misses = expected - actual
        spurious = actual - expected

        # The zero-tolerance counters, measured against what the key expected.
        by_check = {c: (s, st) for c, s, st in expected}
        for check_id, subject, status in actual:
            if check_id in by_check and by_check[check_id][1] != status:
                wanted = by_check[check_id][1]
                if wanted == "UNDETERMINED" and status == "PASS":
                    sold_as_pass += 1
                if wanted == "UNDETERMINED" and status == "BREACH":
                    sold_as_breach += 1
                if wanted == "INDICATOR" and status == "BREACH":
                    indicator_as_breach += 1
        for check_id, subject, status in expected:
            if status == "UNDETERMINED":
                got = {s for c, _, s in actual if c == check_id}
                if "PASS" in got:
                    sold_as_pass += 1
                if "BREACH" in got:
                    sold_as_breach += 1

        if meta["clean"]:
            breaches = [
                o for o in evaluation.outcomes
                if o.status in {CheckStatus.BREACH, CheckStatus.INDICATOR}
            ]
            clean_findings += len(breaches)
            if verbose and breaches:
                for b in breaches:
                    print(f"    [FP on clean event] {b.check_id} -- {b.plain_summary}")

        tp += len(hits)
        fn += len(misses)
        fp += len(spurious)
        for check_id, _, _ in expected:
            counts = per_check.setdefault(check_id, [0, 0, 0])
            counts[0] += 1
        for check_id, _, _ in hits:
            per_check[check_id][1] += 1

        rows.append((name, len(hits), len(misses), len(spurious), len(problems)))
        if verbose:
            flag = "clean" if meta["clean"] else f"{len(expected)} expected"
            print(f"  {name:44s} {flag:14s} tp={len(hits)} fn={len(misses)} fp={len(spurious)}")
            for m in sorted(misses):
                print(f"      MISSED  {m}")
            for s in sorted(spurious):
                print(f"      EXTRA   {s}")

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    never_fired = sorted(c for c, v in per_check.items() if v[1] == 0)

    print()
    print(f"precision {precision:.3f}  recall {recall:.3f}  f1 {f1:.3f}   "
          f"({tp} TP / {fp} FP / {fn} FN over {len(labels)} events)")
    print(f"findings on clean events: {clean_findings}   "
          f"evidence verification failures: {evidence_failures}")
    print(f"UNDETERMINED sold as PASS: {sold_as_pass}   "
          f"as BREACH: {sold_as_breach}   INDICATOR sold as BREACH: {indicator_as_breach}")
    if never_fired:
        print(f"labelled checks that never fired: {', '.join(never_fired)}")

    return {
        "precision": precision, "recall": recall, "f1": f1,
        "tp": tp, "fp": fp, "fn": fn,
        "clean_findings": clean_findings,
        "evidence_failures": evidence_failures,
        "undetermined_sold_as_pass": sold_as_pass,
        "undetermined_sold_as_breach": sold_as_breach,
        "indicator_sold_as_breach": indicator_as_breach,
        "never_fired": never_fired,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    result = evaluate(args.verbose)

    failures = []
    if result["precision"] < MIN_PRECISION:
        failures.append(f"precision {result['precision']:.3f} < {MIN_PRECISION}")
    if result["recall"] < MIN_RECALL:
        failures.append(f"recall {result['recall']:.3f} < {MIN_RECALL}")
    if result["clean_findings"] > MAX_CLEAN_EVENT_FINDINGS:
        failures.append(f"{result['clean_findings']} finding(s) on deliberately clean events")
    if result["evidence_failures"] > MAX_EVIDENCE_FAILURES:
        failures.append(f"{result['evidence_failures']} evidence verification failure(s)")
    if result["undetermined_sold_as_pass"] > MAX_UNDETERMINED_SOLD_AS_PASS:
        failures.append("a check that could not be performed was reported as passing")
    if result["undetermined_sold_as_breach"] > MAX_UNDETERMINED_SOLD_AS_BREACH:
        failures.append("a check that could not be performed was reported as a breach")
    if result["indicator_sold_as_breach"] > MAX_INDICATOR_SOLD_AS_BREACH:
        failures.append("a statistical indicator was reported as a breach")
    if result["never_fired"]:
        failures.append(f"labelled checks never fired: {', '.join(result['never_fired'])}")

    if failures:
        print("\n[FAIL] " + "\n       ".join(failures))
        raise SystemExit(1)
    print("\n[PASS] every floor met.")


if __name__ == "__main__":
    main()
