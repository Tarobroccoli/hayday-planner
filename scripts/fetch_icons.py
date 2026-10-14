"""Download product icons from the Hay Day Wiki and write icons/icon_manifest.csv.

Icon file names come from merged_v2 'Icon file (Fandom)' (first [[File:]] on each product page).
URLs + sha1 via MediaWiki API (prop=imageinfo, 50 files/request). Saved to icons/<Machine>/<Product>.<ext>.
Default: 256px-wide PNG thumbnails (originals are up to ~1000px / ~1.5 MB each).
`--original` saves the uploaded files instead and checks their sha1.
Existing valid files are skipped. Artwork (c) Supercell - personal reference use only.
"""
import csv, hashlib, json, re, ssl, struct, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
import pandas as pd

ORIGINAL = "--original" in sys.argv
XLSX, OUT = [a for a in sys.argv[1:] if not a.startswith("--")][:2]
OUT = Path(OUT)
WIDTH = 256
API = "https://hayday.fandom.com/api.php"
SSL = ssl.create_default_context(cafile="/etc/ssl/certs/ca-certificates.crt")
UA = {"User-Agent": "Mozilla/5.0 (personal Hay Day data project)"}
MAGIC = {b"\x89PNG": "png", b"\xff\xd8\xff": "jpg", b"GIF8": "gif", b"RIFF": "webp"}

def get(url, tries=5):
    """GET with backoff on 429/5xx (the CDN returns 503 while generating thumbnails)."""
    for n in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60, context=SSL) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or n == tries - 1:
                raise
        except urllib.error.URLError:
            if n == tries - 1:
                raise
        time.sleep(5 * 2 ** n)

def png_size(b):
    return struct.unpack(">II", b[16:24]) if b[:8] == b"\x89PNG\r\n\x1a\n" else None

def icon_url(u):
    """Fandom CDN: '/revision/latest?cb=..' -> scaled PNG; format=original stops WebP re-encoding."""
    if not ORIGINAL:
        u = u.replace("/revision/latest", f"/revision/latest/scale-to-width-down/{WIDTH}", 1)
    return u + ("&" if "?" in u else "?") + "format=original"

safe = lambda s: re.sub(r'[\\/:*?"<>|]+', "_", str(s)).strip()

df = pd.read_excel(XLSX, sheet_name="merged_v2")[["Product", "Machine", "Icon file (Fandom)"]]
files = sorted(set(df["Icon file (Fandom)"].dropna()))
info = {}
for i in range(0, len(files), 50):
    chunk = ["File:" + f for f in files[i:i + 50]]
    q = json.loads(get(API + "?" + urllib.parse.urlencode({
        "action": "query", "prop": "imageinfo", "iiprop": "url|sha1|size|mime", "titles": "|".join(chunk),
        "redirects": 1, "format": "json", "formatversion": 2})))["query"]
    alias = {x["from"]: x["to"] for k in ("normalized", "redirects") for x in q.get(k, [])}
    pages = {p["title"]: p for p in q["pages"]}
    for t in chunk:
        f = t
        while f in alias:
            f = alias[f]
        p = pages.get(f, {})
        info[t[5:]] = p["imageinfo"][0] if p.get("imageinfo") else None
    time.sleep(1)
print("imageinfo:", sum(v is not None for v in info.values()), "/", len(files))

rows = []
for _, r in df.iterrows():
    row = {"Product": r.Product, "Machine": r.Machine, "Icon file (Fandom)": r["Icon file (Fandom)"],
           "Local path": "", "Status": "", "Width": "", "Height": "", "Original width": "", "Original height": "", "SHA1 (original)": "", "URL": ""}
    ii = info.get(r["Icon file (Fandom)"]) if pd.notna(r["Icon file (Fandom)"]) else None
    if pd.isna(r["Icon file (Fandom)"]):
        row["Status"] = "no Fandom page"
    elif ii is None:
        row["Status"] = "file not found on wiki"
    else:
        row.update({"URL": ii["url"], "Original width": ii["width"], "Original height": ii["height"], "SHA1 (original)": ii["sha1"]})
        ext = Path(urllib.parse.urlparse(ii["url"]).path).suffix.lower() or ".png"
        dst = OUT / safe(r.Machine) / (safe(r.Product) + ext)
        want_w = ii["width"] if ORIGINAL else min(WIDTH, ii["width"])
        def valid(b):
            if ORIGINAL:
                return hashlib.sha1(b).hexdigest() == ii["sha1"]
            sz = png_size(b)
            return sz is not None and abs(sz[0] - want_w) <= 1
        if dst.exists() and valid(dst.read_bytes()):
            row["Status"] = "ok (cached)"
        else:
            try:
                data = get(icon_url(ii["url"]))
            except urllib.error.URLError as e:
                data, row["Status"] = None, f"download failed: {e}"
            if data is None:
                pass
            elif png_size(data) is None and not any(data.startswith(k) for k in MAGIC):
                row["Status"] = "not an image - not saved"
            elif not valid(data):
                row["Status"] = "sha1/size mismatch - not saved"
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(data)
                row["Status"] = "ok"
            time.sleep(0.3)
        if dst.exists():
            sz = png_size(dst.read_bytes()[:32])
            if sz:
                row["Width"], row["Height"] = sz
        if row["Status"].startswith("ok"):
            row["Local path"] = dst.relative_to(OUT.parent).as_posix()
    rows.append(row)

with open(OUT / "icon_manifest.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print(pd.DataFrame(rows)["Status"].value_counts().to_string())
