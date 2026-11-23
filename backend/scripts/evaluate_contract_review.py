"""Score the deterministic contract-review spine against hand-labelled contracts.

Without this there is no way to tell an improvement from a regression: a rule
change that catches one more non-compete may silently start flagging every
confidentiality clause as one. The README already says as much about the
confidence estimator, and the same is true of the rules.

Scores the deterministic spine only -- parse, segment, rules, checklists. Model
findings are not held to a fixed answer key because they are not reproducible
enough for one; their quality is checked separately, by grounding.

A finding counts as correct when its rule_id AND clause number both match the
label. The clause matters: the right rule on the wrong clause is a segmentation
bug wearing a correct answer's clothes.

Usage:
    uv run python -m scripts.evaluate_contract_review            # table + exit code
    uv run python -m scripts.evaluate_contract_review --verbose  # every FP and FN
"""

import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from src.core.clause_checklists import find_missing_clauses
from src.core.clause_segmenter import segment_clauses
from src.core.document_parser import parse_document
from src.core.red_flag_rules import evaluate_clauses, verify_quotes
from src.schemas.contract import ContractType, PartyPosition

LABELS = "tests/fixtures/eval/labels.json"

# Floors the suite must clear. Deliberately not 1.0: a corpus of ten contracts
# cannot justify a claim of perfection, and a floor that is met exactly today
# leaves no room to add a harder contract tomorrow without the build going red.
MIN_PRECISION = 0.90
MIN_RECALL = 0.90
MAX_CLEAN_CONTRACT_FINDINGS = 0


@dataclass
class ContractScore:
    name: str
    clean: bool
    true_positives: Set[Tuple[str, str]] = field(default_factory=set)
    false_positives: Set[Tuple[str, str]] = field(default_factory=set)
    false_negatives: Set[Tuple[str, str]] = field(default_factory=set)
    missing_expected: Set[str] = field(default_factory=set)
    missing_found: Set[str] = field(default_factory=set)
    grounding_problems: List[str] = field(default_factory=list)

    @property
    def missing_ok(self) -> bool:
        return self.missing_expected == self.missing_found


def _clause_label(value) -> str:
    """Normalise a label's clause to the segmenter's string form.

    A clause given as null (an unnumbered contract) or as an integer never
    matched the segmenter's "4", producing a silent FN+FP pair for every correct
    finding. "" is what the harness records for an unnumbered clause.
    """
    if value is None:
        return ""
    return str(value).strip().rstrip(".")


def compute_metrics(scores: List[ContractScore]) -> Tuple[int, int, int, float, float]:
    tp = sum(len(s.true_positives) for s in scores)
    fp = sum(len(s.false_positives) for s in scores)
    fn = sum(len(s.false_negatives) for s in scores)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return tp, fp, fn, precision, recall


def score_one(entry: dict) -> ContractScore:
    with open(entry["path"], "rb") as handle:
        document = parse_document(handle.read(), entry["path"].rsplit("/", 1)[-1])
    clauses = segment_clauses(document)
    position = PartyPosition(entry["position"])
    contract_type = ContractType(entry["contract_type"])

    findings = evaluate_clauses(clauses, position)
    missing = find_missing_clauses(clauses, contract_type, position)

    expected = {
        (f["rule_id"], _clause_label(f.get("clause"))) for f in entry["expected_findings"]
    }
    actual = {(f.rule_id, f.clause_number or "") for f in findings}

    return ContractScore(
        name=entry["name"],
        clean=bool(entry.get("clean")),
        true_positives=expected & actual,
        false_positives=actual - expected,
        false_negatives=expected - actual,
        missing_expected=set(entry.get("expected_missing", [])),
        missing_found={m.category.value for m in missing},
        grounding_problems=verify_quotes(findings, document.text),
    )


def evaluate(verbose: bool = False) -> int:
    with open(LABELS) as handle:
        manifest = json.load(handle)

    scores = [score_one(entry) for entry in manifest["contracts"]]

    tp, fp, fn, precision, recall = compute_metrics(scores)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    print(f"\n{'contract':32s} {'TP':>3s} {'FP':>3s} {'FN':>3s}  gaps   grounding")
    print("-" * 72)
    for s in scores:
        flag = "  CLEAN" if s.clean else ""
        gaps = "ok " if s.missing_ok else "BAD"
        grounding = "ok" if not s.grounding_problems else f"{len(s.grounding_problems)} BAD"
        print(
            f"{s.name:32s} {len(s.true_positives):3d} {len(s.false_positives):3d} "
            f"{len(s.false_negatives):3d}  {gaps}    {grounding}{flag}"
        )
        if verbose or s.false_positives or s.false_negatives or not s.missing_ok:
            for rule, clause in sorted(s.false_positives):
                print(f"      FALSE POSITIVE  {rule} @ clause {clause}")
            for rule, clause in sorted(s.false_negatives):
                print(f"      MISSED          {rule} @ clause {clause}")
            if not s.missing_ok:
                print(
                    f"      GAPS expected {sorted(s.missing_expected)} "
                    f"found {sorted(s.missing_found)}"
                )

    per_rule: Dict[str, Counter] = defaultdict(Counter)
    for s in scores:
        for rule, _ in s.true_positives:
            per_rule[rule]["tp"] += 1
        for rule, _ in s.false_positives:
            per_rule[rule]["fp"] += 1
        for rule, _ in s.false_negatives:
            per_rule[rule]["fn"] += 1

    print(f"\n{'rule':32s} {'TP':>3s} {'FP':>3s} {'FN':>3s}")
    print("-" * 44)
    for rule in sorted(per_rule):
        c = per_rule[rule]
        print(f"{rule:32s} {c['tp']:3d} {c['fp']:3d} {c['fn']:3d}")

    clean_findings = sum(
        len(s.true_positives | s.false_positives) for s in scores if s.clean
    )
    grounding_failures = sum(len(s.grounding_problems) for s in scores)

    print(
        f"\nprecision {precision:.3f}  recall {recall:.3f}  f1 {f1:.3f}   "
        f"({tp} TP / {fp} FP / {fn} FN over {len(scores)} contracts)"
    )
    print(f"findings on clean contracts: {clean_findings}   quote grounding failures: {grounding_failures}")

    failures = []
    if precision < MIN_PRECISION:
        failures.append(f"precision {precision:.3f} < {MIN_PRECISION}")
    if recall < MIN_RECALL:
        failures.append(f"recall {recall:.3f} < {MIN_RECALL}")
    if clean_findings > MAX_CLEAN_CONTRACT_FINDINGS:
        failures.append(f"{clean_findings} finding(s) on contracts labelled clean")
    if grounding_failures:
        failures.append(f"{grounding_failures} finding(s) quote text not in the document")
    # An aggregate recall floor of 0.90 lets four singleton rules be deleted
    # outright while the suite stays green (36/40 = 0.900 exactly). Each rule
    # the answer key names must therefore still fire somewhere. Measured
    # against the labels rather than RULES, so a deleted rule is caught too.
    labelled_rules = {
        f["rule_id"] for entry in manifest["contracts"] for f in entry["expected_findings"]
    }
    firing_rules = {rule for rule, c in per_rule.items() if c["tp"] > 0}
    silent = sorted(labelled_rules - firing_rules)
    if silent:
        failures.append("labelled rule(s) with no true positive anywhere: " + ", ".join(silent))
    if any(not s.missing_ok for s in scores):
        failures.append("gap detection disagrees with labels on " + ", ".join(
            s.name for s in scores if not s.missing_ok))

    if failures:
        print("\nFAIL: " + "; ".join(failures))
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(evaluate(verbose="--verbose" in sys.argv))
