"""Copy hayday_merged_clean.xlsx -> hayday_merged_v2.xlsx and add Fandom API sheets + notes.
Existing sheets (and their formulas) are left untouched."""
import json, re, sys
from pathlib import Path
import openpyxl
from openpyxl.styles import Font
import pandas as pd

SRC, DST, D, HI = sys.argv[1], sys.argv[2], Path(sys.argv[3]), sys.argv[4]
norm = lambda s: re.sub(r"\s+", " ", re.sub(r"[​-‏⁠﻿]", "", str(s))).strip().lower()

P = pd.read_csv(D / "fandom_api_products.csv")
M = pd.read_csv(D / "fandom_api_machine_lists.csv")
R = pd.read_csv(D / "fandom_api_recipes.csv")
CU = pd.read_csv(D / "check_recipe_vs_usage.csv")
CH = pd.read_csv(D / "check_hand_vs_api.csv")
H = pd.DataFrame(json.load(open(HI)))

# 4-way comparison for value diffs (hand value present)
fmap = {"Level": ("Level", "Level", "level"), "Sell price": ("Sell price max", "Sell price", "price"),
        "XP": ("XP", "XP", "xp"), "Time normal (min)": ("Time normal (min)", "Time normal (min)", "time_min"),
        "Time mastered (min)": ("Time mastered (min)", None, "time_min")}
for d, col in [(P, "Page title"), (M, "Product"), (H, "product")]:
    d["_k"] = d[col].map(norm)
rows = []
for _, r in CH.iterrows():
    if r.field not in fmap:
        rows.append([r.Product, r.field, None, None, None, None, "not on Fandom under this name"]); continue
    k = norm(r.Product); a, b, h = fmap[r.field]
    ib, ml, hi = P[P._k == k], M[M._k == k], H[H._k == k]
    v_ib = ib[a].iloc[0] if len(ib) else None
    v_ml = ml[b].iloc[0] if (b and len(ml)) else None
    v_hi = hi[h].iloc[0] if len(hi) else None
    if pd.isna(r.hand):
        verdict = "hand sheet blank; API fills it"
    elif pd.notna(v_ml) and v_ib != v_ml:
        verdict = "Fandom inconsistent (infobox vs machine table)"
    elif v_hi is not None and r.hand == v_hi:
        verdict = "hand value = hayday.info, not Fandom (transcription mix-up)"
    else:
        verdict = "hand transcription error"
    rows.append([r.Product, r.field, r.hand, v_ib, v_ml, v_hi, verdict])
C4 = pd.DataFrame(rows, columns=["Product", "Field", "fandom_all (hand)", "Fandom infobox (API)",
                                 "Fandom machine table (API)", "hayday.info", "Verdict"])

sheets = {
    "fandom_api_products": P.drop(columns="_k"),
    "fandom_api_machine_lists": M.drop(columns="_k"),
    "recipes": R,
    "check_hand_vs_api": C4,
    "check_recipe_vs_usage": CU.rename(columns={"p": "Product", "i": "Ingredient",
                                               "Qty_recipe": "Qty (product page)", "Qty_usage": "Qty (ingredient page)",
                                               "_merge": "Found on"}),
}
wb = openpyxl.load_workbook(SRC)
for name, df in sheets.items():
    if name in wb.sheetnames:
        del wb[name]
    ws = wb.create_sheet(name)
    ws.append(list(df.columns))
    for c in ws[1]:
        c.font = Font(bold=True)
    for row in df.itertuples(index=False):
        ws.append([None if (isinstance(v, float) and pd.isna(v)) else v for v in row])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = min(45, max(10, max(len(str(c.value or "")) for c in col[:200]) + 2))

n = wb["Notes"]
n.append([])
n.append(["Fandom API pull (2026-10-13)"]); n.cell(n.max_row, 1).font = Font(bold=True)
for k, v in [
    ("Method", "MediaWiki API (action=query&prop=revisions, 50 titles/request) on hayday.fandom.com; raw wikitext cached in raw/fandom/pages.json. Scripts: scripts/fetch_fandom.py, parse_fandom.py, check_fandom.py, build_v2.py."),
    ("Product values", "fandom_api_products = Infobox on each product page (level, 'price = 1 to N' -> N, time, time3 = mastered time, xp, source). Icon file = first [[File:]] on the page."),
    ("Machine tables", "fandom_api_machine_lists = {{Building Products}} rows on machine pages (name|level|time|price[/xp]). Includes the 6 pages that failed before (BBQ Grill, Salad Bar, Deep Fryer, Cupcake Maker, Fudge Shop, Bath Kiosk)."),
    ("Recipes", "recipes = 'Making ...' table on each product page (ingredient icon row + xN row). Cross-checked against {{Item Usage}} on each ingredient page (check_recipe_vs_usage): 877 pairs agree; most disagreements are ingredient pages that omit a product, true qty conflicts: Tofu Dog (tomato 4 vs 2), Mint Fudge (cabbage vs butter)."),
    ("Hand sheet reliability", "check_hand_vs_api: fandom_all (hand) disagrees with the API in 24 cells. Several hand values equal hayday.info instead of Fandom, so fandom_all - and the Status/conflict columns in merged_clean built from it - should not be trusted. Use fandom_api_* instead."),
    ("Fandom self-conflicts", "Infobox and machine table disagree for some products (e.g. Affogato XP, Iron Bracelet XP, Hummus Wrap time, Tea Pot time). Both values kept; unresolved."),
    ("Name aliases", "hayday.info 'Coffee' (Trees & Bushes) = Fandom 'Coffee Bean' (assumed from machine; not verified). 40 Fandom products (lamb, mussel, asparagus, mine ores, etc.) are not in hayday.info."),
    ("Ingredient cost / max price", "'Ingredient cost (Fandom text)' and 'Max price per 10' are parsed from the page prose ('Buying the ingredients ... costs N'); prose may be outdated."),
]:
    n.append([k, v])
wb.save(DST)
print("saved", DST, "| verdicts:"); print(C4.Verdict.value_counts().to_string())
