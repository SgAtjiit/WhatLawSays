import asyncio
import json
import os
import time
from src.core.vector_store import vector_store
from src.schemas.corpus import LegalSectionDoc


async def main():
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    corpus_files = ["constitution.json", "bsa.json", "bns.json", "bnss.json"]

    all_documents = []

    print("[+] Loading Full Legal Corpus Datasets (Constitution, BSA, BNS, BNSS)...")
    start_time = time.time()

    for fname in corpus_files:
        fpath = os.path.join(data_dir, fname)
        if not os.path.exists(fpath):
            print(f"  [!] Warning: File {fname} not found in data directory!")
            continue

        with open(fpath, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        docs = [LegalSectionDoc(**item) for item in raw_data]
        all_documents.extend(docs)
        print(f"  [+] Loaded {len(docs)} sections from [{fname}]", flush=True)

    print(f"[+] Total Legal Sections Loaded: {len(all_documents)}", flush=True)

    print("[+] Initializing Qdrant Collection with Hybrid Vector Schemas (Dense Cosine + Sparse BM25)...", flush=True)
    await vector_store.setup_collection()

    print(f"[+] Upserting {len(all_documents)} Legal Documents into Qdrant Vector Store...", flush=True)
    await vector_store.upsert_legal_documents(all_documents, batch_size=64)

    elapsed = time.time() - start_time
    print(f"\n[SUCCESS] Successfully indexed all {len(all_documents)} legal sections into Qdrant Vector Database in {elapsed:.2f} seconds!", flush=True)


if __name__ == "__main__":
    asyncio.run(main())