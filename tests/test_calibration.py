"""The confidence score must move when the review actually gets worse.

Strict calibration -- when it says 0.7 it is right 70% of the time -- needs far
more labelled reviews than this project has, and the README says so. What is
testable, and what the gap costs in practice, is reliability: the ordering and
the caps. Those are asserted here so a regression in the estimator fails the
build instead of quietly shipping an over-confident review.

The harness itself lives in scripts/calibrate_confidence.py and prints the full
table.
"""

import json

import pytest

from scripts.calibrate_confidence import (
    LABELS,
    check_invariants,
    expected_calibration_error,
    main,
    measure,
)


@pytest.fixture(scope="module")
def runs():
    with open(LABELS) as handle:
        manifest = json.load(handle)
    every = []
    by_contract = {}
    for entry in manifest["contracts"]:
        contract_runs = measure(entry)
        every.extend(contract_runs)
        by_contract[entry["name"]] = {r.condition: r for r in contract_runs}
    return every, by_contract


def test_every_ordering_and_cap_invariant_holds(runs):
    _, by_contract = runs
    assert check_invariants(by_contract) == []


def test_the_calibration_suite_passes():
    assert main() == 0


def test_a_degraded_review_never_outscores_a_healthy_one(runs):
    """The single property that makes the number worth showing at all."""
    _, by_contract = runs
    for contract, conditions in by_contract.items():
        healthy = conditions["full"].predicted
        for name, run in conditions.items():
            if name == "full":
                continue
            assert run.predicted <= healthy, f"{contract}/{name}: {run.predicted} > {healthy}"


def test_an_ungrounded_quote_is_the_hardest_cap(runs):
    """A quote that is not in the document is the strongest signal available
    that a review cannot be trusted, so it must bind tightest."""
    _, by_contract = runs
    for contract, conditions in by_contract.items():
        run = conditions["ungrounded"]
        if not run.applied:
            continue  # a clean contract has no finding whose quote can be broken
        assert run.predicted <= 0.50, contract


def test_guessed_clause_boundaries_are_capped(runs):
    """Measured: finding quality falls to about 0.45 under paragraph fallback,
    while the weighted mean alone still reported 0.81."""
    _, by_contract = runs
    for contract, conditions in by_contract.items():
        assert conditions["paragraph_fallback"].predicted <= 0.70, contract


def test_a_healthy_review_still_never_asserts_certainty(runs):
    _, by_contract = runs
    for contract, conditions in by_contract.items():
        assert 0.05 <= conditions["full"].predicted <= 0.95, contract


def test_the_estimator_errs_towards_under_confidence(runs):
    """Every remaining gap but one is the estimator scoring a good review low,
    which is the right direction to be wrong in for a legal tool."""
    every, _ = runs
    over_confident = [r for r in every if r.predicted - r.observed > 0.30]
    assert not over_confident, [
        (r.contract, r.condition, r.predicted, r.observed) for r in over_confident
    ]


def test_calibration_error_is_tracked(runs):
    """Not a pass/fail on calibration -- the sample is far too small for that.
    It fails only on a large regression, so a change that makes the score
    systematically wrong cannot land unnoticed."""
    every, _ = runs
    assert expected_calibration_error(every) < 0.30
