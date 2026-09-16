"""Find an Act's India Code `act_id` by searching for its name.

`fetch_indiacode_act.py` harvests by `act_id`, an opaque token such as
`AC_CEN_3_20_00035_187209_1523268996428`. That token is not published anywhere
browsable, so without this script the only way to obtain one is to hand-inspect
raw API metadata. Every Act in the corpus is sourced through these two scripts,
so the lookup belongs in the repo rather than in a shell history.

Usage:
    uv run python scripts/find_indiacode_act.py "Indian Contract Act"
"""

import json
import sys
import urllib.parse
import urllib.request
from collections import Counter

SEARCH_URL = "https://indiacode.gov.in/server/api/discover/search/objects"
PAGE_SIZE = 100


def fetch(url):
    request = urllib.request.Request(
        url, headers={"User-Agent": "whatlawsays-corpus-ingest/1.0"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def meta(item, key, default=None):
    values = item.get("metadata", {}).get(key)
    return values[0].get("value") if values else default


def main():
    name = sys.argv[1]
    query = urllib.parse.urlencode({"query": f'"{name}"', "size": PAGE_SIZE})
    payload = fetch(f"{SEARCH_URL}?{query}")
    result = payload["_embedded"]["searchResult"]

    # Group the hits by the Act they belong to. A name fragment matches
    # amendment and repealing Acts as well as the principal Act, so the section
    # count is what distinguishes the real target from the noise.
    acts = Counter()
    details = {}
    for obj in result["_embedded"]["objects"]:
        item = obj["_embedded"]["indexableObject"]
        act_id = meta(item, "dc.identifier.act_id")
        if not act_id:
            continue
        acts[act_id] += 1
        # An ACT-level hit carries no act_name and used to overwrite the name a
        # SECTION hit had already supplied, so the principal Act printed as
        # "None (Act 47 of 1963)" while a state copy printed in full.
        info = {
            "act_name": meta(item, "dc.identifier.act_name"),
            "year": meta(item, "dc.date.act_year"),
            "number": meta(item, "dc.identifier.act_number"),
            "repealed": meta(item, "dc.identifier.act_repealed"),
        }
        details.setdefault(act_id, {}).update({k: v for k, v in info.items() if v is not None})

    print(f"[+] {result['page']['totalElements']} total hits for {name!r}")
    print(f"[+] {len(acts)} distinct Acts in the first {PAGE_SIZE}:\n")
    for act_id, hits in acts.most_common():
        info = details[act_id]
        flag = " [REPEALED]" if info.get("repealed") == "true" else ""
        print(f"  {info.get('act_name', '(name not in sample)')} (Act {info.get('number', '?')} of {info.get('year', '?')}){flag}")
        print(f"    act_id   : {act_id}")
        print(f"    hits     : {hits} in sample\n")


if __name__ == "__main__":
    main()
