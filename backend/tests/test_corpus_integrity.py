"""The corpus must not contain dead law.

The audit found Arbitration Act s.87 -- struck down by the Supreme Court and
omitted by Act 3 of 2021 -- indexed with its full operative text, and 36 omitted
Articles of the Constitution returned at rank 1 for their own titles. A
retrieval system built to prevent legal hallucination cannot have provisions in
its corpus that are no longer law.
"""

import json
import pathlib

import pytest

from src.core.acts import ACT_BNS, ACT_CONSTITUTION, ACT_IT
from src.core.confidence import section_key
from src.schemas.corpus import is_dead_law

DATA = sorted(
    p for p in pathlib.Path("data").glob("*.json") if p.name != "legal_corpus.json"
)

# Real bodies from India Code harvests, verbatim.
DEAD_BODIES = [
    "[Seller when not responsible for latent defects.] Rep. by s. 65, ibid.",
    "1 [Effect of arbitral and related court proceedings.] Rep. by Act 3 of 2021, s. 3.",
    "Repealed by the Repealing and Amending Act, 1974 (56 of 1974), s. 2 and Sch. I.",
    "Omitted by the Constitution (Forty-fourth Amendment) Act, 1978, s. 5 (w.e.f. 20-6-1979).",
    "[Omitted.]",
    "Rep. by the Sale of Goods Act, 1930 (3 of 1930), s. 65.",
]

LIVE_BODIES = [
    "Every agreement by which any one is restrained from exercising a lawful profession, trade or business of any kind, is to that extent void.",
    "(1) This Act may be called the Indian Contract Act, 1872.",
    "The repeal of any enactment shall not affect any right accrued before the repeal.",
]


@pytest.mark.parametrize("body", DEAD_BODIES)
def test_a_repeal_or_omission_note_is_dead_law(body):
    assert is_dead_law("Any Act", "Section 1", "Some title", body)


@pytest.mark.parametrize("body", LIVE_BODIES)
def test_operative_text_is_not_mistaken_for_dead_law(body):
    """"The repeal of any enactment ..." is a live saving clause, not a repeal note."""
    assert not is_dead_law("Any Act", "Section 1", "Some title", body)


def test_a_title_that_only_says_repealed_is_dead_law():
    assert is_dead_law("Any Act", "Section 1", "Repealed.", "anything")
    assert is_dead_law("Any Act", "Section 1", "[Repealed.].", "anything")


def test_the_fetch_script_and_the_ingest_guard_agree():
    """Two copies of the pattern exist because the fetch script must stay
    stdlib-only. They must never drift apart."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("fetch", "scripts/fetch_indiacode_act.py")
    fetch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetch)
    for body in DEAD_BODIES:
        assert bool(fetch.REPEALED_BODY.match(body)) == is_dead_law("x", "x", "x", body), body
    for body in LIVE_BODIES:
        assert not fetch.REPEALED_BODY.match(body), body


@pytest.mark.parametrize("path", DATA, ids=lambda p: p.name)
def test_no_indexed_provision_is_dead_law(path):
    dead = [
        d["section_number"]
        for d in json.loads(path.read_text())
        if is_dead_law(d.get("act", ""), d.get("section_number", ""), d.get("title", ""), d.get("content", ""))
    ]
    assert dead == [], f"{path.name} carries dead law: {dead[:10]}"


def test_arbitration_s87_is_not_in_the_corpus():
    """Struck down in Hindustan Construction (2019), omitted by Act 3 of 2021,
    still rendered by India Code with its full operative text."""
    numbers = {d["section_number"] for d in json.loads(pathlib.Path("data/arbitration_act.json").read_text())}
    assert "Section 87" not in numbers


def test_no_two_provisions_share_an_act_and_section():
    for path in DATA:
        seen = set()
        for d in json.loads(path.read_text()):
            key = (d.get("act"), d.get("section_number"))
            assert key not in seen, f"{path.name}: duplicate {key}"
            seen.add(key)


@pytest.mark.parametrize("variant", ["Section 66B", "Section 66-B", "Section 66 B", "66B", "s. 66-B"])
def test_a_lettered_section_keeps_its_letter(variant):
    """'66-B' collapsed onto '66', so the offence grounded against the parent
    section's chunk with a perfect score while its own chunk scored zero."""
    assert section_key(ACT_IT, variant) == ("it", "66b")
    assert section_key(ACT_IT, variant) != section_key(ACT_IT, "Section 66")


def test_prose_after_a_section_number_is_not_a_suffix():
    assert section_key(ACT_BNS, "Section 302 read with section 34") == ("bns", "302")
    assert section_key(ACT_CONSTITUTION, "Article 243-O") == ("constitution", "243o")
