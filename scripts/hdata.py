"""Shared Hay Day data + modelling assumptions for chain_economics.py and planner.py.

Call load(fandom_dir, hayday_info_json, verified_csv) once; then use prod, recipe, price(), kind(), t_of().
"""
import json, re
import pandas as pd

# --- assumptions (also written to Notes) ---
BATCH = {"Chicken Feed": 3, "Cow Feed": 3, "Pig Feed": 3, "Sheep Feed": 3, "Goat Feed": 3, "Lamb Feed": 3}
FEED = {"Egg": "Chicken Feed", "Milk": "Cow Feed", "Bacon": "Pig Feed", "Wool": "Sheep Feed",
        "Goat Milk": "Goat Feed", "Lamb Chop": "Lamb Feed"}
TREE_FRUIT_PER_HARVEST = 3  # wiki: harvests give 2, 3, 4 (+4 if revived); 3 = no-revive average
EXTERNAL = {"Mine", "Fish", "Lobster", "Duck", "Closed Mussel", "Squirrel"}  # need tools/lures/nets: not modelled
NO_FEED_ANIMAL = {"Honeycomb"}  # beehive: produces on a timer, no feed

norm = lambda s: re.sub(r"\s+", " ", re.sub(r"[​-‏⁠﻿]", "", str(s))).strip().lower()
prod, recipe, hi, alias = {}, {}, {}, {}
P = R = H = V = None

def canon(s):
    return alias.get(norm(s), s)

def load(D, HI, VER):
    global P, R, H, V
    P = pd.read_csv(f"{D}/fandom_api_products.csv")
    R = pd.read_csv(f"{D}/fandom_api_recipes.csv")
    H = pd.DataFrame(json.load(open(HI)))
    V = pd.read_csv(VER)

    alias.update({norm(a): t for a, t in zip(P["Requested as"], P["Page title"])} | {norm(t): t for t in P["Page title"]})
    alias["coffee"] = "Coffee Bean"
    prod.update({r["Page title"]: r for r in P.to_dict("records")})
    for r in R.to_dict("records"):
        recipe.setdefault(r["Product"], []).append((canon(r["Ingredient"]), r["Qty"]))
    hi.update({canon(r["product"]): r for r in H.to_dict("records")})

    # cycle check
    state = {}
    def visit(p, path):
        if state.get(p) == 1: raise RuntimeError("cycle: " + " -> ".join(path + [p]))
        if state.get(p) == 2: return
        state[p] = 1
        for i, _ in recipe.get(p, []): visit(i, path + [p])
        state[p] = 2
    for p in prod: visit(p, [])

    missing = sorted({i for v in recipe.values() for i, _ in v if i not in prod})

    return missing

def price(p):
    v = V[(V.Product.map(canon) == p) & V.Field.str.startswith("Sell price")]
    if len(v):
        return float(v.Value.iloc[-1]), "in game"
    if p in hi:
        return float(hi[p]["price"]), "hayday.info"
    sp = prod.get(p, {}).get("Sell price max")
    return (float(sp), "Fandom") if pd.notna(sp) else (None, "")

def kind(p):
    r = prod[p]; src = r["Made in / from"]
    if src in EXTERNAL: return "external"
    if p in FEED or p in NO_FEED_ANIMAL: return "animal"
    if r["Kind"] == "Crop": return "field" if src == "Farm" else "tree"
    return "machine"

def t_of(p, mastered):
    r = prod[p]
    if mastered and pd.notna(r["Time mastered (min)"]):
        return float(r["Time mastered (min)"])
    return float(r["Time normal (min)"]) if pd.notna(r["Time normal (min)"]) else 0.0

