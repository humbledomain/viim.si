#!/usr/bin/env python3
"""
Rasterize the site's mark into the full icon + social-share set.
Run once per site:  python3 build-icons.py
Inputs:  brand/icon.svg (square, opaque), brand/share.svg (1200x630, opaque)
Outputs: assets/*  — referenced by index.html
"""
import pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent
BRAND, OUT = ROOT / "brand", ROOT / "assets"
OUT.mkdir(exist_ok=True)

def render(svg, png, w, h):
    try:
        import cairosvg
        cairosvg.svg2png(url=str(svg), write_to=str(png),
                         output_width=w, output_height=h)
    except ImportError:
        subprocess.run(["convert", "-background", "none", "-density", "512",
                        str(svg), "-resize", f"{w}x{h}!", str(png)], check=True)
    print(f"  {png.name}  {w}x{h}")

def main():
    icon, share = BRAND / "icon.svg", BRAND / "share.svg"
    for f in (icon, share):
        if not f.exists():
            sys.exit(f"missing {f}")

    print("icons:")
    for size in (16, 32, 48, 180, 192, 512, 1024):
        render(icon, OUT / f"icon-{size}.png", size, size)

    print("share cards:")
    render(share, OUT / "og.png", 1200, 630)          # wide card
    render(icon,  OUT / "og-square.png", 1200, 1200)  # square-crop clients

    from PIL import Image
    (OUT / "apple-touch-icon.png").write_bytes((OUT / "icon-180.png").read_bytes())
    Image.open(OUT / "icon-512.png").convert("RGBA").save(
        OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    print("  apple-touch-icon.png 180x180\n  favicon.ico 16/32/48")

    for name, cap in (("og.png", 600), ("og-square.png", 600)):
        kb = (OUT / name).stat().st_size // 1024
        flag = "  <-- OVER BUDGET, flatten gradients" if kb > cap else ""
        print(f"  {name}: {kb} KB (cap {cap}){flag}")

if __name__ == "__main__":
    main()
