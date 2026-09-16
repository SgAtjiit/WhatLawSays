"""The evaluation harness as a test, so a regression fails the build.

The harness itself lives in scripts/evaluate_contract_review.py and prints the
full table; this just holds the line. Floors are below 1.0 on purpose: ten
contracts cannot justify a claim of perfection, and a floor met exactly today
leaves no room to add a harder contract tomorrow without the build going red.
"""

import json

from scripts.evaluate_contract_review import (
    LABELS,
    MAX_CLEAN_CONTRACT_FINDINGS,
    MIN_PRECISION,
    MIN_RECALL,
    compute_metrics,
    evaluate,
    score_one,
)


def _scores():
    with open(LABELS) as handle:
        return [score_one(entry) for entry in json.load(handle)["contracts"]]


def test_the_evaluation_suite_passes():
    assert evaluate() == 0


def test_precision_and_recall_clear_their_floors():
    # compute_metrics guards the zero case, so a rule engine that emits nothing
    # fails as "recall 0.0 < 0.9" rather than as a ZeroDivisionError.
    _, _, _, precision, recall = compute_metrics(_scores())
    assert precision >= MIN_PRECISION
    assert recall >= MIN_RECALL


def test_every_labelled_rule_still_fires_somewhere():
    """The aggregate floor is not enough: with recall at 0.90, four singleton
    rules can be deleted outright and the suite stays green. Each rule the
    answer key names must produce at least one true positive."""
    with open(LABELS) as handle:
        labelled = {
            f["rule_id"]
            for entry in json.load(handle)["contracts"]
            for f in entry["expected_findings"]
        }
    firing = {rule for score in _scores() for rule, _ in score.true_positives}
    assert labelled <= firing, f"labelled rules that never fire: {sorted(labelled - firing)}"


def test_clean_contracts_produce_no_findings():
    """The most important row in the table. A rule that fires on a fair contract
    teaches people to ignore the review."""
    for score in _scores():
        if score.clean:
            assert len(score.true_positives | score.false_positives) <= MAX_CLEAN_CONTRACT_FINDINGS, score.name


def test_every_label_quotes_real_text():
    for score in _scores():
        assert score.grounding_problems == [], score.name


def test_the_answer_key_covers_every_rule():
    """A rule with no labelled positive is a rule the harness cannot regress."""
    from src.core.red_flag_rules import RULES

    with open(LABELS) as handle:
        labelled = {
            f["rule_id"]
            for entry in json.load(handle)["contracts"]
            for f in entry["expected_findings"]
        }
    assert {rule.rule_id for rule in RULES} <= labelled


def test_the_answer_key_has_clean_contracts():
    """Without a clean contract there is no measurement of false positives at all."""
    with open(LABELS) as handle:
        assert sum(1 for e in json.load(handle)["contracts"] if e.get("clean")) >= 2
