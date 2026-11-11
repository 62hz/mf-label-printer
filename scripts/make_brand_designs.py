"""Write the MF Brand label designs from one grid, so every position is derived, never typed by eye.

  uv run python scripts/make_brand_designs.py

The system (50 x 30 mm label, 8 dots per mm):
  margins     2.5 mm on all four sides: the live area is x 2.5-47.5, y 2.5-27.5
  baselines   every line of text sits on a baseline in a 0.5 mm grid; text boxes are anchored on it
              (valign "baseline"), so a line that shrinks to fit stays on its line
  type scale  6 / 8 / 10 / 12 pt, DM Sans only: artist 12 SemiBold, title 8 Regular, price 10 Medium,
              meta and SKU 6 pt (meta Medium, uppercase)
  black       the barcode is the only large solid mass; no reverse chips; one 0.25 mm rule at most
  mark        the symbol at 6 mm or nothing (the screen logo is 30 mm at minimum: 60 % of this label)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "labelprinter" / "designs"
DPM = 8
PX_PER_PT = DPM * 25.4 / 72

L, R, T, B = 2.5, 47.5, 2.5, 27.5     # live area
W = R - L
SEMI, MED, REG = "dm-sans-semibold", "dm-sans-medium", "dm-sans"
SYMBOL_W, SYMBOL_H = 6.0, 6.66        # the symbol at its 6 mm minimum, in its own proportions
CAP = 0.7                             # DM Sans cap height in em


def mm(dots: float) -> float:
    return round(dots / DPM, 3)


def cap_mm(pt: float) -> float:
    return pt * PX_PER_PT * CAP / DPM


def text(eid, content, font, pt, x, w, baseline, *, align="left", min_pt=None, upper=False):
    """A text line whose baseline is at `baseline` mm. The box is one em tall and ends on the baseline."""
    base = round(baseline * DPM)
    h = round(pt * PX_PER_PT)             # one em, in whole dots
    return {"id": eid, "type": "text", "content": content, "x": x, "y": mm(base - h), "w": w, "h": mm(h),
            "font": font, "size_pt": pt, "min_size_pt": min_pt or pt, "bold": False, "italic": False, "reverse": False,
            "upper": upper, "align": align, "valign": "baseline"}


def barcode(x, y, w, h):
    return {"id": "barcode", "type": "barcode", "content": "{sku}", "x": x, "y": y, "w": w, "h": h, "mode": "integer"}


def rule(y, x=L, w=W):
    return {"id": "rule", "type": "rect", "x": x, "y": y, "w": w, "h": 0.25}


def symbol(x, y):
    return {"id": "symbol", "type": "image", "src": "symbol", "x": x, "y": y, "w": SYMBOL_W, "h": SYMBOL_H}


def design(name, elements):
    return {"name": name, "width_mm": 50, "height_mm": 30, "gap_mm": 2, "direction": 1, "smooth_text": True, "elements": elements}


META = 12.0   # baseline of the meta line: the gap above each line's caps is 1.8-1.9 mm all the way down
SCAN_TOP, SCAN_H = 16.5, 7.5   # the barcode zone of the full-width layouts, 2.3 mm above the SKU line
PRICE_ROW = 13.0               # when the price shares the meta line it drops one step, so its caps clear the title line
PRICE_FOOT = 26.5              # a price on the last line sits 1 mm higher so the descender of the "p" stays inside the margin


def artist(x=L, w=W):
    return text("artist", "{artist}", SEMI, 12, x, w, 5.5, min_pt=6.5)


def title(x=L, w=W):
    return text("title", "{title}", REG, 8, x, w, 9.0, min_pt=5)


def ledger():
    """Type on top, a hairline, then the scan zone on the left and the money on the right."""
    barcode_top = 16.5
    price_baseline = round((barcode_top + cap_mm(10)) * 2) / 2
    return design("MF Brand · Ledger", [
        artist(), title(),
        text("meta", "{format}  {year}  {genre}", MED, 6, L, W, META, min_pt=5, upper=True),
        rule(14.25),
        barcode(L, barcode_top, 24, 8.0),
        text("price", "{price}", MED, 10, 28, R - 28, price_baseline, align="right", min_pt=7),
        text("sku", "{sku}", REG, 6, L, 24, B),
        symbol(R - SYMBOL_W, B - SYMBOL_H),
    ])


def barcode_foot():
    """No mark. The price rides the meta line, so the barcode gets the full width and real height."""
    return design("MF Brand · Barcode foot", [
        artist(), title(),
        text("meta", "{format}  {year}", MED, 6, L, 22, PRICE_ROW, min_pt=5, upper=True),
        text("price", "{price}", MED, 10, 24, R - 24, PRICE_ROW, align="right", min_pt=7),
        barcode(L, SCAN_TOP, W, SCAN_H),
        text("sku", "{sku}", REG, 6, L, 22, B),
        text("genre", "{genre}", MED, 6, 25.5, R - 25.5, B, align="right", min_pt=5, upper=True),
    ])


def symbol_column():
    """The symbol sets the text axis: the artist, title and meta line hang from its right edge."""
    x = L + SYMBOL_W + 2.0
    return design("MF Brand · Symbol column", [
        symbol(L, 9.0 - SYMBOL_H),
        artist(x, R - x), title(x, R - x),
        text("meta", "{format}  {year}  {genre}", MED, 6, x, R - x, META, min_pt=5, upper=True),
        barcode(L, SCAN_TOP - 1.0, W, 6.5),           # ends 2 mm above the caps of the price line
        text("sku", "{sku}", REG, 6, L, 22, PRICE_FOOT),
        text("price", "{price}", MED, 10, 24, R - 24, PRICE_FOOT, align="right", min_pt=7),
    ])


FILES = {"mf-brand-ledger": ledger, "mf-brand-barcode-foot": barcode_foot, "mf-brand-symbol-column": symbol_column}


def main() -> int:
    for slug, build in FILES.items():
        path = OUT / f"{slug}.json"
        path.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote", path.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
