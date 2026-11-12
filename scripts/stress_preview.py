"""Render one design with hard data: long artists and titles, wordy genres, long SKUs, big prices, empty fields.

  uv run python scripts/stress_preview.py [slug] [out.png]

Shows each label at 2x with the record's text beside it, and prints every element the renderer had to
shrink or cut ("..."), so spacing problems are visible before they reach a sleeve.
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from labelprinter import fonts, render  # noqa: E402
from labelprinter.model import Label  # noqa: E402

CASES = [
    ("Typical", Label("NOUPASC001", "Nourished By Time", "The Passionate Ones", "CD", "2024", "Soul", 330000)),
    ("Long artist", Label("SAKVRIO002", "Ryuichi Sakamoto & Alva Noto", "Vrioon", "VINYL", "2002", "Electronic", 450000)),
    ("Long title", Label("GODSPEED01", "Godspeed You! Black Emperor", "Lift Your Skinny Fists Like Antennas To Heaven (Remastered 2LP)", "VINYL", "2000", "Post-Rock", 785000)),
    ("Wordy genre", Label("VARIOUS0042", "Various Artists", "Kampung Gaul: Indonesian Disco, Funk & Boogie 1976-1989", "VINYL", "2023", "Funk / Soul, Disco, Pop Kreatif", 520000)),
    ("Long everything", Label("ORCHMANOEUV7", "Orchestral Manoeuvres In The Dark", "Architecture & Morality (40th Anniversary Deluxe Edition, Half-Speed Master)", "CASSETTE", "1981", "Synth-pop, New Wave, Electronic", 1250000)),
    ("Long SKU, big price", Label("ABCDEFGHIJKLM", "Miles Davis", "Kind Of Blue (Original Mono Recording, Mint Box Set)", "VINYL", "1959", "Jazz", 12500000)),
    ("13-digit SKU", Label("4988031465987", "Kikagaku Moyo", "Kumoyo Island", "CD", "2022", "Psychedelic Rock", 299000)),
    ("Empty fields", Label("ALEHEAC557", "Various Artists", "Cafe de Flore", "CD", "", "", 95000)),
    ("Bahasa", Label("IWAKARI003", "Iwan Fals & Sawung Jabo", "Swami (Edisi Ulang Tahun Ke-30)", "CASSETTE", "1989", "Pop Rock Indonesia", 175000)),
]
SCALE, PAD, TEXT_W = 2, 24, 520


def main() -> int:
    slug = sys.argv[1] if len(sys.argv) > 1 else "mf-passport-row"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "samples" / "stress" / f"{slug}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    design = json.loads((ROOT / "labelprinter" / "designs" / f"{slug}.json").read_text(encoding="utf-8"))
    w, h = render.size_dots(design)
    cell_w, cell_h = w * SCALE, h * SCALE
    sheet = Image.new("RGB", (PAD * 3 + cell_w + TEXT_W, PAD + len(CASES) * (cell_h + PAD)), (226, 226, 224))
    draw = ImageDraw.Draw(sheet)
    f_head = ImageFont.truetype(str(fonts.default.resolve("dm-sans-semibold", False, False)), 22)
    f_body = ImageFont.truetype(str(fonts.default.resolve("dm-sans", False, False)), 17)
    for i, (name, label) in enumerate(CASES):
        y = PAD + i * (cell_h + PAD)
        try:
            img = render.render(label, design).convert("L")
            sheet.paste(img.resize((cell_w, cell_h), Image.NEAREST).convert("RGB"), (PAD, y))
        except ValueError as exc:
            draw.rectangle((PAD, y, PAD + cell_w, y + cell_h), fill=(255, 235, 235))
            draw.text((PAD + 10, y + 10), "FAILS: " + str(exc)[:60], font=f_body, fill=(160, 0, 0))
            print(name, "FAILS:", exc)
        tx = PAD * 2 + cell_w
        draw.text((tx, y), name, font=f_head, fill=(25, 25, 25))
        lines = [f"artist  {label.artist}", f"title   {label.title}", f"genre   {label.genre}", f"sku     {label.sku}",
                 f"format {label.format}  year {label.year or '-'}  price {label.price}"]
        for j, line in enumerate(lines):
            draw.text((tx, y + 34 + j * 24), line[:58] + ("..." if len(line) > 58 else ""), font=f_body, fill=(70, 70, 70))
    sheet.save(out)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
