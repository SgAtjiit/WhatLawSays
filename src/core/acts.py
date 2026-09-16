"""Canonical Act names and the retrieval pools they form.

Split out of `vector_store` so that modules needing only the names -- the
red-flag rules carry statutory citations directly -- can import them without
constructing the embedding models, which `vector_store` does at import time.
`vector_store` re-exports every name here, so existing imports are unaffected.
"""

# Canonical `act` payload values, exactly as indexed in the collection.
ACT_BNS = "Bharatiya Nyaya Sanhita, 2023 (BNS)"
ACT_BNSS = "Bharatiya Nagarik Suraksha Sanhita, 2023 (BNSS)"
ACT_BSA = "Bharatiya Sakshya Adhiniyam, 2023 (BSA)"
ACT_CONSTITUTION = "Constitution of India"

# Only the BNS creates offences. Searching it alongside the other three left the
# substantive penal law outnumbered roughly 3:1 in every candidate pool, so
# procedural and constitutional provisions crowded out the sections an offence
# analysis actually needs.
ACT_IT = "The Information Technology Act, 2000 (IT Act)"
ACT_POSH = (
    "The Sexual Harassment of Women at Workplace "
    "(Prevention, Prohibition and Redressal) Act, 2013 (POSH Act)"
)

# The IT Act (ss. 65-74) and the POSH Act (s. 26) both create offences, so they
# join the BNS in the offence-identification pass. Their procedural and
# definitional sections are filtered out downstream by title, exactly as the
# BNS's own preliminary provisions already are.
SUBSTANTIVE_ACTS = [ACT_BNS, ACT_IT, ACT_POSH]
PROCEDURAL_ACTS = [ACT_BNSS, ACT_BSA, ACT_CONSTITUTION]

# Contract review is a civil question, so it draws on a third pool that the
# criminal passes never see. Folding these into SUBSTANTIVE_ACTS would be harmful
# in both directions: a lease dispute would start surfacing BNS offences, and an
# assault scenario would start surfacing lease covenants.
#
# `prescribes_penalty` cannot gate this pool the way it gates penal law -- only 1
# of the Contract Act's 192 sections carries punishment language, and 0 of the
# Arbitration Act's 93 -- so the contract pass must not apply that filter.
ACT_CONTRACT = "The Indian Contract Act, 1872 (Contract Act)"
ACT_SPECIFIC_RELIEF = "The Specific Relief Act, 1963 (SRA)"
ACT_ARBITRATION = "The Arbitration and Conciliation Act, 1996 (Arbitration Act)"
ACT_CONSUMER = "The Consumer Protection Act, 2019 (CPA)"
# The trailing period is the India Code source's own rendering of the short
# title. These strings are matched verbatim against the Qdrant `act` payload, so
# tidying it would silently empty the filter.
ACT_DPDP = "The Digital Personal Data Protection Act, 2023. (DPDP Act)"
ACT_TRANSFER_OF_PROPERTY = "The Transfer of Property Act, 1882 (TPA)"

CONTRACT_ACTS = [
    ACT_CONTRACT,
    ACT_SPECIFIC_RELIEF,
    ACT_ARBITRATION,
    ACT_CONSUMER,
    ACT_DPDP,
    ACT_TRANSFER_OF_PROPERTY,
]
