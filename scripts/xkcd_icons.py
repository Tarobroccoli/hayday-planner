"""Redraw product icons as xkcd-style line art: black wobbly strokes on white.

Outline = alpha-mask contour; inner lines = contours of the blurred brightness at a few levels.
Everything is drawn with matplotlib's plt.xkcd() sketch mode, which gives the hand-drawn wobble.

Optional flat colour under the lines (--color flat|marker): the icon posterised to a few colours,
lightened toward white; "marker" shifts the colour a little off the lines like hand colouring.

Usage: xkcd_icons.py <icons_dir> <out_dir> [--only "Name1,Name2"] [--px 256] [--levels 3]
                     [--color flat|marker] [--ncolors 4] [--no-halo]
plt.xkcd() draws a 4 px white stroke behind every line (the "halo"); --no-halo turns it off.
--no-lines skips the black strokes and keeps only the flat colour (use with --color flat).
"""
import sys, zlib
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image, ImageFilter
from scipy import ndimage


def flat_fill(im, ncolors=4, lighten=0.25, shift=(0, 0)):
    """Posterised, lightened copy of the icon on white (RGBA image in, RGB array out)."""
    rgb = Image.alpha_composite(Image.new("RGBA", im.size, "white"), im).convert("RGB")
    rgb = rgb.filter(ImageFilter.GaussianBlur(2)).quantize(ncolors, method=Image.Quantize.MEDIANCUT).convert("RGB")
    a = np.asarray(rgb, dtype=float)
    a = a + (255 - a) * lighten
    mask = ndimage.binary_erosion(np.asarray(im)[..., 3] > 128, iterations=2)
    mask = np.roll(mask, shift, axis=(0, 1))
    a[~mask] = 255
    return a.astype(np.uint8)


def draw(src, dst, px=256, levels=3, min_len=25, color=None, ncolors=4, halo=True, lines=True):
    im = Image.open(src).convert("RGBA")
    pad = int(px * 0.06)                       # room for the wobble so outlines are not clipped
    im = im.crop(im.getbbox() or (0, 0, *im.size))   # trim empty border, then scale up or down to fit
    k = (px - 2 * pad) / max(im.size)
    im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
    canvas = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    canvas.paste(im, ((px - im.width) // 2, (px - im.height) // 2))
    im = canvas
    a = np.asarray(im, dtype=float) / 255
    alpha = ndimage.gaussian_filter(a[..., 3], 1.5)
    lum = (0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2])
    lum = ndimage.gaussian_filter(np.where(a[..., 3] > 0.5, lum, 1.0), 2.0)
    h, w = alpha.shape

    with plt.xkcd(scale=1.2, length=60, randomness=2):
        if not halo:
            plt.rcParams["path.effects"] = []
        fig = plt.figure(figsize=(w / 100, h / 100), dpi=100)
        ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, w); ax.set_ylim(h, 0); ax.axis("off")
        fig.patch.set_facecolor("white")
        if color:
            rng = np.random.default_rng(zlib.crc32(Path(src).stem.encode()))  # same shift every run
            shift = tuple(rng.integers(-5, 6, 2)) if color == "marker" else (0, 0)
            ax.imshow(flat_fill(im, ncolors, shift=shift), extent=(0, w, h, 0), interpolation="nearest", zorder=0)
        if not lines:
            fig.savefig(dst, facecolor="white"); plt.close(fig); return
        # inner lines: brightness contours inside the shape, short scraps dropped
        inside = ndimage.binary_erosion(a[..., 3] > 0.5, iterations=4)
        qs = sorted(set(np.quantile(lum[inside], np.linspace(0.2, 0.7, levels)))) if inside.sum() > 50 else []
        inner = ax.contour(np.where(inside, lum, np.nan), levels=qs).allsegs if len(qs) else []
        for p in [p for lv in inner for p in lv]:
            if len(p) >= min_len:
                ax.plot(p[:, 0], p[:, 1], color="black", lw=1.4, solid_capstyle="round")
        # outline last, thicker
        for p in ax.contour(alpha, levels=[0.5]).allsegs[0]:
            if len(p) >= min_len:
                ax.plot(p[:, 0], p[:, 1], color="black", lw=2.6, solid_capstyle="round")
        for c in list(ax.collections):
            c.remove()
        fig.savefig(dst, facecolor="white")
        plt.close(fig)


def main():
    args = sys.argv[1:]
    src, out = Path(args[0]), Path(args[1])
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    px = int(args[args.index("--px") + 1]) if "--px" in args else 256
    levels = int(args[args.index("--levels") + 1]) if "--levels" in args else 3
    color = args[args.index("--color") + 1] if "--color" in args else None
    ncolors = int(args[args.index("--ncolors") + 1]) if "--ncolors" in args else 4
    halo = "--no-halo" not in args
    lines = "--no-lines" not in args
    files = sorted(p for p in src.rglob("*.png") if not p.name.startswith("contact_sheet"))
    if only: files = [p for p in files if p.stem in only]
    for p in files:
        d = out / p.relative_to(src)
        d.parent.mkdir(parents=True, exist_ok=True)
        draw(p, d, px, levels, color=color, ncolors=ncolors, halo=halo, lines=lines)
    print(f"{len(files)} icons -> {out}")


if __name__ == "__main__":
    main()
