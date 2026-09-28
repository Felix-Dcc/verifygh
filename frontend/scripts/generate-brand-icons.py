"""Draw the VerifyGH favicon, app icons and link-preview image.

    python scripts/generate-brand-icons.py        (needs Pillow)

Everything is drawn from the same geometry as the Logomark component
(src/components/brand.tsx, a 32 x 32 design): a rounded green tile, a white
check, and the small gold star. It is rendered large and scaled down, so the
edges stay smooth, and the small sizes are checked to stay legible - at 16px
the check is what you see, which is the point of the mark.

Outputs (paths relative to frontend/):
  src/app/favicon.ico            16, 32, 48
  src/app/icon.svg               the vector favicon modern browsers prefer
  src/app/apple-icon.png         180, full-bleed (iOS rounds the corners itself)
  public/icons/icon-192.png      web app manifest
  public/icons/icon-512.png      web app manifest
  public/icons/icon-maskable-512.png   manifest, Android adaptive icon safe zone
  src/app/opengraph-image.png    1200 x 630 link preview (also twitter-image.png)
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BRAND = (11, 100, 70)        # brand-600  #0B6446
BRAND_DARK = (7, 60, 42)     # brand-800  #073C2A
GOLD = (199, 154, 46)        # #C79A2E
INK = (16, 24, 40)
MUTED = (71, 84, 103)
CANVAS = (246, 248, 247)

CHECK = [(9.5, 16.6), (13.7, 20.8), (22.5, 11.6)]
CHECK_WIDTH = 2.6
STAR = [(24.2, 6.4), (24.92, 8.0), (26.64, 8.2), (25.36, 9.4), (25.70, 11.12), (24.20, 10.26),
        (22.70, 11.12), (23.04, 9.40), (21.76, 8.20), (23.48, 8.00)]

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="9" fill="#0B6446"/>
  <path d="M9.5 16.6l4.2 4.2 8.8-9.2" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M24.2 6.4l.72 1.6 1.72.2-1.28 1.2.34 1.72-1.5-.86-1.5.86.34-1.72-1.28-1.2 1.72-.2z" fill="#C79A2E"/>
</svg>
"""


def mark(size: int, *, full_bleed: bool = False, inset: float = 0.0, star: bool = True) -> Image.Image:
    """The logomark at `size` px. `inset` shrinks the drawing inside the square
    (for maskable icons); `full_bleed` fills the square instead of rounding it."""
    scale_up = 4
    big = size * scale_up
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    unit = big * (1 - 2 * inset) / 32
    offset = big * inset

    def pt(x, y):
        return (offset + x * unit, offset + y * unit)

    if full_bleed:
        draw.rectangle([0, 0, big, big], fill=BRAND)
    else:
        draw.rounded_rectangle([0, 0, big - 1, big - 1], radius=9 * big / 32, fill=BRAND)

    width = max(1, round(CHECK_WIDTH * unit))
    points = [pt(x, y) for x, y in CHECK]
    draw.line(points, fill="white", width=width, joint="curve")
    radius = width / 2
    for x, y in (points[0], points[-1]):
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill="white")

    if star:
        draw.polygon([pt(x, y) for x, y in STAR], fill=GOLD)

    return image.resize((size, size), Image.LANCZOS)


def font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    for name in (["segoeuib.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"]):
        for folder in (Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu")):
            if (folder / name).exists():
                return ImageFont.truetype(str(folder / name), size)
    return ImageFont.load_default()


def social_card() -> Image.Image:
    card = Image.new("RGB", (1200, 630), CANVAS)
    draw = ImageDraw.Draw(card)
    # A band of brand colour down the left, so the preview is recognisable
    # even as a thumbnail.
    draw.rectangle([0, 0, 24, 630], fill=BRAND)
    logo = mark(168)
    card.paste(logo, (96, 118), logo)
    draw.text((96, 330), "VerifyGH", font=font(True, 96), fill=INK)
    draw.text((100, 450), "SMS verification numbers, paid for with", font=font(False, 40), fill=MUTED)
    draw.text((100, 502), "Ghana Mobile Money.", font=font(False, 40), fill=MUTED)
    draw.text((1104, 560), "getverifygh.com", font=font(True, 28), fill=BRAND, anchor="rs")
    return card


def main() -> None:
    app = ROOT / "src" / "app"
    icons = ROOT / "public" / "icons"
    icons.mkdir(parents=True, exist_ok=True)

    (app / "icon.svg").write_text(SVG, encoding="utf-8")

    # 16px: the star is below a pixel and only muddies the check, so it goes.
    ico_sizes = [mark(16, star=False), mark(32), mark(48)]
    ico_sizes[2].save(app / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48)],
                      append_images=ico_sizes[:2])

    mark(180, full_bleed=True, inset=0.08).convert("RGB").save(app / "apple-icon.png", optimize=True)
    mark(192).save(icons / "icon-192.png", optimize=True)
    mark(512).save(icons / "icon-512.png", optimize=True)
    # Android crops maskable icons to a circle: keep the mark in the middle 80%.
    mark(512, full_bleed=True, inset=0.1).save(icons / "icon-maskable-512.png", optimize=True)

    card = social_card()
    card.save(app / "opengraph-image.png", optimize=True)
    card.save(app / "twitter-image.png", optimize=True)
    alt = "VerifyGH - SMS verification numbers, paid for with Ghana Mobile Money."
    (app / "opengraph-image.alt.txt").write_text(alt, encoding="utf-8")
    (app / "twitter-image.alt.txt").write_text(alt, encoding="utf-8")
    print("brand icons written")


if __name__ == "__main__":
    main()
