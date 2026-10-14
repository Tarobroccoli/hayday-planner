"""Export product data + farm profile + small icons for the single-file HTML planner.

Usage: export_web.py <fandom_dir> <hayday_info.json> <verified.csv> <farm_profile.json> <icon_manifest.csv>
                     <template.html> <out.html>
The template contains the placeholder /*__DATA__*/null; it is replaced by the JSON blob.
"""
import base64, io, json, sys
from pathlib import Path
import pandas as pd
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hdata, planner
from hdata import BATCH, FEED, TREE_FRUIT_PER_HARVEST, prod, recipe, price, kind

ICON_PX = 48


def icon_uri(path):
    try:
        im = Image.open(path).convert("RGBA")
    except Exception:
        return None
    im.thumbnail((ICON_PX, ICON_PX), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=80, method=6)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()


def main():
    D, HI, VER, FARM, MAN, TPL, OUT = sys.argv[1:8]
    hdata.load(D, HI, VER)
    man = pd.read_csv(MAN)
    icons = {p: lp for p, lp in zip(man["Product"], man["Local path"]) if isinstance(lp, str)}
    items = []
    for p, r in sorted(prod.items()):
        k = kind(p)
        if k == "animal":
            ins = [[FEED[p], 1]] if p in FEED else []
        elif k == "machine":
            ins = [[i, float(q)] for i, q in recipe.get(p, [])]
        else:
            ins = []
        pr, src = price(p)
        num = lambda v: None if pd.isna(v) else float(v)
        items.append({
            "n": p, "k": k, "w": r["Made in / from"] if isinstance(r["Made in / from"], str) else "",
            "lv": num(r["Level"]), "t": num(r["Time normal (min)"]) or 0.0, "tm": num(r["Time mastered (min)"]),
            "p": pr, "ps": src, "xp": planner.xp_of(p),
            "y": BATCH.get(p, 1) if k == "machine" else (TREE_FRUIT_PER_HARVEST if k == "tree" else 1),
            "in": ins, "ic": icon_uri(icons[p]) if p in icons else None,
        })
    farm = {k: v for k, v in json.load(open(FARM)).items() if not k.startswith("_")}
    blob = {"items": items, "farm": farm, "treeFruit": TREE_FRUIT_PER_HARVEST,
            "built": pd.Timestamp.now().strftime("%Y-%m-%d"),
            "sources": "hayday.info (prices, XP), Fandom MediaWiki API (recipes, times, levels), in-game checks"}
    html = Path(TPL).read_text()
    assert "/*__DATA__*/null" in html
    html = html.replace("/*__DATA__*/null", json.dumps(blob, separators=(",", ":")))
    if "/*__ENGINE__*/" in html:  # engine.js lives next to the template
        html = html.replace("/*__ENGINE__*/", (Path(TPL).parent / "engine.js").read_text())
    Path(OUT).write_text(html)
    print(f"{len(items)} products, {sum(1 for i in items if i['ic'])} icons -> {OUT} "
          f"({Path(OUT).stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
