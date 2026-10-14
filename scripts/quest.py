"""Hay Day production planner - Mode 2 (quest base): make a fixed order, then spend what is left on coins.

1. BOM     explode the order into everything to make (net of stock you already have), batch-rounded.
2. Schedule visit-by-visit simulation of your farm (slots, fields, animals, trees): what to do at
           each check-in and when the order is ready. Tasks on the longest remaining chain go first.
3. Money   Mode 1 LP with the order as a must-produce rate over the schedule length: coins/hr you
           still earn while doing the order, and the coins the order costs you vs Mode 1.

Assumptions: farm starts empty (fields bare, animals unfed, machines idle, trees just harvested)
except for the stock listed in "have"; trees are ready to harvest ("trees_start": "harvested" for
worst case); seeds are free (a field nets +1 crop); trees give
TREE_FRUIT_PER_HARVEST fruit per harvest.

quest.json: {"name": "...", "items": {"Bread": 3, ...}, "have": {"Wheat": 20, ...},
             "reward_coins": 0, "reward_xp": 0, "trees_start": "ready"}
Usage: quest.py <fandom_dir> <hayday_info.json> <verified.csv> <farm_profile.json> <quest.json>
                [--checkin N] [--out DIR]
"""
import json, math, sys
from collections import defaultdict
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hdata, planner
from hdata import BATCH, FEED, TREE_FRUIT_PER_HARVEST, prod, recipe, price, kind, t_of


def inputs_of(p):
    """Ingredients per start unit (machine batch, animal good, field planting, tree harvest)."""
    if kind(p) == "animal":
        return [(FEED[p], 1)] if p in FEED else []
    return list(recipe.get(p, [])) if kind(p) == "machine" else []


def yield_of(p):
    k = kind(p)
    if k == "machine": return BATCH.get(p, 1)
    if k == "tree": return TREE_FRUIT_PER_HARVEST
    return 1


def topo(roots):
    """Products reachable from roots, every product after all products that use it."""
    order, seen = [], set()
    def visit(p):
        if p in seen: return
        seen.add(p)
        for i, _ in inputs_of(p): visit(i)
        order.append(p)
    for r in roots: visit(r)
    return order[::-1]


def bom(items, have):
    """Returns gross need, units taken from stock, start units to run, units made, spare units."""
    order = topo(items)
    need = defaultdict(float, items)
    stock = defaultdict(float, have)
    from_stock, starts, made = {}, {}, {}
    for p in order:
        take = min(stock[p], need[p]); stock[p] -= take; from_stock[p] = take
        net = need[p] - take
        starts[p] = math.ceil(net / yield_of(p) - 1e-9) if net > 0 else 0
        made[p] = starts[p] * yield_of(p)
        for i, q in inputs_of(p):
            need[i] += q * starts[p]
    spare = {p: made[p] - (need[p] - from_stock[p]) for p in order}
    return order, need, from_stock, starts, made, spare


def tails(order, farm):
    """Minutes from starting p to the order being done along its longest downstream chain."""
    mastered = set(farm.get("mastered", []))
    T = {p: t_of(p, kind(p) == "machine" and prod[p]["Made in / from"] in mastered) for p in order}
    users = defaultdict(list)
    for p in order:
        for i, _ in inputs_of(p): users[i].append(p)
    tail = {}
    for p in order:  # users come before ingredients in `order`
        tail[p] = T[p] + max((tail[u] for u in users[p]), default=0.0)
    return T, tail


def simulate(order, starts, farm, have, I, trees_ready=True, max_visits=2000):
    T, tail = tails(order, farm)
    pri = sorted((p for p in order if starts[p]), key=lambda p: -tail[p])
    stock = defaultdict(float, have)
    rem = dict(starts)
    machines = {}   # machine type -> list of queues; queue = list of (finish, product)
    fields, animals, trees, log = [], defaultdict(list), {}, []
    last_finish = 0.0

    def capacity_error(p, what):
        raise RuntimeError(f"{p}: your farm has no {what} (check farm_profile.json or add it to 'have')")

    for v in range(max_visits):
        t = v * I
        # collect
        for m, qs in machines.items():
            for q in qs:
                for f, p in [x for x in q if x[0] <= t + 1e-9]:
                    stock[p] += yield_of(p); q.remove((f, p))
        for f, p in [x for x in fields if x[0] <= t + 1e-9]:
            stock[p] += 1; fields.remove((f, p))
        for p, busy in animals.items():
            done = [f for f in busy if f <= t + 1e-9]
            stock[p] += len(done); animals[p] = [f for f in busy if f > t + 1e-9]
        # start work, longest remaining chain first
        for p in pri:
            k = kind(p)
            while rem[p] > 0:
                ins = inputs_of(p)
                if any(stock[i] < q - 1e-9 for i, q in ins): break
                if k == "machine":
                    m = prod[p]["Made in / from"]
                    cnt = farm.get("machine_count", {}).get(m, farm["machine_count_default"])
                    slots = farm.get("machine_slots", {}).get(m, farm["machine_slots_default"])
                    if cnt * slots == 0: capacity_error(p, m)
                    qs = machines.setdefault(m, [[] for _ in range(cnt)])
                    free = [q for q in qs if len(q) < slots]
                    if not free: break
                    q = min(free, key=lambda q: max((f for f, _ in q), default=t))
                    f = max(max((f for f, _ in q), default=t), t) + T[p]
                    q.append((f, p)); where, act = m, "start"
                elif k == "field":
                    if farm["fields"] == 0: capacity_error(p, "fields")
                    if len(fields) >= farm["fields"]: break
                    f = t + T[p]; fields.append((f, p)); where, act = "Field", "plant"
                elif k == "animal":
                    N = farm["beehives"] if p == "Honeycomb" else farm.get("animals", {}).get(p, farm["animals_default"])
                    if N == 0: capacity_error(p, f"animals for {p}")
                    if len(animals[p]) >= N: break
                    f = t + T[p]; animals[p].append(f); where, act = prod[p]["Made in / from"], "feed" if ins else "collect later"
                elif k == "tree":
                    N = farm.get("trees", {}).get(p, farm["trees_default"])
                    if N == 0: capacity_error(p, f"{p} trees")
                    nxt = trees.setdefault(p, [0.0 if trees_ready else T[p]] * N)
                    ready = [j for j, f in enumerate(nxt) if f <= t + 1e-9]
                    if not ready: break
                    nxt[ready[0]] = t + T[p]; f = t
                    stock[p] += yield_of(p); where, act = prod[p]["Made in / from"], "harvest"
                else:
                    capacity_error(p, "way to make it (external source: add it to 'have')")
                for i, q in ins: stock[i] -= q
                rem[p] -= 1; last_finish = max(last_finish, f)
                log.append({"Visit": v + 1, "Hour": round(t / 60, 2), "Action": act, "Where": where,
                            "Product": p, "Units": yield_of(p)})
        busy = any(q for qs in machines.values() for q in qs) or fields or any(animals.values())
        if not any(rem.values()) and not busy:
            return {"visits": v + 1, "done_h": t / 60, "ready_h": last_finish / 60, "log": log}
        started = any(r["Visit"] == v + 1 for r in log[-1:])
        trees_pending = any(rem[p] and kind(p) == "tree" for p in pri)
        if not busy and not started and not trees_pending:
            raise RuntimeError(f"stuck at visit {v + 1}: cannot start {[p for p in pri if rem[p]]}")
    raise RuntimeError("did not finish within max_visits")


def money(farm, items, from_stock, I, hours):
    """Mode 1 LP with the order as a must-produce rate; stretch the window if the farm cannot keep up."""
    base = planner.solve(farm, I)["revenue"]
    net = {p: q - from_stock.get(p, 0) for p, q in items.items() if q - from_stock.get(p, 0) > 0}
    H = max(hours, I / 60)
    for _ in range(20):
        try:
            sol = planner.solve(farm, I, demand={p: q / H for p, q in net.items()})
            return base, sol, H
        except RuntimeError:
            H *= 1.25
    raise RuntimeError("LP infeasible even with a long window")


def food_web(order, starts, need):
    lines = []
    def walk(p, depth, mult):
        lines.append("  " * depth + f"- {p} x{mult:g}  [{kind(p)}: {prod[p]['Made in / from']}]")
        for i, q in inputs_of(p):
            walk(i, depth + 1, q * mult / yield_of(p))
    return walk, lines


def main():
    args = sys.argv[1:]
    out = Path(args[args.index("--out") + 1]) if "--out" in args else Path("plans")
    pos = [a for k, a in enumerate(args) if not a.startswith("--") and (k == 0 or not args[k - 1].startswith("--"))]
    D, HI, VER, FARM, QUEST = pos[:5]
    hdata.load(D, HI, VER)
    farm, quest = json.load(open(FARM)), json.load(open(QUEST))
    I = float(args[args.index("--checkin") + 1]) if "--checkin" in args else float(farm["checkin_minutes"])
    items = {hdata.canon(p): float(q) for p, q in quest["items"].items()}
    have = {hdata.canon(p): float(q) for p, q in quest.get("have", {}).items()}
    tag = quest.get("name", Path(QUEST).stem).replace(" ", "_")
    out.mkdir(exist_ok=True)
    rep = []
    say = lambda s="": (rep.append(s), print(s))

    bad = [p for p in items if p not in prod]
    if bad: raise SystemExit(f"unknown products: {bad}")
    unlocked = set(planner.unlocked_products(farm["level"], True, set()))
    order, need, from_stock, starts, made, spare = bom(items, have)
    locked = [p for p in order if starts[p] and p not in unlocked]

    say(f"=== Quest '{tag}': {', '.join(f'{q:g} {p}' for p, q in items.items())} | check-in every {I:g} min ===")
    if locked: say(f"WARNING locked at level {farm['level']} or external: {locked}")
    T, tail = tails(order, farm)
    b = pd.DataFrame([{"Product": p, "Type": kind(p), "Where": prod[p]["Made in / from"] if kind(p) != "field" else "Field",
                       "Needed": need[p], "From stock": from_stock[p], "Start units": starts[p],
                       "Unit": {"machine": "batches", "field": "fields to plant", "animal": "feedings",
                                "tree": "harvests"}.get(kind(p), ""),
                       "Made": made[p], "Spare after quest": spare[p], "Time each (min)": T[p],
                       "Chain to finish (min)": tail[p],
                       "Sell value of spare": round(spare[p] * (price(p)[0] or 0))} for p in order])
    b.to_csv(out / f"quest_{tag}_bom.csv", index=False)
    say("\n-- What it takes (BOM) --")
    say(b[["Product", "Where", "Needed", "From stock", "Start units", "Unit", "Spare after quest"]].to_string(index=False))

    walk, lines = food_web(order, starts, need)
    for p, q in items.items(): walk(p, 0, q)
    say("\n-- Food web (per order, before stock) --"); [say(l) for l in lines]
    edges = defaultdict(float)
    for p in order:
        for i, q in inputs_of(p):
            if starts[p]: edges[(i, p)] += q * starts[p]
    mmd = ["graph LR"] + [f'  "{i}" -->|{q:g}| "{p}"' for (i, p), q in edges.items()]
    (out / f"quest_{tag}_foodweb.mmd").write_text("\n".join(mmd) + "\n")

    crit = max(tail[p] for p in order if starts[p]) / 60 if any(starts.values()) else 0
    tr = quest.get("trees_start", "ready") != "harvested"
    try:
        sim = simulate(order, starts, farm, have, I, tr) if any(starts.values()) else {"visits": 1, "done_h": 0, "ready_h": 0, "log": []}
        fast = simulate(order, starts, farm, have, 5.0, tr) if any(starts.values()) else sim
    except RuntimeError as e:
        say(f"\nCANNOT SCHEDULE: {e}"); (out / f"quest_{tag}_report.txt").write_text("\n".join(rep) + "\n")
        raise SystemExit(1)
    log = pd.DataFrame(sim["log"])
    if len(log):
        log = log.groupby(["Visit", "Hour", "Action", "Where", "Product"], as_index=False)["Units"].sum()
        log["Units"] = log["Units"].astype(int)
    log.to_csv(out / f"quest_{tag}_schedule.csv", index=False)
    say(f"\n-- Timing --\nlongest chain (no waiting): {crit:.1f} h"
        f"\nchecking every 5 min: ready in {fast['done_h']:.1f} h"
        f"\nchecking every {I:g} min: ready at visit {sim['visits']} = {sim['done_h']:.1f} h from now "
        f"(last item finishes at {sim['ready_h']:.1f} h)")
    say("\n-- What to do at each visit --")
    for (v, h), g in log.groupby(["Visit", "Hour"]) if len(log) else []:
        say(f"visit {v} (+{h:g} h): " + "; ".join(f"{r.Action} {r.Units} {r.Product} @{r.Where}" for r in g.itertuples()))
    say(f"visit {sim['visits']} (+{sim['done_h']:g} h): collect, hand in the order")

    base, sol, H = money(farm, items, from_stock, I, sim["done_h"])
    plan, _ = planner.tables(sol)
    plan.to_csv(out / f"quest_{tag}_money_plan.csv", index=False)
    value = sum(q * (price(p)[0] or 0) for p, q in items.items())
    cost = (base - sol["revenue"]) * H
    say(f"\n-- Money while doing it (LP over {H:.1f} h{' - stretched, farm too small for ' + format(sim['done_h'], '.1f') + ' h' if H > sim['done_h'] + 1e-6 else ''}) --")
    say(f"Mode 1 alone: {base:.0f} coins/hr | with this order: {sol['revenue']:.0f} coins/hr"
        f"\norder costs you about {cost:.0f} coins of lost sales; selling the items instead would give {value:.0f}")
    rc = quest.get("reward_coins")
    if rc:
        say(f"reward {rc:g} coins (+{quest.get('reward_xp', 0):g} XP) vs cost {cost:.0f} -> "
            + ("WORTH IT" if rc >= cost else "costs more than it pays (do it for XP / quest only)"))
    sold = plan[plan["Sold/hr"] > 0].sort_values("Coins/hr from sales", ascending=False).head(8)
    say("leftover capacity -> sell: " + ", ".join(f"{p} {v:.0f}/hr" for p, v in zip(sold.Product, sold["Coins/hr from sales"])))
    fp = plan[plan.Type == "field"]
    say("plant per visit (order + money): " + ", ".join(f"{p} {v:g}" for p, v in zip(fp.Product, fp["Per visit"])))
    (out / f"quest_{tag}_report.txt").write_text("\n".join(rep) + "\n")


if __name__ == "__main__":
    main()
