import asyncio
from src.core.vector_store import vector_store
from src.schemas.corpus import LegalSectionDoc

# Initial Seed Data for BNS & BNSS Core Sections
CORPUS_SEED: list[LegalSectionDoc] = [
    LegalSectionDoc(
        act="Bharatiya Nyaya Sanhita, 2023 (BNS)",
        chapter="Chapter XVII - Offences Against Property",
        section_number="Section 329",
        title="Criminal Trespass and House-trespass",
        content=(
            "Whoever enters into or upon property in the possession of another with intent to commit an offence "
            "or to intimidate, insult or annoy any person in possession of such property, or having lawfully entered, "
            "unlawfully remains there with intent to intimidate, insult, or annoy, commits criminal trespass. "
            "Entering a human dwelling without permission constitutes house-trespass."
        ),
        elements=[
            "Unauthorized entry onto private property",
            "Intent to commit offence, intimidate, insult, or annoy",
            "Entry into dwelling/building without consent",
        ],
        punishment="Imprisonment up to 1 year, or fine up to Rs. 5,000, or both.",
        bailable=True,
        cognizable=True,
    ),
    LegalSectionDoc(
        act="Bharatiya Nagarik Suraksha Sanhita, 2023 (BNSS)",
        chapter="Chapter XII - Information to Police and Powers to Investigate",
        section_number="Section 185",
        title="Search by Police Officer",
        content=(
            "Whenever an officer in charge of a police station or an investigating officer has reasonable grounds for "
            "believing that anything necessary for the purposes of an investigation into any offence may be found in any place, "
            "and that such thing cannot in his opinion be otherwise obtained without undue delay, such officer may, after recording "
            "in writing the grounds of his belief and specifying therein the thing, conduct or cause search to be made. "
            "Arbitrary search or access to personal electronic devices without recorded reasons or warrant is prohibited."
        ),
        elements=[
            "Officer must have reasonable grounds during investigation",
            "Must record grounds of belief in writing prior to search",
            "Unauthorized electronic device access violates search protocols",
        ],
        punishment="Procedural invalidation of seized evidence, departmental action against errant officer.",
        bailable=None,
        cognizable=None,
    ),
    LegalSectionDoc(
        act="Bharatiya Nyaya Sanhita, 2023 (BNS)",
        chapter="Chapter VIII - Offences Affecting the Public Tranquillity",
        section_number="Section 189",
        title="Unlawful Assembly",
        content=(
            "An assembly of five or more persons is designated an unlawful assembly if the common object of the persons "
            "composing that assembly is to overawe by criminal force, or show of criminal force, the Central or State Government, "
            "or any public servant in exercise of lawful power."
        ),
        elements=["Assembly of 5 or more persons", "Common unlawful object"],
        punishment="Imprisonment up to 6 months, or fine, or both.",
        bailable=True,
        cognizable=True,
    ),
    LegalSectionDoc(
        act="Constitution of India",
        chapter="Part III - Fundamental Rights",
        section_number="Article 21",
        title="Protection of Life and Personal Liberty",
        content=(
            "No person shall be deprived of his life or personal liberty except according to procedure established by law. "
            "The right to privacy and informational privacy of digital devices is protected as an intrinsic part of personal liberty."
        ),
        elements=[
            "State interference requires lawful procedure",
            "Right to digital privacy protected against arbitrary state action",
        ],
        punishment="Constitutional remedy via Writ Petition under Article 32 or Article 226.",
        bailable=None,
        cognizable=None,
    ),
]


async def main():
  print("[+] Initializing Qdrant Collection with Hybrid Vector Schemas...")
  await vector_store.setup_collection()
  print("[+] Upserting Legal Documents with Dense + Sparse BM25 Vectors...")
  await vector_store.upsert_legal_documents(CORPUS_SEED)
  print("[SUCCESS] Legal Corpus successfully indexed into Qdrant!")



if __name__ == "__main__":
  asyncio.run(main())