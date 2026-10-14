"""Cross-checks for parsed Fandom API data. Writes check_*.csv into fandom_api/."""
import re, sys
from pathlib import Path
import pandas as pd

XLSX, D = sys.argv[1], Path(sys.argv[2])
P = pd.read_csv(D / "fandom_api_products.csv")
R = pd.read_csv(D / "fandom_api_recipes.csv")
U = pd.read_csv(D / "fandom_api_usage.csv")
fa = pd.read_excel(XLSX, sheet_name="fandom_all")
mc = pd.read_excel(XLSX, sheet_name="merged_clean")

def norm(s):
    s = re.sub(r"[​-‏⁠﻿]", "", str(s))
    return re.sub(r"\s+", " ", s).strip().lower()

# map requested names / redirects -> page title
alias = {norm(a): t for a, t in zip(P["Requested as"], P["Page title"])} | {norm(t): t for t in P["Page title"]}

# 1) recipe (product page) vs usage (ingredient page)
r = R.assign(p=R.Product.map(norm), i=R.Ingredient.map(lambda x: norm(alias.get(norm(x), x))))
u = U.assign(p=U.Product.map(lambda x: norm(alias.get(norm(x), x))), i=U.Ingredient.map(norm))
x = r.merge(u, on=["p", "i"], how="outer", suffixes=("_recipe", "_usage"), indicator=True)
bad = x[(x._merge != "both") | (x.Qty_recipe != x.Qty_usage)]
# usage-only rows whose product page we never fetched aren't conflicts, just unknown
known = set(r.p)
bad = bad[~((bad._merge == "right_only") & ~bad.p.isin(known))]
bad[["p", "i", "Qty_recipe", "Qty_usage", "_merge"]].to_csv(D / "check_recipe_vs_usage.csv", index=False)
print(f"1) recipe vs usage: {(x._merge=='both').sum()} pairs agree-on-existence, {len(bad)} disagreements")
print(bad[["p", "i", "Qty_recipe", "Qty_usage", "_merge"]].to_string())

# 2) API infobox vs hand-transcribed fandom_all
p = P.assign(k=P["Page title"].map(norm))
fa["k"] = fa.Product.map(lambda s: norm(alias.get(norm(s), s)))
y = fa.merge(p, on="k", how="left", suffixes=("_hand", "_api"))
rows = []
for _, z in y.iterrows():
    if pd.isna(z["Page title"]):
        rows.append({"Product": z.Product, "field": "NOT FOUND in API", "hand": None, "api": None}); continue
    for hf, af in [("Level_hand", "Level_api"), ("Time normal (min)_hand", "Time normal (min)_api"),
                   ("Time mastered (min)_hand", "Time mastered (min)_api"), ("Sell price", "Sell price max"),
                   ("XP_hand", "XP_api")]:
        a, b = z[hf], z[af]
        if pd.isna(a) and pd.isna(b): continue
        if pd.isna(a) or pd.isna(b) or abs(float(a) - float(b)) > 0.01:
            rows.append({"Product": z.Product, "field": hf.replace("_hand", ""), "hand": a, "api": b})
c2 = pd.DataFrame(rows); c2.to_csv(D / "check_hand_vs_api.csv", index=False)
print(f"\n2) fandom_all (hand, {len(fa)} rows) vs API: {len(c2)} diffs"); print(c2.field.value_counts().to_string())

# 3) coverage of merged_clean
mc["k"] = mc.Product.map(lambda s: norm(alias.get(norm(s), s)))
miss = mc[~mc.k.isin(set(p.k))]
print(f"\n3) merged_clean rows with no Fandom page: {len(miss)}"); print(miss[["Product", "Machine"]].to_string())
extra = p[~p.k.isin(set(mc.k))]
print(f"\n   Fandom product pages not in merged_clean: {len(extra)}"); print(extra[["Page title", "Kind", "Made in / from", "Level"]].to_string())
