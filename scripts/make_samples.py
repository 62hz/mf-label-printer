"""Render sample labels from a Templater workbook into one review sheet, and check every barcode decodes.

  uv run python scripts/make_samples.py "C:/Users/SER5 MAX/Documents/#MEDFOR/04APR/Barcode Templater April.xlsx" [count] [design-slug]

Writes samples/review-sheet.png (3 columns). Open it next to the April label and judge the look.
"""
import sys
from pathlib import Path

import zxingcpp
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from labelprinter.designs import DEFAULT_SLUG, DesignStore  # noqa: E402
from labelprinter.outputs import read_sheet  # noqa: E402
from labelprinter.render import render  # noqa: E402


def main():
    src = Path(sys.argv[1])
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 9
    design = DesignStore(ROOT / "data" / "designs").get(sys.argv[3] if len(sys.argv) > 3 else DEFAULT_SLUG)
    labels, sheet = read_sheet(src.read_bytes(), src.name)
    print(f"{len(labels)} rows from sheet '{sheet}'")
    picks = labels[:count]
    cols, pad = 3, 14
    sheet_img = Image.new("L", (cols * (400 + pad) + pad, ((len(picks) + cols - 1) // cols) * (240 + pad) + pad), 190)
    bad = 0
    for n, label in enumerate(picks):
        img = render(label, design)
        got = [r.text for r in zxingcpp.read_barcodes(img.convert("L"))]
        ok = got == [label.sku]
        bad += not ok
        print(("ok  " if ok else "FAIL"), label.sku, "|", label.artist, "-", label.title[:40])
        sheet_img.paste(img.convert("L"), (pad + (n % cols) * (400 + pad), pad + (n // cols) * (240 + pad)))
    out = ROOT / "samples"
    out.mkdir(exist_ok=True)
    sheet_img.save(out / "review-sheet.png")
    print("wrote", out / "review-sheet.png")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
