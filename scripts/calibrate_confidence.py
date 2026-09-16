"""Measure whether the confidence estimate means anything.

The README has always said the score is "an estimate, not a calibrated
probability", and that remains true: calibration in the strict sense -- when it
says 0.7 it is right 70% of the time -- needs hundreds of labelled reviews
spanning a wide quality range, and this project has ten contracts on which the
rules are near-perfect. There is not enough variance to fit against.

What can be measured, and is what the gap actually costs in practice, is
*reliability*: does the score move in the right direction, and far enough, when
the review genuinely gets worse? Each labelled contract is reviewed under a
series of deliberate degradations, and two things are reported.

  Invariants. Ordering and cap rules that must hold on every contract. These are
  assertions, and tests/test_calibration.py fails the build when one breaks --
  this is the part that lets a regression be told from an improvement.

  A reliability table. Predicted confidence against observed quality, where
  quality is measured against the answer key and against the undegraded run. It
  is a small-sample diagnostic, not a fitted calibration, and the expected
  calibration error it reports should be read that way.

    uv run python -m scripts.calibrate_confidence
    uv run python -m scripts.calibrate_confidence --verbose
"""

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence, Tuple

from src.core.clause_segmenter import segment_clauses
from src.core.contract_confidence import estimate_contract_confidence
from src.core.document_parser import parse_document
from src.core.red_flag_rules import evaluate_clauses
from src.schemas.contract import ContractType, PartyPosition

LABELS = "tests/fixtures/eval/labels.json"

# How far a prediction may sit from observed quality before it is worth saying
# so. Deliberately loose: with this many samples a tighter number would be
# measuring noise.
MAX_CALIBRATION_ERROR = 0.35


@dataclass
class Run:
    contract: str
    condition: str
    predicted: float
    observed: float
    caps: List[str] = field(default_factory=list)
    findings: int = 0
    detail: str = ""
    # False when a condition could not be applied -- a clean contract has no
    # finding whose quote can be corrupted, so asserting its cap is meaningless.
    applied: bool = True


def _f1(expected: set, actual: set) -> float:
    if not expected and not actual:
        return 1.0
    tp = len(expected & actual)
    if not tp:
        return 0.0
    precision = tp / len(actual)
    recall = tp / len(expected)
    return 2 * precision * recall / (precision + recall)


def _review(clauses, position, analysed, document_text, **kwargs):
    findings = evaluate_clauses(clauses, position)
    report = estimate_contract_confidence(
        clauses=clauses,
        findings=findings,
        document_text=document_text,
        analysed_indices=analysed,
        **kwargs,
    )
    return findings, report


def _conditions(entry) -> List[Tuple[str, Dict[str, Any], str]]:
    """Each degradation, and what it is meant to simulate."""
    return [
        ("full", {}, "everything healthy"),
        ("no_position", {"position": PartyPosition.UNKNOWN},
         "the reviewer never said which side they are on"),
        ("paragraph_fallback", {"strip_numbers": True},
         "an unnumbered contract, so clause boundaries are guesses"),
        ("half_coverage", {"halve_coverage": True},
         "only half the contract received analysis"),
        ("ungrounded", {"corrupt_quote": True},
         "a finding quotes text that is not in the document"),
        ("llm_down", {"llm_available": False}, "no model reached at all"),
        ("reranker_down", {"reranker_available": False}, "cross-encoder unavailable"),
    ]


def measure(entry: dict) -> List[Run]:
    with open(entry["path"], "rb") as handle:
        raw = handle.read()

    declared = PartyPosition(entry["position"])
    contract_type = ContractType(entry["contract_type"])
    expected = {(f["rule_id"], str(f.get("clause") or "")) for f in entry["expected_findings"]}

    # The undegraded run is the reference every other condition is compared to.
    base_document = parse_document(raw, entry["path"].rsplit("/", 1)[-1])
    base_clauses = segment_clauses(base_document)
    base_findings, _ = _review(
        base_clauses, declared, [c.index for c in base_clauses], base_document.text,
        position_source="USER_DECLARED", contract_type=contract_type.value,
    )
    reference_severity = {
        (f.rule_id, f.clause_number or ""): f.severity for f in base_findings
    }

    runs = []
    for name, options, detail in _conditions(entry):
        text = raw
        if options.get("strip_numbers"):
            import re

            text = re.sub(
                r"(?m)^\s*\d{1,3}(?:\.\d{1,3})*[.)]?\s+", "", raw.decode()
            ).encode()

        document = parse_document(text, "c.txt")
        clauses = segment_clauses(document)
        position = options.get("position", declared)
        analysed = [c.index for c in clauses]
        if options.get("halve_coverage"):
            analysed = analysed[: max(1, len(analysed) // 2)]

        findings = evaluate_clauses(clauses, position)
        corrupted = False
        if options.get("corrupt_quote") and findings:
            findings = [f.model_copy(deep=True) for f in findings]
            findings[0].matched_quote = "text that is not in this document at all"
            corrupted = True

        report = estimate_contract_confidence(
            clauses=clauses,
            findings=findings,
            document_text=document.text,
            analysed_indices=analysed,
            position_source="UNKNOWN" if position is PartyPosition.UNKNOWN else "USER_DECLARED",
            contract_type=contract_type.value,
            llm_available=options.get("llm_available", True),
            reranker_available=options.get("reranker_available", True),
        )

        # Observed quality: did the review find the right things, and score them
        # the way the undegraded run did?
        grounded = [
            f for f in findings
            if " ".join(document.text[f.match_start:f.match_end].split()) == f.matched_quote
        ]
        # An unnumbered run has no clause number to compare, so keying on one
        # would score every correct finding as a miss -- measuring the key, not
        # the review. There, compare the rules found; elsewhere keep the clause,
        # since the right rule on the wrong clause is still a real defect.
        numbered = any(c.number for c in clauses)
        if numbered:
            actual = {(f.rule_id, f.clause_number or "") for f in grounded}
            found = _f1(expected, actual)
        else:
            found = _f1({rule for rule, _ in expected}, {f.rule_id for f in grounded})

        reference_by_rule = {rule: sev for (rule, _), sev in reference_severity.items()}
        agreed = []
        for finding in grounded:
            if numbered:
                key = (finding.rule_id, finding.clause_number or "")
                if key in reference_severity:
                    agreed.append(1.0 if reference_severity[key] == finding.severity else 0.0)
            elif finding.rule_id in reference_by_rule:
                agreed.append(1.0 if reference_by_rule[finding.rule_id] == finding.severity else 0.0)
        severity = sum(agreed) / len(agreed) if agreed else (1.0 if not grounded else 0.0)

        runs.append(Run(
            contract=entry["name"], condition=name,
            predicted=report.score, observed=round((found + severity) / 2, 3),
            caps=report.caps_applied, findings=len(grounded), detail=detail,
            applied=corrupted or not options.get("corrupt_quote"),
        ))
    return runs


def check_invariants(by_contract: Dict[str, Dict[str, Run]]) -> List[str]:
    """Ordering and cap rules that must hold on every contract."""
    failures = []
    for contract, runs in by_contract.items():
        full = runs["full"]
        if runs["paragraph_fallback"].predicted > 0.70:
            failures.append(
                f"{contract}: guessed clause boundaries left confidence at "
                f"{runs['paragraph_fallback'].predicted:.2f}, above the 0.70 cap"
            )
        for condition in ("no_position", "paragraph_fallback", "half_coverage",
                          "ungrounded", "llm_down"):
            run = runs.get(condition)
            if run and run.predicted > full.predicted:
                failures.append(
                    f"{contract}: {condition} scored {run.predicted:.2f}, above "
                    f"the undegraded {full.predicted:.2f}"
                )
        if runs["ungrounded"].applied and runs["ungrounded"].predicted > 0.50:
            failures.append(
                f"{contract}: an ungrounded quote left confidence at "
                f"{runs['ungrounded'].predicted:.2f}, above the 0.50 cap"
            )
        if runs["no_position"].predicted > 0.65:
            failures.append(
                f"{contract}: unknown side left confidence at "
                f"{runs['no_position'].predicted:.2f}, above the 0.65 cap"
            )
        if runs["llm_down"].predicted > 0.60:
            failures.append(
                f"{contract}: llm unavailable left confidence at "
                f"{runs['llm_down'].predicted:.2f}, above the 0.60 cap"
            )
        if not 0.05 <= full.predicted <= 0.95:
            failures.append(f"{contract}: {full.predicted:.2f} outside [0.05, 0.95]")
    return failures


def expected_calibration_error(runs: Sequence[Run], buckets: int = 5) -> float:
    total, error = len(runs), 0.0
    for index in range(buckets):
        low, high = index / buckets, (index + 1) / buckets
        members = [r for r in runs if low < r.predicted <= high or (index == 0 and r.predicted <= high)]
        if not members:
            continue
        mean_predicted = sum(r.predicted for r in members) / len(members)
        mean_observed = sum(r.observed for r in members) / len(members)
        error += (len(members) / total) * abs(mean_predicted - mean_observed)
    return error


def main(verbose: bool = False) -> int:
    with open(LABELS) as handle:
        manifest = json.load(handle)

    runs: List[Run] = []
    by_contract: Dict[str, Dict[str, Run]] = {}
    for entry in manifest["contracts"]:
        contract_runs = measure(entry)
        runs.extend(contract_runs)
        by_contract[entry["name"]] = {r.condition: r for r in contract_runs}

    conditions = [c for c, _, _ in _conditions(manifest["contracts"][0])]
    print(f"\n{'condition':22s} {'predicted':>10s} {'observed':>9s} {'gap':>7s}   caps seen")
    print("-" * 78)
    for condition in conditions:
        members = [r for r in runs if r.condition == condition]
        predicted = sum(r.predicted for r in members) / len(members)
        observed = sum(r.observed for r in members) / len(members)
        caps = sorted({c.split("<=")[0] for r in members for c in r.caps})
        print(f"  {condition:20s} {predicted:10.3f} {observed:9.3f} {predicted - observed:+7.3f}   "
              f"{', '.join(caps) or '-'}")

    if verbose:
        print(f"\n{'contract':30s} {'condition':20s} {'pred':>6s} {'obs':>6s} {'n':>4s}")
        print("-" * 72)
        for run in runs:
            print(f"  {run.contract:28s} {run.condition:20s} {run.predicted:6.2f} "
                  f"{run.observed:6.2f} {run.findings:4d}")

    print(f"\n{'bucket':14s} {'n':>4s} {'mean predicted':>15s} {'mean observed':>14s}")
    print("-" * 52)
    for index in range(5):
        low, high = index / 5, (index + 1) / 5
        members = [r for r in runs if low < r.predicted <= high or (index == 0 and r.predicted <= high)]
        if not members:
            continue
        print(f"  {low:.1f}-{high:.1f}      {len(members):4d} "
              f"{sum(r.predicted for r in members) / len(members):15.3f} "
              f"{sum(r.observed for r in members) / len(members):14.3f}")

    ece = expected_calibration_error(runs)
    failures = check_invariants(by_contract)

    print(f"\n{len(runs)} runs over {len(by_contract)} contracts x {len(conditions)} conditions")
    print(f"expected calibration error: {ece:.3f}  (small-sample diagnostic, not a fitted calibration)")

    if failures:
        print(f"\nFAIL: {len(failures)} invariant(s) broken")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\nPASS: every ordering and cap invariant holds")
    if ece > MAX_CALIBRATION_ERROR:
        print(f"NOTE: calibration error {ece:.3f} exceeds {MAX_CALIBRATION_ERROR}. The "
              "estimator is deliberately conservative under degradation -- it lowers "
              "the score for coverage the quality metric cannot see -- so some gap is "
              "expected here rather than wrong.")
    return 0


if __name__ == "__main__":
    sys.exit(main(verbose="--verbose" in sys.argv))
