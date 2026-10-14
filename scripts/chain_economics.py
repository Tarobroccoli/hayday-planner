"""Per-product production economics over the full ingredient chain (step 1 of the planner).

For 1 unit of every product: resource-minutes by type (machine / field / animal / tree), total chain
minutes, critical path (wall-clock, assuming enough fields/animals in parallel and one machine of each
kind), ingredient market value, and coins-per-hour metrics. Normal and mastered (machine) times.

Inputs: fandom_api/fandom_api_products.csv, fandom_api_recipes.csv, raw hayday.info JSON,
verified_in_game.csv. Output: CSV (argv[4]).
"""
import math, sys
from pathlib import Path
from functools import lru_cache
import pandas as pd

D, HI, VER, OUT = sys.argv[1:5]
PLAYER_LEVEL = int(sys.argv[5]) if len(sys.argv) > 5 else None

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hdata
from hdata import BATCH, FEED, NO_FEED_ANIMAL, TREE_FRUIT_PER_HARVEST, hi, prod, recipe, price, kind, t_of

missing = hdata.load(D, HI, VER)
if missing: print("ingredients without a product page:", missing)

def add(a, b, k=1.0):
    for key, v in b.items(): a[key] = a.get(key, 0.0) + k * v

@lru_cache(None)
def resources(p, mastered):
    """resource-minutes per 1 unit: {'machine:Bakery': .., 'field': .., 'animal:Egg': .., 'tree:Apple': .., 'external:Gold Ore': units}"""
    k, out = kind(p), {}
    if k == "external": return (("external:" + p, 1.0),)
    if k == "field": return (("field", t_of(p, False)),)
    if k == "tree": return (("tree:" + p, t_of(p, False) / TREE_FRUIT_PER_HARVEST),)
    if k == "animal":
        out["animal:" + p] = t_of(p, False)
        if p in FEED:
            add(out, dict(resources(FEED[p], mastered)))
        return tuple(out.items())
    y = BATCH.get(p, 1)
    out["machine:" + prod[p]["Made in / from"]] = t_of(p, mastered) / y
    for i, q in recipe.get(p, []):
        if i in prod: add(out, dict(resources(i, mastered)), q / y)
    return tuple(out.items())

@lru_cache(None)
def critical(p, n, mastered):
    """wall-clock minutes to have n units of p, starting from empty barn/silo."""
    k = kind(p)
    if k == "external": return 0.0
    if k in ("field", "tree"): return t_of(p, False)   # enough fields/trees in parallel
    if k == "animal": return (critical(FEED[p], n, mastered) if p in FEED else 0.0) + t_of(p, False)
    y = BATCH.get(p, 1); batches = math.ceil(n / y); T = t_of(p, mastered)
    need = max((critical(i, math.ceil(q * batches), mastered) for i, q in recipe.get(p, []) if i in prod), default=0.0)
    return need + batches * T   # one machine: batches run back to back once ingredients are in

rows = []
for p, r in prod.items():
    pr, psrc = price(p)
    k = kind(p)
    ing_val = sum(q * (price(i)[0] or 0) for i, q in recipe.get(p, [])) / BATCH.get(p, 1) if k == "machine" else 0.0
    if k == "animal" and p in FEED:
        ing_val = (price(FEED[p])[0] or 0)
    row = {"Product": p, "Type": k, "Machine / source": r["Made in / from"], "Level": r["Level"],
           "Price": pr, "Price source": psrc, "Yield per batch": BATCH.get(p, 1),
           "Own time (min)": t_of(p, False), "Own time mastered (min)": t_of(p, True) if k == "machine" else None,
           "Ingredient value (coins)": round(ing_val, 2)}
    for tag, m in (("", False), (" mastered", True)):
        res = dict(resources(p, m))
        mach = sum(v for key, v in res.items() if key.startswith("machine:"))
        fld = res.get("field", 0.0)
        ani = sum(v for key, v in res.items() if key.startswith("animal:"))
        tre = sum(v for key, v in res.items() if key.startswith("tree:"))
        tot = mach + fld + ani + tre
        row[f"Machine-min{tag}"] = round(mach, 2)
        if not tag:
            row["Field-min"] = round(fld, 2); row["Animal-min"] = round(ani, 2); row["Tree-min"] = round(tre, 2)
            ext = [key[9:] for key in res if key.startswith("external:")]
            row["External inputs (time not modelled)"] = "; ".join(f"{e} x{res['external:' + e]:g}" for e in ext)
        row[f"Total chain min{tag}"] = round(tot, 2)
        row[f"Critical path min{tag}"] = round(critical(p, 1, m), 2)
        row[f"Coins/hr per chain-min{tag}"] = round(pr / tot * 60, 2) if pr and tot else None
    own = row["Own time (min)"] / BATCH.get(p, 1)
    own_m = (row["Own time mastered (min)"] or row["Own time (min)"]) / BATCH.get(p, 1)
    row["Value added (coins)"] = round(pr - ing_val, 2) if pr is not None else None
    row["Value added/hr own machine"] = round((pr - ing_val) / own * 60, 2) if pr is not None and own else None
    row["Value added/hr own machine mastered"] = round((pr - ing_val) / own_m * 60, 2) if pr is not None and own_m else None
    h = hi.get(p)
    row["hayday.info profit/hr"] = round(h["profit_per_hour"], 2) if h else None
    row["Ingredients"] = "; ".join(f"{i} x{q:g}" for i, q in recipe.get(p, [])) or (f"{FEED[p]} x1" if p in FEED else "")
    if PLAYER_LEVEL is not None:
        lv = lambda x: prod[x]["Level"] if pd.notna(prod[x]["Level"]) else 10**6  # unknown level = not unlocked
        def chain_ok(x):
            return lv(x) <= PLAYER_LEVEL and all(chain_ok(i) for i, _ in recipe.get(x, []) if i in prod) \
                   and (x not in FEED or chain_ok(FEED[x]))
        row[f"Unlocked at L{PLAYER_LEVEL} (whole chain)"] = chain_ok(p)
    rows.append(row)

df = pd.DataFrame(rows)

# Cross-check own-step value added/hr against hayday.info profit_per_hour (site formula =
# (price - ingredient value) / hours; it uses unrounded mastered time = normal x 0.85, or normal time).
def check(r):
    site = r["hayday.info profit/hr"]
    if pd.isna(site) or r["Type"] != "machine" or r["Price"] is None:
        return ""
    per = r["Own time (min)"] / r["Yield per batch"]
    for label, t in (("match (mastered)", (r["Own time mastered (min)"] or r["Own time (min)"]) / r["Yield per batch"]),
                     ("match (normal x0.85)", per * 0.85), ("match (site uses normal time)", per)):
        if t and abs(r["Value added (coins)"] / t * 60 - site) <= 0.6:
            return label
    return "differs - check recipe / ingredient prices"
df["Check vs hayday.info"] = df.apply(check, axis=1)
df = df.sort_values("Coins/hr per chain-min", ascending=False)
print(df["Check vs hayday.info"].value_counts().to_string())
df.to_csv(OUT, index=False)
print(df.Type.value_counts().to_string())
