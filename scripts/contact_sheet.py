"""Tile every icon in icons/icon_manifest.csv into contact sheet PNGs for a visual spot-check.
Each tile: icon (fit in 96x96) + product name; tiles grouped by machine in manifest order."""
import sys
from pathlib import Path
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

MAN, OUT = Path(sys.argv[1]), Path(sys.argv[2])
COLS, TILE, PAD, LAB, PER = 12, 96, 8, 26, 156  # PER = tiles per sheet
m = pd.read_csv(MAN).sort_values(["Machine", "Product"])
m = m[m["Local path"].notna()]
font = ImageFont.load_default(size=11)

for s, start in enumerate(range(0, len(m), PER), 1):
    part = m.iloc[start:start + PER]
    rows = -(-len(part) // COLS)
    W, H = COLS * (TILE + PAD) + PAD, rows * (TILE + LAB + PAD) + PAD
    sheet = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(sheet)
    for i, r in enumerate(part.rename(columns={"Local path": "path"}).itertuples()):
        x, y = PAD + (i % COLS) * (TILE + PAD), PAD + (i // COLS) * (TILE + LAB + PAD)
        im = Image.open(MAN.parent.parent / r.path).convert("RGBA")
        im.thumbnail((TILE, TILE))
        bg = Image.new("RGBA", (TILE, TILE), (235, 235, 235, 255))
        bg.alpha_composite(im, ((TILE - im.width) // 2, (TILE - im.height) // 2))
        sheet.paste(bg.convert("RGB"), (x, y))
        name = r.Product if len(r.Product) <= 17 else r.Product[:16] + "…"
        d.text((x, y + TILE + 1), name, fill="black", font=font)
        d.text((x, y + TILE + 13), r.Machine[:17], fill=(120, 120, 120), font=font)
    f = OUT / f"contact_sheet_{s}.png"; sheet.save(f); print(f, len(part))
