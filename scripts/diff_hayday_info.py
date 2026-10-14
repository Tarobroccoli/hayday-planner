"""Diff live hayday.info /api/production-data JSON against the hand-transcribed
'hayday_info' sheet of hayday_merged_clean.xlsx. Read-only: writes a CSV report."""
import json, re, sys
import pandas as pd

XLSX, JSON, OUT = sys.argv[1], sys.argv[2], sys.argv[3]

def norm(s):
    s = re.sub(r"[​-‏⁠﻿]", "", str(s))
    return re.sub(r"\s+", " ", s).strip().lower()

sheet = pd.read_excel(XLSX, sheet_name="hayday_info")
live = pd.DataFrame(json.load(open(JSON)))
live = live.rename(columns={"product": "Product", "machine": "Machine", "level": "Level",
                            "time_min": "Time (min)", "price": "Sell price", "xp": "XP",
                            "profit_per_hour": "Profit/hr (site)", "xp_per_hour": "XP/hr (site)"})
for d in (sheet, live):
    d["key"] = d["Product"].map(norm)

print("dup keys sheet:", sheet["key"][sheet["key"].duplicated()].tolist())
print("dup keys live :", live["key"][live["key"].duplicated()].tolist())

m = sheet.merge(live, on="key", how="outer", suffixes=("_xlsx", "_live"), indicator=True)
rows = []
for _, r in m.iterrows():
    if r["_merge"] != "both":
        rows.append({"key": r["key"], "field": "MISSING", "xlsx": r.get("Product_xlsx"),
                     "live": r.get("Product_live"), "note": r["_merge"]})
        continue
    for f in ["Machine", "Level", "Time (min)", "Sell price", "XP", "Profit/hr (site)", "XP/hr (site)"]:
        a, b = r[f + "_xlsx"], r[f + "_live"]
        if f == "Machine":
            same = norm(a) == norm(b)
        else:
            same = abs(float(a) - float(b)) <= (0.051 if "/hr" in f else 0)  # sheet rounded /hr
        if not same:
            rows.append({"key": r["key"], "field": f, "xlsx": a, "live": b, "note": ""})
    if str(r["Product_xlsx"]) != str(r["Product_live"]).strip():
        rows.append({"key": r["key"], "field": "Product name (case/spelling)", "xlsx": r["Product_xlsx"],
                     "live": r["Product_live"], "note": "cosmetic"})
rep = pd.DataFrame(rows)
rep.to_csv(OUT, index=False)
print(f"sheet {len(sheet)} rows, live {len(live)} rows, diffs {len(rep)}")
if len(rep):
    print(rep["field"].value_counts().to_string())
    print(rep[rep["note"] != "cosmetic"].to_string())
