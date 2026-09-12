"""Floors for the procurement spine, so a regression fails the build.

The aggregate precision and recall floors are the ordinary part. The interesting
assertions are the three zero-tolerance counters and
`test_the_answer_key_covers_every_check`, which between them stop the two ways a
compliance engine degrades without anyone noticing: a check quietly stops firing,
or a check that could not run starts reporting that it passed.
"""

import json

import pytest

from scripts.evaluate_procurement_review import (
    FIXTURES,
    MAX_CLEAN_EVENT_FINDINGS,
    MAX_EVIDENCE_FAILURES,
    MAX_INDICATOR_SOLD_AS_BREACH,
    MAX_UNDETERMINED_SOLD_AS_BREACH,
    MAX_UNDETERMINED_SOLD_AS_PASS,
    MIN_PRECISION,
    MIN_RECALL,
    evaluate,
)
from src.core.bid_integrity import SPECS
from src.core.procurement_rules import POLICY_TEMPLATES, STATUTORY_CHECKS


@pytest.fixture(scope="module")
def result():
    return evaluate(verbose=False)


def test_precision_floor(result):
    assert result["precision"] >= MIN_PRECISION, (
        f"precision {result['precision']:.3f}; {result['fp']} false positive(s)"
    )


def test_recall_floor(result):
    assert result["recall"] >= MIN_RECALL, (
        f"recall {result['recall']:.3f}; {result['fn']} missed finding(s)"
    )


def test_nothing_fires_on_a_deliberately_clean_event(result):
    """An engine that flags everything is useless, and only clean events show it."""
    assert result["clean_findings"] <= MAX_CLEAN_EVENT_FINDINGS


def test_every_finding_re_derives_from_its_own_event(result):
    assert result["evidence_failures"] <= MAX_EVIDENCE_FAILURES


def test_a_check_that_could_not_run_is_never_reported_as_passing(result):
    """The single most dangerous failure available to this system."""
    assert result["undetermined_sold_as_pass"] <= MAX_UNDETERMINED_SOLD_AS_PASS


def test_a_check_that_could_not_run_is_never_reported_as_a_breach(result):
    assert result["undetermined_sold_as_breach"] <= MAX_UNDETERMINED_SOLD_AS_BREACH


def test_a_statistical_pattern_is_never_reported_as_a_breach(result):
    """It names real companies. It cannot be allowed to read as a determination."""
    assert result["indicator_sold_as_breach"] <= MAX_INDICATOR_SOLD_AS_BREACH


def test_every_labelled_check_actually_fires(result):
    """An aggregate floor would let four singleton checks be deleted at 28 of 32."""
    assert result["never_fired"] == [], (
        f"labelled but never produced: {result['never_fired']}"
    )


def test_the_answer_key_covers_every_check():
    """A new check cannot ship without a labelled event exercising it."""
    labels = json.loads((FIXTURES / "labels.json").read_text())
    labelled = {
        check_id
        for meta in labels.values()
        for check_id, _, _ in meta["expected"]
    }
    registry = (
        {spec.check_id for spec, _ in STATUTORY_CHECKS}
        | {t.spec.check_id for t in POLICY_TEMPLATES.values()}
        | set(SPECS)
    )
    missing = sorted(registry - labelled)
    assert missing == [], f"checks with no labelled event: {missing}"


def test_every_check_has_a_remediation():
    """A finding with nothing to do about it is half a product."""
    from src.core.procurement_remediations import missing_actions

    registry = (
        [spec.check_id for spec, _ in STATUTORY_CHECKS]
        + [t.spec.check_id for t in POLICY_TEMPLATES.values()]
        + list(SPECS)
    )
    assert missing_actions(registry) == []
