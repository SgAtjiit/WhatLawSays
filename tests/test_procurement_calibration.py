"""Reliability of the procurement confidence score.

Not calibration in the strict sense -- see the harness docstring. What is
asserted here is that the number moves the right way under degradation, and that
where it is wrong it is wrong in the safe direction.

These tests exist because this harness already caught a real miscalibration: a
statute-only review scored 0.889 against a full review's 0.817, because dropping
`policy_authority` renormalised the weights over four components that were all
near 1.0. The estimator was rewarding a review for never looking at the
customer's policy. `STATUTE_ONLY_CAP` came out of that measurement.
"""

import pytest

from scripts.calibrate_procurement_confidence import (
    CAPS,
    CONDITIONS,
    calibrate,
    expected_calibration_error,
)

MAX_CALIBRATION_ERROR = 0.30
MAX_OVERCONFIDENCE = 0.30


@pytest.fixture(scope="module")
def table():
    return calibrate(verbose=False)


def test_every_condition_is_measured(table):
    assert set(table) == set(CONDITIONS)


def test_no_degraded_review_outscores_a_healthy_one(table):
    full = table["full"]["predicted"]
    for condition, row in table.items():
        if condition == "full":
            continue
        assert row["predicted"] <= full + 1e-9, (
            f"{condition} scored {row['predicted']:.3f} against a healthy {full:.3f}"
        )


@pytest.mark.parametrize("condition", sorted(CAPS))
def test_each_cap_holds_on_every_event(condition, table):
    ceiling = CAPS[condition]
    assert table[condition]["max_predicted"] <= ceiling + 1e-9, (
        f"{condition} reached {table[condition]['max_predicted']:.3f}, above its {ceiling} cap"
    )


def test_a_statute_only_review_cannot_score_like_a_full_one(table):
    """The regression that produced STATUTE_ONLY_CAP."""
    assert table["no_policy"]["predicted"] < table["full"]["predicted"]


def test_unratified_rules_carry_the_heaviest_penalty(table):
    """Enforcing rules nobody confirmed is not measuring the customer's policy."""
    others = [v["predicted"] for k, v in table.items() if k != "unratified_policy"]
    assert table["unratified_policy"]["predicted"] <= min(others) + 1e-9


def test_the_estimator_errs_towards_under_confidence(table):
    """Where the score is wrong, it should read low rather than high."""
    for condition, row in table.items():
        overconfidence = row["predicted"] - row["observed"]
        assert overconfidence <= MAX_OVERCONFIDENCE, (
            f"{condition} predicted {row['predicted']:.3f} against observed "
            f"{row['observed']:.3f}"
        )


def test_the_reliability_error_stays_bounded(table):
    assert expected_calibration_error(table) < MAX_CALIBRATION_ERROR


def test_the_score_stays_within_its_declared_bounds(table):
    for condition, row in table.items():
        assert 0.05 <= row["predicted"] <= 0.95, condition
