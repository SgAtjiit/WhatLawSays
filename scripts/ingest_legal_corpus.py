import asyncio
import json
import os
import time
from src.core.vector_store import vector_store
from src.schemas.corpus import LegalSectionDoc, is_dead_law


async def main():
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    corpus_files = [
        "constitution.json",
        "bsa.json",
        "bns.json",
        "bnss.json",
        "it_act.json",
        "posh_act.json",
        # Civil pool, used by contract review only (see CONTRACT_ACTS).
        "contract_act.json",
        "specific_relief_act.json",
        "arbitration_act.json",
        "consumer_protection_act.json",
        "dpdp_act.json",
        "transfer_of_property_act.json",
    ]

    all_documents = []

    print("[+] Loading Full Legal Corpus Datasets (Constitution, BSA, BNS, BNSS, IT Act, POSH Act + civil/contract pool)...")
    start_time = time.time()

    for fname in corpus_files:
        fpath = os.path.join(data_dir, fname)
        if not os.path.exists(fpath):
            print(f"  [!] Warning: File {fname} not found in data directory!")
            continue

        with open(fpath, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        docs = [LegalSectionDoc(**item) for item in raw_data]
        # Belt and braces over the data files: an omitted Article indexed as
        # live law is returned at rank 1 for its own title.
        live = [d for d in docs if not is_dead_law(d.act, d.section_number, d.title, d.content)]
        if len(live) != len(docs):
            print(f"  [!] Skipping {len(docs) - len(live)} repealed/omitted sections in [{fname}]", flush=True)
        all_documents.extend(live)
        print(f"  [+] Loaded {len(live)} sections from [{fname}]", flush=True)

    print(f"[+] Total Legal Sections Loaded: {len(all_documents)}", flush=True)

    # Point ids are derived from act + section, so a rebuild is idempotent. The
    # collection is recreated so that points from a previous ingest which are no
    # longer in the corpus (or were written under the old positional id scheme)
    # do not linger as duplicates.
    print("[+] Rebuilding Qdrant Collection with Hybrid Vector Schemas (Dense Cosine + Sparse BM25)...", flush=True)
    await vector_store.recreate_collection()

    print(f"[+] Upserting {len(all_documents)} Legal Documents into Qdrant Vector Store...", flush=True)
    await vector_store.upsert_legal_documents(all_documents, batch_size=64)

    elapsed = time.time() - start_time
    print(f"\n[SUCCESS] Successfully indexed all {len(all_documents)} legal sections into Qdrant Vector Database in {elapsed:.2f} seconds!", flush=True)


if __name__ == "__main__":
    asyncio.run(main())