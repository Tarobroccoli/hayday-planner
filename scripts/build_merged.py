"""Build sheet 'merged_v2' (hayday.info + Fandom API) into an existing workbook (run after build_v2.py).

Key = product name (case-insensitive, zero-width chars removed, Fandom redirects + ALIAS applied).
Both sources' values are kept side by side; primary Level/Sell price/XP are formulas
(hayday.info first, Fandom if hayday.info has none). Status/Conflict columns are formulas.
"""
import json, re, sys
from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
import pandas as pd

WB, D, HI = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
ALIAS = {"coffee": "coffee bean"}  # hayday.info name -> Fandom page (assumed, see Notes)
MACHINE_FIX = {"Jewler": "Jeweler", "Donut maker": "Donut Maker", "Preservation station": "Preservation Station"}
SMALL = {"and", "di", "of", "with", "a", "the"}

def norm(s):
    s = re.sub(r"[​-‏⁠﻿]", "", str(s))
    return re.sub(r"\s+", " ", s).strip().lower()

def title(s):
    w = norm(s).split(" ")
    return " ".join(x if (i and x in SMALL) else ("BLT" if x == "blt" else x[:1].upper() + x[1:]) for i, x in enumerate(w))

H = pd.DataFrame(json.load(open(HI)))
P = pd.read_csv(D / "fandom_api_products.csv")
M = pd.read_csv(D / "fandom_api_machine_lists.csv")
R = pd.read_csv(D / "fandom_api_recipes.csv")

alias = {norm(a): norm(t) for a, t in zip(P["Requested as"], P["Page title"])} | ALIAS
key = lambda s: alias.get(norm(s), norm(s))
H["k"] = H["product"].map(key); P["k"] = P["Page title"].map(norm); M["k"] = M["Product"].map(key)
assert not H.k.duplicated().any() and not P.k.duplicated().any()

# local icon paths from scripts/fetch_icons.py (optional)
man = D.parent / "icons" / "icon_manifest.csv"
icon_local = dict(zip(pd.read_csv(man).Product, pd.read_csv(man)["Local path"])) if man.exists() else {}

recipe_txt = (R.assign(t=R.Ingredient + " x" + R.Qty.astype(int).astype(str))
              .groupby("Product")["t"].agg("; ".join))
recipe_txt.index = recipe_txt.index.map(norm)

def fandom_machine(r):
    src, kind = r["Made in / from"], r["Kind"]
    if kind == "Crop":
        return "Crops" if src == "Farm" else "Trees & Bushes"
    if kind == "Animal good":
        return "Animal Products"
    return src

def internal_conflict(k, ib):
    ml = M[M.k == k]
    if ml.empty or ib is None:
        return ""
    ml = ml.iloc[0]; out = []
    for f_ml, f_ib, lab in [("Level", "Level", "level"), ("Time normal (min)", "Time normal (min)", "time"),
                            ("Sell price", "Sell price max", "price"), ("XP", "XP", "xp")]:
        a, b = ml[f_ml], ib[f_ib]
        if pd.notna(a) and pd.notna(b) and float(a) != float(b):
            out.append(f"{lab} {a:g} (machine page) vs {b:g} (product page)")
    return "; ".join(out)

rows = []
for k in sorted(set(H.k) | set(P.k)):
    h = H[H.k == k].iloc[0] if (H.k == k).any() else None
    f = P[P.k == k].iloc[0] if (P.k == k).any() else None
    found = "both" if (h is not None and f is not None) else ("hayday.info" if h is not None else "Fandom")
    machine = (MACHINE_FIX.get(h.machine.strip(), h.machine.strip()) if h is not None else fandom_machine(f))
    src = []
    if h is not None: src.append("hayday.info /api/production-data (2026-10-13)")
    if f is not None: src.append("Hay Day Wiki infobox via MediaWiki API (2026-10-13)")
    g = lambda r, c: (None if r is None or pd.isna(r[c]) else r[c])
    rows.append({
        "Product": f["Page title"] if f is not None else title(h["product"]),
        "Machine": machine,
        "Kind (Fandom)": g(f, "Kind"),
        "Level (hayday.info)": g(h, "level"), "Level (Fandom)": g(f, "Level"),
        "Time hayday.info (min)": g(h, "time_min"),
        "Time normal (Fandom, min)": g(f, "Time normal (min)"), "Time mastered (Fandom, min)": g(f, "Time mastered (min)"),
        "Sell price (hayday.info)": g(h, "price"), "Sell price (Fandom)": g(f, "Sell price max"),
        "XP (hayday.info)": g(h, "xp"), "XP (Fandom)": g(f, "XP"),
        "Profit/hr (site)": round(h["profit_per_hour"], 2) if h is not None else None,
        "XP/hr (site)": round(h["xp_per_hour"], 2) if h is not None else None,
        "Found in": found,
        "Fandom internal conflict": internal_conflict(k, f),
        "Ingredients (Fandom)": recipe_txt.get(k, ""),
        "Icon file (Fandom)": g(f, "Icon file"),
        "Source": " + ".join(src),
        "Fandom page": g(f, "Fandom page"),
        "hayday.info name": h["product"].strip() if h is not None else None,
    })
    rows[-1]["Icon (local)"] = icon_local.get(rows[-1]["Product"])
df = pd.DataFrame(rows).sort_values(["Machine", "Level (hayday.info)", "Level (Fandom)", "Product"], na_position="last")

# layout: value columns + formula columns inserted after the values they use
cols = ["Product", "Machine", "Kind (Fandom)",
        "=Level", "Level (hayday.info)", "Level (Fandom)",
        "Time hayday.info (min)", "Time normal (Fandom, min)", "Time mastered (Fandom, min)", "=hayday.info time basis",
        "=Sell price", "Sell price (hayday.info)", "Sell price (Fandom)",
        "=XP", "XP (hayday.info)", "XP (Fandom)",
        "Profit/hr (site)", "XP/hr (site)", "=Flag",
        "Found in", "=Status", "=Conflict fields", "Fandom internal conflict",
        "Ingredients (Fandom)", "Icon file (Fandom)", "Icon (local)", "Source", "Fandom page", "hayday.info name"]
L = {c.lstrip("="): get_column_letter(i + 1) for i, c in enumerate(cols)}

def formula(name, r):
    c = lambda n: f"{L[n]}{r}"
    if name in ("Level", "Sell price", "XP"):
        a, b = c(f"{name} (hayday.info)"), c(f"{name} (Fandom)")
        return f'=IF({a}<>"",{a},IF({b}<>"",{b},""))'
    if name == "hayday.info time basis":
        t, n, m = c("Time hayday.info (min)"), c("Time normal (Fandom, min)"), c("Time mastered (Fandom, min)")
        return f'=IF(OR({t}="",AND({n}="",{m}="")),"n/a",IF({t}={m},"mastered",IF({t}={n},"normal","differs")))'
    if name == "Flag":
        p = c("Profit/hr (site)")
        return f'=IF({p}="","",IF({p}<0,"negative profit",IF({p}>Notes!$B$4,"unusually high - verify","")))'
    if name == "Status":
        return f'=IF({c("Found in")}<>"both",{c("Found in")}&" only",IF({c("Conflict fields")}="","agree","conflict"))'
    if name == "Conflict fields":
        label = {"Level": "level", "Sell price": "price", "XP": "xp"}
        d = lambda n: (f'IF(AND({c(n + " (hayday.info)")}<>"",{c(n + " (Fandom)")}<>"",'
                       f'{c(n + " (hayday.info)")}<>{c(n + " (Fandom)")}),"{label[n]} ","")')
        return (f'=IF({c("Found in")}="both",TRIM({d("Level")}&{d("Sell price")}&{d("XP")}'
                f'&IF({c("hayday.info time basis")}="differs","time","")),"")')
    raise KeyError(name)

wb = openpyxl.load_workbook(WB)
if "merged_v2" in wb.sheetnames:
    del wb["merged_v2"]
ws = wb.create_sheet("merged_v2", 0)
blue, bold = Font(color="FF0000FF"), Font(bold=True)
ws.append([c.lstrip("=") for c in cols])
for i, c in enumerate(cols, 1):
    ws.cell(1, i).font = bold
    if c.startswith("="):
        ws.cell(1, i).fill = PatternFill("solid", fgColor="FFF4E1C1")
for r, rec in enumerate(df.to_dict("records"), start=2):
    for i, c in enumerate(cols, 1):
        if c.startswith("="):
            ws.cell(r, i, formula(c[1:], r))
        else:
            v = rec[c]
            v = None if (v is None or (isinstance(v, float) and pd.isna(v)) or v == "") else v
            if isinstance(v, float) and v.is_integer() and "hr" not in c:
                v = int(v)
            cell = ws.cell(r, i, v)
            if c == "Icon (local)" and v:
                cell.hyperlink = v
            if c not in ("Product", "Machine", "Found in", "Source", "Fandom page", "Fandom internal conflict"):
                cell.font = blue
ws.freeze_panes = "B2"
ws.auto_filter.ref = ws.dimensions
for i, c in enumerate(cols, 1):
    ws.column_dimensions[get_column_letter(i)].width = {"Product": 30, "Ingredients (Fandom)": 50, "Source": 40,
                                                       "Fandom page": 45, "Fandom internal conflict": 40}.get(c.lstrip("="), 14)

n = wb["Notes"]
last = len(df) + 1
rng = lambda name: f"merged_v2!{L[name]}2:{L[name]}{last}"
n.append([])
n.append(["Merged sheet v2 (merged_v2) - replaces merged_clean"]); n.cell(n.max_row, 1).font = bold
for k, v in [
    ("Rows", f"=COUNTA({rng('Product')})"),
    ("  in both sources", f'=COUNTIF({rng("Found in")},"both")'),
    ("  hayday.info only", f'=COUNTIF({rng("Found in")},"hayday.info")'),
    ("  Fandom only", f'=COUNTIF({rng("Found in")},"Fandom")'),
    ("  status = conflict", f'=COUNTIF({rng("Status")},"conflict")'),
    ("  price conflicts", f'=COUNTIF({rng("Conflict fields")},"*price*")'),
    ("  xp conflicts", f'=COUNTIF({rng("Conflict fields")},"*xp*")'),
    ("  level conflicts", f'=COUNTIF({rng("Conflict fields")},"*level*")'),
    ("  time basis = mastered", f'=COUNTIF({rng("hayday.info time basis")},"mastered")'),
    ("  time basis = normal", f'=COUNTIF({rng("hayday.info time basis")},"normal")'),
    ("  time basis = differs", f'=COUNTIF({rng("hayday.info time basis")},"differs")'),
    ("  Fandom internal conflict", f'=COUNTIF({rng("Fandom internal conflict")},"?*")'),
    ("  with ingredients", f'=COUNTIF({rng("Ingredients (Fandom)")},"?*")'),
    ("  with local icon", f'=COUNTIF({rng("Icon (local)")},"?*")'),
    ("Icons", "icons/<Machine>/<Product>.png = 256px-wide PNG thumbnail of the first image on the Fandom product page (CDN scale-to-width-down + format=original). Manifest: icons/icon_manifest.csv. Artwork (c) Supercell, personal reference use only. Lead image assumed to be the item icon - spot-checked via icons/contact_sheet.png."),
    ("Inputs", "hayday.info JSON (verified identical to hayday_info sheet) + fandom_api_products (product-page infobox). fandom_all (hand-typed) is NOT used."),
    ("Primary values", "Level / Sell price / XP columns are formulas: hayday.info if present, else Fandom. Same rule as before (my choice, not verified). Both sources are always shown, not only when different."),
    ("Conflicts", "Conflict fields compares hayday.info vs Fandom infobox for level, price, xp, and time (basis 'differs'). 'Fandom internal conflict' = machine page table disagrees with product page infobox."),
    ("Machine", "hayday.info machine (spelling fixed) if present; for Fandom-only rows: Farm crops -> Crops, tree/bush crops -> Trees & Bushes, animal goods -> Animal Products, else the infobox source."),
    ("Product name", "Fandom page title if the item has a page, else Title Case of the hayday.info name. Original hayday.info name kept in the last column."),
    ("merged_clean", "Kept for history only. Its conflict/Status columns were computed from fandom_all, which contains transcription errors (see check_hand_vs_api)."),
]:
    n.append([k, v])
wb.save(WB)
print(df["Found in"].value_counts().to_string())
print("rows", len(df), "| with internal conflict", (df["Fandom internal conflict"] != "").sum(),
      "| with ingredients", (df["Ingredients (Fandom)"] != "").sum())
