"""Tests for act-scoped retrieval.

Offence identification must see substantive penal law only. Procedural and
constitutional provisions are retrieved separately and feed the procedural tab.
Contract review draws on a third, civil pool that neither criminal pass sees.
"""

import asyncio

from src.core.confidence import act_family, section_key
from src.core.vector_store import (
    ACT_ARBITRATION,
    ACT_BNS,
    ACT_BNSS,
    ACT_BSA,
    ACT_CONSTITUTION,
    ACT_CONSUMER,
    ACT_CONTRACT,
    ACT_DPDP,
    ACT_IT,
    ACT_POSH,
    ACT_SPECIFIC_RELIEF,
    ACT_TRANSFER_OF_PROPERTY,
    CONTRACT_ACTS,
    PROCEDURAL_ACTS,
    SUBSTANTIVE_ACTS,
    vector_store,
)

CRIMINAL_ACTS = {ACT_BNS, ACT_BNSS, ACT_BSA, ACT_CONSTITUTION, ACT_IT, ACT_POSH}
CIVIL_ACTS = {
    ACT_CONTRACT,
    ACT_SPECIFIC_RELIEF,
    ACT_ARBITRATION,
    ACT_CONSUMER,
    ACT_DPDP,
    ACT_TRANSFER_OF_PROPERTY,
}
ALL_INDEXED_ACTS = CRIMINAL_ACTS | CIVIL_ACTS


class _CapturingClient:
    """Stands in for the Qdrant client and records the query it was handed."""

    def __init__(self):
        self.prefetch = None

    async def query_points(self, **kwargs):
        self.prefetch = kwargs.get("prefetch")

        class _Empty:
            points = []

        return _Empty()


def search_with(acts):
    client = _CapturingClient()
    original = vector_store.client
    vector_store.client = client
    try:
        asyncio.run(vector_store.hybrid_search("theft of a laptop", limit=5, acts=acts))
    finally:
        vector_store.client = original
    return client.prefetch


def test_act_pools_partition_the_indexed_corpus():
    """Every indexed act belongs to exactly one pool -- none dropped, none double-counted."""
    pools = [set(SUBSTANTIVE_ACTS), set(PROCEDURAL_ACTS), set(CONTRACT_ACTS)]
    for i, pool in enumerate(pools):
        for other in pools[i + 1 :]:
            assert pool.isdisjoint(other)
    assert set().union(*pools) == ALL_INDEXED_ACTS


def test_contract_pool_is_isolated_from_the_criminal_passes():
    """A lease dispute must not surface BNS offences, and an assault scenario
    must not surface lease covenants."""
    assert set(CONTRACT_ACTS) == CIVIL_ACTS
    assert CIVIL_ACTS.isdisjoint(CRIMINAL_ACTS)


def test_offence_creating_acts_are_the_substantive_pool():
    """BNS, IT Act and POSH Act all create offences; the other three do not."""
    for act in (ACT_BNS, ACT_IT, ACT_POSH):
        assert act in SUBSTANTIVE_ACTS
    for act in (ACT_BNSS, ACT_BSA, ACT_CONSTITUTION):
        assert act not in SUBSTANTIVE_ACTS
        assert act in PROCEDURAL_ACTS


def test_every_act_resolves_to_its_own_family():
    """Without distinct families the special Acts collapse into "unknown", and an
    IT Act section can then ground a citation against a POSH section of the same
    number."""
    families = [act_family(a) for a in ALL_INDEXED_ACTS]
    assert "unknown" not in families
    assert len(set(families)) == len(ALL_INDEXED_ACTS)


def test_same_numbered_sections_in_different_acts_do_not_collide():
    assert section_key(ACT_IT, "Section 66") != section_key(ACT_POSH, "Section 66")
    assert section_key(ACT_IT, "Section 66") != section_key(ACT_BNS, "Section 66")


def test_scoped_search_filters_both_prefetches():
    """The filter must shape candidate generation, not just trim the fused result."""
    prefetch = search_with(SUBSTANTIVE_ACTS)
    assert len(prefetch) == 2
    for branch in prefetch:
        condition = branch.filter.must[0]
        assert condition.key == "act"
        assert condition.match.any == SUBSTANTIVE_ACTS


def test_procedural_search_excludes_the_bns():
    prefetch = search_with(PROCEDURAL_ACTS)
    for branch in prefetch:
        assert ACT_BNS not in branch.filter.must[0].match.any


def test_contract_search_excludes_every_criminal_act():
    prefetch = search_with(CONTRACT_ACTS)
    assert len(prefetch) == 2
    for branch in prefetch:
        scoped = set(branch.filter.must[0].match.any)
        assert scoped == CIVIL_ACTS
        assert scoped.isdisjoint(CRIMINAL_ACTS)


def test_unscoped_search_is_still_possible():
    """Passing no acts must not silently apply a filter."""
    prefetch = search_with(None)
    assert all(branch.filter is None for branch in prefetch)
