"""Parse cached Fandom wikitext (raw/fandom/pages.json) into tidy CSVs.

Outputs (in OUT_DIR):
  fandom_api_products.csv   one row per product page (infobox values + icon file)
  fandom_api_recipes.csv    product -> ingredient, qty (from the 'Making ...' table on the product page)
  fandom_api_usage.csv      ingredient -> product, qty (from {{Item Usage}} on the ingredient page)
  fandom_api_machine_lists.csv  rows of {{Building Products}} on machine pages
"""
import json, re, sys
from pathlib import Path
import pandas as pd

PAGES, OUT = Path(sys.argv[1]), Path(sys.argv[2])
c = json.loads(PAGES.read_text())
URL = "https://hayday.fandom.com/wiki/"

def minutes(s):
    """'1 h 50 m', '5 min', '16 h', '45m', '1d 2h', '30 s' -> minutes (float)."""
    if not s:
        return None
    s = s.lower().replace(",", "")
    tot, hit = 0.0, False
    for n, u in re.findall(r"(\d+(?:\.\d+)?)\s*(days?|d|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b", s):
        hit = True
        n = float(n)
        tot += n * (1440 if u[0] == "d" else 60 if u[0] == "h" else 1 / 60 if u[0] == "s" else 1)
    return round(tot, 2) if hit else None

def num(s):
    m = re.search(r"\d[\d,]*", s or "")
    return int(m.group().replace(",", "")) if m else None

def strip_markup(s):
    s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", s or "")
    return re.sub(r"\{\{|\}\}", "", s).strip()

def split_top(body):
    """Split template body on '|' that are not inside nested {{ }} or [[ ]]."""
    parts, depth, cur, i = [], 0, "", 0
    while i < len(body):
        two = body[i:i + 2]
        if two in ("{{", "[["):
            depth += 1; cur += two; i += 2; continue
        if two in ("}}", "]]"):
            depth -= 1; cur += two; i += 2; continue
        if body[i] == "|" and depth == 0:
            parts.append(cur); cur = ""
        else:
            cur += body[i]
        i += 1
    return parts + [cur]

def infobox(w):
    start = w.find("{{Infobox")
    if start < 0:
        return None
    depth, i = 0, start
    while i < len(w):
        if w.startswith("{{", i):
            depth += 1; i += 2
        elif w.startswith("}}", i):
            depth -= 1; i += 2
            if depth == 0:
                break
        else:
            i += 1
    d = {}
    for part in split_top(w[start + 2:i - 2])[1:]:
        if "=" in part:
            k, v = part.split("=", 1)
            d[k.strip()] = v.strip()
    return d

def source_name(v):
    """{{Infoicon|x|link=Bakery}} / [[File:Bakery.png|50px|link=Bakery]] / [[File:Bakery.png|50px]] -> 'Bakery'."""
    m = re.search(r"link\s*=\s*([^|}\]]+)", v or "") or re.search(r"\[\[File:([^|\]]+?)\.\w+[|\]]", v or "")
    name = m.group(1).strip() if m else strip_markup(v)
    return name[:1].upper() + name[1:]

def recipe(w):
    """Ingredients table in the 'Making/Producing ...' section: row of [[File:..|link=X]] then row of '''xN'''."""
    sec = re.search(r"===\s*'''\s*(Making|Producing|Creating|Crafting)[^\n]*\n(.*?)(?=\n===|\Z)", w, re.S | re.I)
    if not sec:
        return None
    tab = re.search(r"\{\|(.*?)\n\|\}", sec.group(2), re.S)
    if not tab:
        return None
    rows = re.split(r"\n\|-", tab.group(1))
    ings, qtys = [], []
    for r in rows:
        files = re.findall(r"\[\[File:([^|\]]+)([^\]]*)\]\]", r)
        q = re.findall(r"[x×X]\s*(\d+)", r)
        if files and not ings:
            for f, rest in files:
                link = re.search(r"\|\s*link\s*=\s*([^|\]]+)", rest)
                ings.append(link.group(1).strip() if link else re.sub(r"\.\w+$", "", f).strip())
        elif q and ings and not qtys:
            qtys = [int(x) for x in q]
    if not ings:
        return None
    return list(zip(ings, qtys)) if len(qtys) == len(ings) else [(i, None) for i in ings]

def template_rows(w, name, width, skip=0):
    """Rows of a positional template; `skip` leading positional params (e.g. Item Usage's ingredient name)."""
    out = []
    for block in re.findall(r"\{\{\s*" + name + r"(.*?)\}\}", w, re.S):
        parts = [p.strip() for p in block.split("|")]
        parts = [p for p in parts[1:] if "=" not in p]
        head, parts = parts[:skip], parts[skip:]
        out.append((head, [parts[i:i + width] for i in range(0, len(parts) - width + 1, width)]))
    return out

prods, recs, uses, mlist = [], [], [], []
for req, v in c.items():
    if not v:
        continue
    t, w = v["title"], v["wikitext"]
    for _, rows in template_rows(w, "Building Products", 4):
        for name, lvl, tm, pr in rows:
            price, _, xp = pr.partition("/")
            mlist.append({"Machine page": t, "Product": name, "Level": num(lvl), "Time normal (min)": minutes(tm),
                          "Sell price": num(price), "XP": num(xp)})
    for _, rows in [(h, r) for h, r in template_rows(w, "Item Usage", 3, skip=1)]:
        for name, qty, lvl in rows:
            uses.append({"Ingredient": t, "Product": name, "Qty": num(qty), "Product level": num(lvl)})
    ib = infobox(w)
    if not ib or "Production Buildings" in ib.get("title", ""):
        continue
    icon = re.search(r"\[\[File:([^|\]]+)", w)
    price = ib.get("price", "")
    prods.append({
        "Page title": t, "Requested as": req, "Kind": strip_markup(ib.get("title", "")).rstrip("}"),
        "Level": num(ib.get("level")), "Sell price max": num(price.split("to")[-1]) if price else None,
        "Time normal (min)": minutes(ib.get("time")), "Time mastered (min)": minutes(ib.get("time3")),
        "XP": num(ib.get("xp")), "Made in / from": source_name(ib.get("source")),
        "Base price": num(ib.get("base")), "Diamond price": num(ib.get("dia")),
        "Icon file": icon.group(1).strip() if icon else None,
        "Ingredient cost (Fandom text)": num(cost.group(1)) if (cost := re.search(r"Buying the ingredients[^\n]*?costs?\s*([\d,]+)", w)) else None,
        "Max price per 10 (Fandom text)": num(mx.group(1)) if (mx := re.search(r"maximum price of\s*([\d,]+)[^\n]*?for 10", w)) else None,
        "Raw time": ib.get("time"), "Raw time3": ib.get("time3"), "Raw price": price,
        "Fandom page": URL + t.replace(" ", "_"),
    })
    r = recipe(w)
    for ing, q in (r or []):
        recs.append({"Product": t, "Ingredient": ing, "Qty": q, "Source": "Fandom product page (Making table)",
                     "Fandom page": URL + t.replace(" ", "_")})

P = pd.DataFrame(prods).drop_duplicates("Page title")
R = pd.DataFrame(recs).drop_duplicates()
U = pd.DataFrame(uses).drop_duplicates()
M = pd.DataFrame(mlist).drop_duplicates()
for name, d in [("products", P), ("recipes", R), ("usage", U), ("machine_lists", M)]:
    d.to_csv(OUT / f"fandom_api_{name}.csv", index=False)
    print(name, d.shape)
noR = P[~P["Page title"].isin(R["Product"])]
print("product pages with no recipe:", len(noR)); print(noR.groupby("Kind").size().to_string())
print(noR[noR["Kind"].str.contains("roduct")]["Page title"].tolist())
print("recipes missing qty:", R["Qty"].isna().sum(), R[R["Qty"].isna()]["Product"].unique().tolist())
print("unparsed times:", P[P["Time normal (min)"].isna()][["Page title", "Raw time"]].to_string())
