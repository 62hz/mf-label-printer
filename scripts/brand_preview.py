"""Render sample labels in the current April design and the two brand designs, side by side.

  uv run python scripts/brand_preview.py [out_dir]

Each label is the exact 1-bit image the printer gets (400 x 240 dots), shown at 2x with hard pixels.
Writes compare.png (all designs, all samples) and one sheet per brand design. Output goes to
samples/brand/ (git-ignored) unless a folder is given.
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
COLUMNS = [("mf-april", "Today: MF April"), ("mf-brand-symbol", "Brand: symbol"), ("mf-brand-screen-logo", "Brand: screen logo")]
SCALE, PAD, CAPTION = 2, 28, 44
PLATE, INK, MUTED = (226, 226, 224), (25, 25, 25), (110, 110, 108)


def load(slug: str) -> dict:
    return json.loads((DESIGN_DIR / f"{slug}.json").read_text(encoding="utf-8"))


def label_image(label: Label, design: dict) -> Image.Image:
    dots = render.render(label, design).convert("L")
    return dots.resize((dots.width * SCALE, dots.height * SCALE), Image.NEAREST).convert("RGB")


def sheet(columns, samples) -> Image.Image:
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
            out.paste(label_image(label, design), (x, y))
            draw.rectangle((x - 1, y - 1, x + cell_w, y + cell_h), outline=MUTED)
    return out


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "samples" / "brand"
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet(COLUMNS, SAMPLES).save(out_dir / "compare.png")
    for column in COLUMNS[1:]:
        sheet([column], SAMPLES).save(out_dir / f"{column[0]}.png")
    for slug, _ in COLUMNS:
        for label in SAMPLES:
            notes = render.notes(label, load(slug))
            if notes:
                print(slug, label.sku, "|", notes[0][:90])
    print("wrote", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
