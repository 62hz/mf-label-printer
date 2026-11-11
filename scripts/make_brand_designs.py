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


def chip(eid, content, font, pt, x, y, w, h, *, min_pt=None, upper=False, align="center"):
    """White text on a black box (the box is the element)."""
    return {"id": eid, "type": "text", "content": content, "x": x, "y": y, "w": w, "h": h, "font": font, "size_pt": pt,
            "min_size_pt": min_pt or pt, "bold": False, "italic": False, "reverse": True, "upper": upper,
            "align": align, "valign": "middle"}


def line(eid, x, y, w, h):
    return {"id": eid, "type": "rect", "x": x, "y": y, "w": w, "h": h}


def catalogue_line():
    """After Hard Wax, Yoyaku and Honest Jon's: the catalogue line on top, artist and title as the headline,
    and format and price fused into one ticket, the single black element."""
    tx, tw = 28.5, R - 28.5
    return design("MF Concept · Catalogue line", [
        text("sku", "{sku}", MED, 6, L, 20, 4.5),
        text("meta", "{year}  {genre}", MED, 6, 22.5, R - 22.5, 4.5, align="right", min_pt=5, upper=True),
        rule(5.5),
        artist_at(10.0),
        text("title", "{title}", REG, 8, L, W, 13.5, min_pt=5),
        barcode(L, 18.5, 24, 9.0),
        line("ticket", tx, 16.5, tw, 11.0),
        chip("format", "{format}", MED, 6, tx + 1.0, 17.5, tw - 2.0, 3.0, min_pt=5, upper=True, align="left"),
        chip("price", "{price}", MED, 10, tx + 1.0, 22.0, tw - 2.0, 4.5, min_pt=7, align="left"),
    ])


def artist_at(baseline, x=L, w=W, pt=12):
    return text("artist", "{artist}", SEMI, pt, x, w, baseline, min_pt=6.5)


def price_card():
    """After Disk Union's used-record price card: a ruled form with named cells, the barcode standing up the left edge."""
    col = L + 6.5                      # right edge of the barcode column
    c = col + 0.5                      # left edge of the cells
    pad = 0.8
    r1, r2, r3 = 9.0, 15.0, 21.0       # row lines
    f_end, y_end = 23.0, 32.0          # cell lines in the format row
    p_start = 30.0                     # cell line in the last row

    def label_(eid, words, x, base):
        return text(eid, words, MED, 5, x + pad, 12, base, upper=True)

    return design("MF Price card", [
        {"id": "barcode", "type": "barcode", "content": "{sku}", "x": L, "y": T, "w": 5.5, "h": B - T, "mode": "integer", "rotate": 90},
        line("col", col, T, 0.25, B - T),
        line("r1", c, r1, R - c, 0.25), line("r2", c, r2, R - c, 0.25), line("r3", c, r3, R - c, 0.25),
        line("v-format", f_end, r2, 0.25, r3 - r2), line("v-year", y_end, r2, 0.25, r3 - r2), line("v-price", p_start, r3, 0.25, B - r3),
        label_("l-artist", "Artist", c, T + 2.0), artist_at(r1 - 1.0, c + pad, R - c - 2 * pad, pt=10),
        label_("l-title", "Title", c, r1 + 2.0), text("title", "{title}", REG, 8, c + pad, R - c - 2 * pad, r2 - 1.0, min_pt=5),
        label_("l-format", "Format", c, r2 + 2.0), text("format", "{format}", MED, 8, c + pad, f_end - c - 2 * pad, r3 - 1.0, min_pt=5, upper=True),
        label_("l-year", "Year", f_end, r2 + 2.0), text("year", "{year}", MED, 8, f_end + pad, y_end - f_end - 2 * pad, r3 - 1.0, min_pt=5),
        label_("l-genre", "Genre", y_end, r2 + 2.0), text("genre", "{genre}", REG, 8, y_end + pad, R - y_end - 2 * pad, r3 - 1.0, min_pt=5),
        label_("l-sku", "SKU", c, r3 + 2.0), text("sku", "{sku}", REG, 6, c + pad, p_start - c - 2 * pad, B - 1.0, min_pt=5),
        label_("l-price", "Price", p_start, r3 + 2.0), text("price", "{price}", MED, 10, p_start + pad, R - p_start - pad, B - 1.0, align="right", min_pt=7),
    ])


def format_tile():
    """Medium Format's own idea: the format is the hero mark, a black tile like an element in a periodic table."""
    x = L + 11.0 + 2.0
    return design("MF Concept · Format tile", [
        line("tile", L, T, 11.0, 11.0),                # the tile stays whole when the year is empty
        chip("format", "{format}", SEMI, 12, L, T, 11.0, 8.0, min_pt=5, upper=True),
        chip("year", "{year}", MED, 6, L, T + 8.0, 11.0, 3.0, min_pt=5),
        artist_at(5.5, x, R - x),
        text("title", "{title}", REG, 8, x, R - x, 9.0, min_pt=5),
        text("genre", "{genre}", MED, 6, x, R - x, T + 11.0, min_pt=5, upper=True),
        barcode(L, 16.5, W, 6.5),
        text("sku", "{sku}", REG, 6, L, 22, PRICE_FOOT),
        text("price", "{price}", MED, 10, 24, R - 24, PRICE_FOOT, align="right", min_pt=7),
    ])


FILES = {"mf-brand-ledger": ledger, "mf-brand-barcode-foot": barcode_foot, "mf-brand-symbol-column": symbol_column,
         "mf-concept-catalogue-line": catalogue_line, "mf-concept-price-card": price_card, "mf-concept-format-tile": format_tile}


def main() -> int:
    for slug, build in FILES.items():
        path = OUT / f"{slug}.json"
        path.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote", path.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
