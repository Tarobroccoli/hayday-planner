"""Fetch raw wikitext from the Hay Day Wiki (Fandom) via the MediaWiki API and cache it.

Fetches machine pages, reads product names from their {{Building Products}} template,
then fetches every product page (plus every product name in merged_clean) in batches
of 50 titles per request. Already-cached pages are skipped.

Output: raw/fandom/pages.json  {requested title: {"title": resolved title, "wikitext": ...} | null}
"""
import json, re, sys, time
from pathlib import Path
import pandas as pd
import ssl, urllib.parse, urllib.request

XLSX, OUT = sys.argv[1], Path(sys.argv[2])
API = "https://hayday.fandom.com/api.php"
SSL = ssl.create_default_context(cafile="/etc/ssl/certs/ca-certificates.crt")
UA = {"User-Agent": "Mozilla/5.0 (personal Hay Day data project)"}

def get_json(params):
    url = API + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60, context=SSL) as r:
        return json.load(r)

cache = json.loads(OUT.read_text()) if OUT.exists() else {}

def fetch(titles):
    todo = [t for t in dict.fromkeys(titles) if t not in cache]
    for i in range(0, len(todo), 50):
        chunk = todo[i:i + 50]
        q = get_json({"action": "query", "prop": "revisions", "rvprop": "content",
                      "rvslots": "main", "titles": "|".join(chunk), "redirects": 1,
                      "format": "json", "formatversion": 2})["query"]
        alias = {}
        for k in ("normalized", "redirects"):
            for x in q.get(k, []):
                alias[x["from"]] = x["to"]
        pages = {p["title"]: p for p in q["pages"]}
        for t in chunk:
            final = t
            while final in alias:
                final = alias[final]
            p = pages.get(final)
            if p is None or p.get("missing") or "revisions" not in p:
                cache[t] = None
            else:
                cache[t] = {"title": final, "wikitext": p["revisions"][0]["slots"]["main"]["content"]}
        print(f"  fetched {i + len(chunk)}/{len(todo)}", flush=True)
        OUT.write_text(json.dumps(cache, ensure_ascii=False, indent=0))
        time.sleep(1.5)

m = pd.read_excel(XLSX, sheet_name="merged_clean")
machines = sorted(set(m["Machine"]) | {"Trees and Bushes", "Crops", "Animals", "Products"})
print("machines:", len(machines)); fetch(machines)

BP = re.compile(r"\{\{\s*Building Products(.*?)\}\}", re.S)
products = set(m["Product"])
for t in machines:
    if cache.get(t):
        for block in BP.findall(cache[t]["wikitext"]):
            parts = [p.strip() for p in block.split("|")[1:]]
            products |= {parts[k] for k in range(0, len(parts), 4) if parts[k] and "=" not in parts[k]}
print("product titles:", len(products)); fetch(sorted(products))
print("missing:", sorted(t for t, v in cache.items() if v is None))

# second pass: ingredient pages referenced by parsed recipes (run parse_fandom.py first)
rec = OUT.parent.parent.parent / "fandom_api" / "fandom_api_recipes.csv"
if rec.exists():
    ings = set(pd.read_csv(rec)["Ingredient"])
    print("ingredient titles:", len(ings)); fetch(sorted(ings))
    print("missing:", sorted(t for t, v in cache.items() if v is None))
