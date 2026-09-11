"""Fetch an Act's sections from the India Code REST API into the corpus schema.

India Code (indiacode.gov.in) is the Government of India's official legislative
repository, running DSpace 9. Every section of a central Act is indexed as its
own item carrying the verbatim statutory text in
`dc.identifier.section_page_note`.

Statutory text is copied verbatim and never paraphrased: for a retrieval system
whose whole architecture exists to prevent legal hallucination, generated
section text would poison the corpus at its source.

Usage:
    uv run python scripts/fetch_indiacode_act.py <act_id> <short_tag> <out.json>
"""

import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request

SEARCH_URL = "https://indiacode.gov.in/server/api/discover/search/objects"
PAGE_SIZE = 100

# India Code marks a provision that has been omitted or struck down by titling it
# "[Omitted.]" while still printing the original text in the body. IT Act s.66A
# (struck down in Shreya Singhal v. Union of India) is the clearest example.
# These are not enforceable law and must not enter a legal-advice corpus.
OMITTED_TITLE = re.compile(r"^\[?\s*omitted\s*\.?\s*\]?\s*\.?$", re.I)

# Punishment clauses are captured verbatim from the section text -- never
# composed -- so the worst failure mode is a truncation, not an invention.
PUNISHMENT = re.compile(
    r"((?:shall be punish\w*|shall also be liable|punishable)\s.{0,400}?\.)(?=\s+[A-Z(]|\s*$)",
    re.I | re.S,
)


def fetch(url, attempts=4):
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "whatlawsays-corpus-ingest/1.0"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(2 * (attempt + 1))


def meta(item, key, default=None):
    values = item.get("metadata", {}).get(key)
    return values[0].get("value") if values else default


def clean(raw):
    """Strip the source's presentation markup without altering the wording."""
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def harvest(act_id):
    items, page = [], 0
    while True:
        query = urllib.parse.urlencode(
            {"query": f'act_id:"{act_id}"', "size": PAGE_SIZE, "page": page}
        )
        payload = fetch(f"{SEARCH_URL}?{query}")
        result = payload["_embedded"]["searchResult"]
        items.extend(
            obj["_embedded"]["indexableObject"]
            for obj in result["_embedded"]["objects"]
        )
        page += 1
        total_pages = result["page"]["totalPages"]
        print(f"  page {page}/{total_pages} ({len(items)} items)", flush=True)
        if page >= total_pages:
            return items


def to_corpus_docs(items, short_tag):
    docs, omitted, act_name = [], [], None

    sections = [i for i in items if meta(i, "dc.identifier.collection") == "SECTION"]
    for item in sections:
        title = (meta(item, "dc.title") or "").strip()
        number = (meta(item, "dc.identifier.section_number") or "").strip()
        act_name = act_name or meta(item, "dc.identifier.act_name")

        if OMITTED_TITLE.match(title):
            omitted.append(number)
            continue

        content = clean(meta(item, "dc.identifier.section_page_note"))
        if not content:
            omitted.append(f"{number} (no text)")
            continue

        punishment_match = PUNISHMENT.search(content)
        docs.append(
            {
                "act": f"{meta(item, 'dc.identifier.act_name')} ({short_tag})",
                # India Code exposes no chapter grouping for these Acts. Stating
                # that is preferable to reconstructing chapter headings, which
                # would be unsourced.
                "chapter": "(Chapter not specified in India Code source)",
                "section_number": f"Section {number}",
                "title": title.rstrip("."),
                "content": content,
                "elements": [],
                "punishment": punishment_match.group(1).strip() if punishment_match else None,
                # Cognizability and bailability are not stated in the section
                # text and are left unset rather than inferred.
                "bailable": None,
                "cognizable": None,
                "source_url": meta(item, "dc.identifier.uri"),
                "order_number": int(meta(item, "dc.identifier.order_number") or 0),
            }
        )

    docs.sort(key=lambda d: d["order_number"])
    for doc in docs:
        doc.pop("order_number")
    return docs, omitted, act_name


def main():
    act_id, short_tag, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    print(f"[+] Harvesting {short_tag} ({act_id}) from India Code...", flush=True)
    items = harvest(act_id)

    docs, omitted, act_name = to_corpus_docs(items, short_tag)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(docs, handle, ensure_ascii=False, indent=1)

    with_punishment = sum(1 for d in docs if d["punishment"])
    print(f"\n[+] Act: {act_name}")
    print(f"[+] Retained {len(docs)} sections -> {out_path}")
    print(f"[+] Punishment clause extracted for {with_punishment}/{len(docs)}")
    print(f"[!] Excluded {len(omitted)} omitted/empty sections: {', '.join(omitted)}")


if __name__ == "__main__":
    main()
