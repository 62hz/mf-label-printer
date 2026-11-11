"""Render sample labels in the MF Brand designs side by side.

  uv run python scripts/brand_preview.py [out_dir] [--guides] [--prefix mf-brand-]

Every design whose file name starts with the prefix becomes one column. Each label is the exact
1-bit image the printer gets (400 x 240 dots), shown at 2x with hard pixels. Writes compare.png
(all designs, all samples). With --guides it also writes compare-guides.png: the same sheet with the
2 mm margins drawn in magenta and a 1 mm grid in light grey, to check alignment by eye.
Output goes to samples/brand/ (git-ignored) unless a folder is given.
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from labelprinter import fonts, render  # noqa: E402
from labelprinter.model import Label  # noqa: E402

DESIGN_DIR = ROOT / "labelprinter" / "designs"
SAMPLES = [
    Label("AMEAMET158", "American Football", "American Football (Deluxe Edition)", "CASSETTE", "1999", "Rock", 305000),
    Label("NOUPASC001", "Nourished By Time", "The Passionate Ones", "CD", "2024", "Soul", 330000),
    Label("191404155127", "Charli XCX", "Brat", "VINYL", "2024", "Pop", 345000),
    Label("SAKVRIO002", "Ryuichi Sakamoto & Alva Noto", "Vrioon (Remastered 25th Anniversary Edition)", "VINYL", "2002", "Electronic", 1250000),
    Label("ALEHEAC557", "Various Artists", "Cafe de Flore", "CD", "", "", 95000),
]
SCALE, PAD, CAPTION = 2, 28, 44
PLATE, INK, MUTED = (226, 226, 224), (25, 25, 25), (110, 110, 108)
MARGIN_MM = 2


def load(slug: str) -> dict:
    return json.loads((DESIGN_DIR / f"{slug}.json").read_text(encoding="utf-8"))


def label_image(label: Label, design: dict, guides: bool) -> Image.Image:
    dots = render.render(label, design).convert("L")
    img = dots.resize((dots.width * SCALE, dots.height * SCALE), Image.NEAREST).convert("RGB")
    if guides:
        d = ImageDraw.Draw(img)
        mm = render.DPM * SCALE
        for i in range(1, int(design["width_mm"])):
            d.line((i * mm, 0, i * mm, img.height), fill=(215, 215, 235), width=1)
        for j in range(1, int(design["height_mm"])):
            d.line((0, j * mm, img.width, j * mm), fill=(215, 215, 235), width=1)
        m = MARGIN_MM * mm
        d.rectangle((m, m, img.width - m, img.height - m), outline=(220, 0, 140), width=1)
    return img


def sheet(columns, samples, guides: bool = False) -> Image.Image:
    caption_font = ImageFont.truetype(str(fonts.default.resolve("dm-sans-medium", False, False)), 22)
    designs = [(load(slug), title) for slug, title in columns]
    w, h = render.size_dots(designs[0][0])
    cell_w, cell_h = w * SCALE, h * SCALE
    width = PAD + len(designs) * (cell_w + PAD)
    height = PAD + CAPTION + len(samples) * (cell_h + PAD)
    out = Image.new("RGB", (width, height), PLATE)
    draw = ImageDraw.Draw(out)
    for c, (design, title) in enumerate(designs):
        x = PAD + c * (cell_w + PAD)
        draw.text((x, PAD), title, font=caption_font, fill=INK)
        for r, label in enumerate(samples):
            y = PAD + CAPTION + r * (cell_h + PAD)
            out.paste(label_image(label, design, guides), (x, y))
            draw.rectangle((x - 1, y - 1, x + cell_w, y + cell_h), outline=MUTED)
    return out


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    prefix = "mf-brand-"
    if "--prefix" in sys.argv:
        prefix = sys.argv[sys.argv.index("--prefix") + 1]
        args = [a for a in args if a != prefix]
    out_dir = Path(args[0]) if args else ROOT / "samples" / "brand"
    out_dir.mkdir(parents=True, exist_ok=True)
    slugs = sorted(p.stem for p in DESIGN_DIR.glob(f"{prefix}*.json"))
    columns = [(slug, load(slug)["name"]) for slug in slugs]
    sheet(columns, SAMPLES).save(out_dir / "compare.png")
    if "--guides" in sys.argv:
        sheet(columns, SAMPLES, guides=True).save(out_dir / "compare-guides.png")
    for slug, _ in columns:
        for label in SAMPLES:
            notes = [n for n in render.notes(label, load(slug)) if "Barcode bars" not in n]
            if notes:
                print(slug, label.sku, "|", notes[0][:90])
    print("wrote", out_dir, [s for s, _ in columns])
    return 0


if __name__ == "__main__":
    sys.exit(main())
