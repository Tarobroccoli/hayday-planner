"""Hay Day production planner - Mode 1 (resource base): steady-state plan with the most coins/hr.

Linear program over production rates (units/hr) and sales rates (units/hr):
  maximise   sum(price * sold)
  subject to flow       made - used as ingredient - sold >= 0          (per product)
             machine    sum(batch time * batches) <= 60 min/hr        (per machine type)
             slots      batches/hr <= slots * 60 / check-in            (you collect at most `slots` per visit)
             fields     sum(cycle * crops) <= 60 * fields              (cycle = grow time rounded up to visits)
             animals    cycle * goods <= 60 * animals                  (per animal type, 1 feed per good)
             trees      cycle * fruit / fruit-per-harvest <= 60 * trees
             shop       units sold/hr <= shop slots * stack * 60 / max(check-in, sell time)
             storage    units collected per visit <= silo (crops, fruit) / barn (everything else)
Shadow prices of binding constraints = coins/hr gained per extra unit of that resource (the bottlenecks).

Usage: planner.py <fandom_dir> <hayday_info.json> <verified.csv> <farm_profile.json> [--checkin N ...] [--out DIR]
"""
import json, math, sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.optimize import linprog

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hdata
from hdata import BATCH, FEED, TREE_FRUIT_PER_HARVEST, hi, prod, recipe, price, kind, t_of


def unlocked_products(level, allow_external, exclude):
    lv = lambda p: prod[p]["Level"] if pd.notna(prod[p]["Level"]) else 10**6
    memo = {}
    def ok(p):
        if p in memo: return memo[p]
        memo[p] = False  # guard
        good = (p in prod and lv(p) <= level and p not in exclude
                and (allow_external or kind(p) != "external")
                and all(ok(i) for i, _ in recipe.get(p, []))
                and (p not in FEED or ok(FEED[p])))
        memo[p] = good
        return good
    return sorted(p for p in prod if ok(p))


def xp_of(p):
    if p in hi: return float(hi[p]["xp"])
    v = prod[p]["XP"]
    return float(v) if pd.notna(v) else 0.0


def solve(farm, checkin=None, demand=None):
    """demand: {product: units/hr that must be produced and NOT sold to the shop} (Mode 2 hook)."""
    I = float(checkin if checkin is not None else farm["checkin_minutes"])
    cyc = lambda T: math.ceil(T / I - 1e-9) * I if I > 0 else T   # wait for the next visit to collect
    mastered = set(farm.get("mastered", []))
    items = unlocked_products(farm["level"], farm.get("allow_external", False), set(farm.get("exclude", [])))
    n = len(items); ix = {p: k for k, p in enumerate(items)}
    nv = 2 * n                                    # x_0..x_n-1 made, s_0..s_n-1 sold
    rows, rhs, names = [], [], []

    def row():
        return np.zeros(nv)

    # flow: -made + used + sold <= -demand
    for p in items:
        r = row(); r[ix[p]] = -1.0; r[n + ix[p]] = 1.0
        for q in items:
            y = BATCH.get(q, 1)
            for i, qty in recipe.get(q, []):
                if i == p: r[ix[q]] += qty / y
            if FEED.get(q) == p: r[ix[q]] += 1.0
        rows.append(r); rhs.append(-(demand or {}).get(p, 0.0)); names.append(("flow", p))

    # machines
    machines = sorted({prod[p]["Made in / from"] for p in items if kind(p) == "machine"})
    for m in machines:
        cnt = farm.get("machine_count", {}).get(m, farm["machine_count_default"])
        slots = farm.get("machine_slots", {}).get(m, farm["machine_slots_default"])
        rt, rs = row(), row()
        for p in items:
            if kind(p) == "machine" and prod[p]["Made in / from"] == m:
                y = BATCH.get(p, 1)
                rt[ix[p]] = t_of(p, m in mastered) / y
                rs[ix[p]] = 1.0 / y
        rows += [rt, rs]; rhs += [60.0 * cnt, slots * cnt * 60.0 / I]
        names += [("machine", m), ("slots", m)]

    # fields
    r = row()
    for p in items:
        if kind(p) == "field": r[ix[p]] = cyc(t_of(p, False))
    rows.append(r); rhs.append(60.0 * farm["fields"]); names.append(("fields", "fields"))

    # animals, beehives, trees
    for p in items:
        k = kind(p)
        if k == "animal":
            N = farm["beehives"] if p == "Honeycomb" else farm.get("animals", {}).get(p, farm["animals_default"])
            r = row(); r[ix[p]] = cyc(t_of(p, False))
            rows.append(r); rhs.append(60.0 * N); names.append(("animal", p))
        elif k == "tree":
            N = farm.get("trees", {}).get(p, farm["trees_default"])
            r = row(); r[ix[p]] = cyc(t_of(p, False)) / TREE_FRUIT_PER_HARVEST
            rows.append(r); rhs.append(60.0 * N); names.append(("tree", p))

    # storage: what one visit brings in must fit (approximation - ignores stock you keep between visits)
    for cap, kinds_ in (("silo", ("field", "tree")), ("barn", ("machine", "animal"))):
        if farm.get(cap):
            r = row()
            for p in items:
                if kind(p) in kinds_: r[ix[p]] = I / 60.0
            rows.append(r); rhs.append(float(farm[cap])); names.append(("storage", cap))

    # shop throughput
    r = row(); r[n:] = 1.0
    shop_units = farm["shop_slots"] * farm["shop_stack"] * 60.0 / max(I, farm["shop_sell_minutes"])
    rows.append(r); rhs.append(shop_units); names.append(("shop", "shop"))

    c = np.zeros(nv)
    for p in items:
        pr = price(p)[0]
        c[n + ix[p]] = -(pr or 0.0)
        if pr is None: c[n + ix[p]] = 0.0
    res = linprog(c, A_ub=np.array(rows), b_ub=np.array(rhs), bounds=[(0, None)] * nv, method="highs")
    if res.status != 0:
        raise RuntimeError(res.message)
    x, s = res.x[:n], res.x[n:]
    duals = -res.ineqlin.marginals               # coins/hr per unit of rhs
    A = np.array(rows)
    return {"I": I, "items": items, "x": x, "s": s, "revenue": -res.fun, "names": names,
            "duals": duals, "rhs": np.array(rhs), "lhs": A @ res.x, "farm": farm, "cyc": cyc,
            "xp": sum(xp_of(p) * x[ix[p]] for p in items), "ix": ix, "shop_units": shop_units}


def bottlenecks(sol):
    """Binding constraints translated to 'one more X' coins/hr."""
    f, I, out = sol["farm"], sol["I"], []
    for (kind_, name), d, rhs, lhs in zip(sol["names"], sol["duals"], sol["rhs"], sol["lhs"]):
        if d <= 1e-6 or kind_ == "flow":
            continue
        if kind_ == "machine":
            if name in set(f.get("mastered", [])):
                per, what = d * 60, f"{name} full (already mastered): value of 1 more hour of {name} time"
            else:
                per, what = d * lhs * 0.15, f"master {name} (-15% time; first-order estimate)"
        elif kind_ == "storage":
            per, what = d, f"+1 {name} space"
        elif kind_ == "slots":
            per, what = d * 60 / I, f"+1 slot on {name}"
        elif kind_ == "fields":
            per, what = d * 60, "+1 field"
        elif kind_ == "animal":
            per, what = d * 60, f"+1 animal making {name}"
        elif kind_ == "tree":
            per, what = d * 60, f"+1 tree of {name}"
        else:
            per, what = d * f["shop_stack"] * 60 / max(I, f["shop_sell_minutes"]), "+1 roadside shop slot"
        out.append({"Resource": what, "Coins/hr gained": round(per, 1), "Used": round(lhs / rhs * 100) if rhs else None})
    return pd.DataFrame(out).sort_values("Coins/hr gained", ascending=False) if out else pd.DataFrame()


def tables(sol):
    items, x, s, I, cyc, ix = sol["items"], sol["x"], sol["s"], sol["I"], sol["cyc"], sol["ix"]
    rows = []
    for p in items:
        k = ix[p]
        if x[k] < 1e-6 and s[k] < 1e-6:
            continue
        kd = kind(p); y = BATCH.get(p, 1)
        r = {"Product": p, "Type": kd, "Where": prod[p]["Made in / from"] if kd != "field" else "Field",
             "Made/hr": round(x[k], 2), "Sold/hr": round(s[k], 2), "Used as ingredient/hr": round(x[k] - s[k], 2),
             "Coins/hr from sales": round(s[k] * (price(p)[0] or 0), 1),
             "Per visit": round(x[k] * I / 60 / y, 2)}
        if kd == "machine":
            r["Unit"] = "batches" if y > 1 else "items"
        elif kd == "field":
            r["Unit"] = "fields to plant"; r["Per visit"] = round(x[k] * cyc(t_of(p, False)) / 60, 1)
        else:
            r["Unit"] = "items collected"
        rows.append(r)
    plan = pd.DataFrame(rows).sort_values(["Type", "Where", "Product"])
    use = []
    for (kd, name), rhs, lhs in zip(sol["names"], sol["rhs"], sol["lhs"]):
        if kd in ("machine", "slots", "fields", "shop"):
            use.append({"Constraint": kd, "Name": name, "Used %": round(lhs / rhs * 100, 1) if rhs else None})
    return plan, pd.DataFrame(use)


def main():
    args = sys.argv[1:]
    out = Path(args[args.index("--out") + 1]) if "--out" in args else Path("plans")
    checkins = []
    if "--checkin" in args:
        k = args.index("--checkin") + 1
        while k < len(args) and not args[k].startswith("--"):
            checkins.append(float(args[k])); k += 1
    pos = [a for a in args if not a.startswith("--")][:4]
    D, HI, VER, FARM = pos
    missing = hdata.load(D, HI, VER)
    farm = json.load(open(FARM))
    out.mkdir(exist_ok=True)
    summary = []
    for I in checkins or [farm["checkin_minutes"]]:
        sol = solve(farm, I)
        plan, use = tables(sol)
        bn = bottlenecks(sol)
        tag = f"checkin{int(I)}"
        plan.to_csv(out / f"mode1_{tag}_plan.csv", index=False)
        bn.to_csv(out / f"mode1_{tag}_bottlenecks.csv", index=False)
        use.to_csv(out / f"mode1_{tag}_utilisation.csv", index=False)
        top = plan.sort_values("Coins/hr from sales", ascending=False).head(5)
        summary.append({"Check-in (min)": int(I), "Coins/hr": round(sol["revenue"]), "XP/hr": round(sol["xp"]),
                        "Products sold": int((plan["Sold/hr"] > 0).sum()),
                        "Top sellers": ", ".join(f"{p} {v:.0f}" for p, v in zip(top.Product, top["Coins/hr from sales"])),
                        "Main bottleneck": (f"{bn.iloc[0]['Resource']} (+{bn.iloc[0]['Coins/hr gained']}/hr)" if len(bn) else "")})
        print(f"\n=== check-in every {I:g} min: {sol['revenue']:.0f} coins/hr, {sol['xp']:.0f} XP/hr, "
              f"{len(sol['items'])} unlocked products ===")
        print(plan.sort_values("Coins/hr from sales", ascending=False).head(15).to_string(index=False))
        print("bottlenecks:"); print(bn.head(8).to_string(index=False))
    pd.DataFrame(summary).to_csv(out / "mode1_summary.csv", index=False)
    print("\n" + pd.DataFrame(summary).to_string(index=False))


if __name__ == "__main__":
    main()
