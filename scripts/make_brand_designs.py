"""Write the two MF label designs that are built from a grid, so every position is derived, never typed by eye.

  uv run python scripts/make_brand_designs.py

  mf-passport-row     the default: MF Passport, symbol left (the symbol and a flush-right barcode on one row,
                      two machine-readable lines in DM Mono at the foot)
  mf-concept-price-card   the Price card: a closed ruled form, the barcode standing up the left edge

The system (50 x 30 mm label, 8 dots per mm):
  margins     2.5 mm on all four sides: the live area is x 2.5-47.5, y 2.5-27.5
  baselines   text boxes are anchored on a baseline (valign "baseline"), so a line that shrinks to fit stays on its line
  type        DM Sans (Regular, Medium, SemiBold) and DM Mono for the machine-readable lines
Older designs (Ledger, Barcode foot, Symbol column, Catalogue line, Format tile, Stamp, the other Passport placements)
were removed on 2026-11-12; they are in git history (commit ad8aa1a and before).
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
MINI_W, MINI_H = 3.15, 3.5            # the small symbol in the Price card header corner (Django's call, below the guide's 6 mm)
CAP = 0.7                             # DM Sans cap height in em


def mm(dots: float) -> float:
    return round(dots / DPM, 3)


def cap_mm(pt: float) -> float:
    return pt * PX_PER_PT * CAP / DPM


def text(eid, content, font, pt, x, w, baseline, *, align="left", min_pt=None, upper=False, lines=1, top=None,
         blank="", first_item=False, mrz=0):
    """A text line whose baseline is at `baseline` mm. The box is one em tall and ends on the baseline;
    a text that may wrap gets a box from `top` down to the baseline, the room its lines must fit in."""
    base = round(baseline * DPM)
    h = round(pt * PX_PER_PT) if top is None else base - round(top * DPM)
    el = {"id": eid, "type": "text", "content": content, "x": x, "y": mm(base - h), "w": w, "h": mm(h),
          "font": font, "size_pt": pt, "min_size_pt": min_pt or pt, "bold": False, "italic": False, "reverse": False,
          "upper": upper, "lines": lines, "align": align, "valign": "baseline",
          "blank": blank, "first_item": first_item}
    if mrz:
        el["mrz"] = mrz
    return el


def barcode(x, y, w, h):
    return {"id": "barcode", "type": "barcode", "content": "{sku}", "x": x, "y": y, "w": w, "h": h, "mode": "integer"}


def design(name, elements):
    return {"name": name, "width_mm": 50, "height_mm": 30, "gap_mm": 2, "direction": 1, "smooth_text": True, "elements": elements}


def line(eid, x, y, w, h):
    return {"id": eid, "type": "rect", "x": x, "y": y, "w": w, "h": h}


def flow(eid, content, font, pt, x, w, first_baseline, last_baseline, *, min_pt=None, lines=2, after="", gap=0.0):
    """Text whose first line sits on `first_baseline` (or `gap` mm under the element named in `after`) and runs down,
    no lower than `last_baseline`."""
    return {"id": eid, "type": "text", "content": content, "x": x, "y": first_baseline, "w": w,
            "h": round(last_baseline - first_baseline, 3), "font": font, "size_pt": pt, "min_size_pt": min_pt or pt,
            "bold": False, "italic": False, "reverse": False, "upper": False, "lines": lines, "align": "left",
            "valign": "flow", "after": after, "after_gap": gap}


def price_card():
    """After Disk Union's used-record price card: a closed ruled form, the barcode standing up the left edge.

    One grid on every record: header 12.5 mm (artist, then the title flowing under it), a cell row 5 mm
    (format, year, genre), a last row 7.5 mm (SKU, price). The frame is 2 dots, the inner rules 1 dot,
    and the cell dividers line up across rows. Empty fields print an en dash."""
    col = L + 6.5                      # the vertical rule right of the barcode column
    x0 = col + 0.25                    # inside the frame
    x1 = R - 0.25
    inset = 0.8
    xi, wi = x0 + inset, x1 - x0 - 2 * inset
    head, cells = 15.0, 20.0           # inner row lines
    f_end, y_end = x0 + 11.0, x0 + 18.0  # FORMAT 11 mm, YEAR 7 mm, GENRE the rest; the SKU cell ends where YEAR ends
    frame, hair = 0.25, 0.125
    label_base = lambda row_top: round(row_top + hair + 0.6 + cap_mm(4.5), 2)

    def label_(eid, words, x, base):
        return text(eid, words, REG, 4.5, x + inset, 12, base, upper=True)

    def value(eid, content, x, x_end, base, pt=6.5, **kw):
        return text(eid, content, MED, pt, x + inset, x_end - x - 2 * inset, base, **kw)

    return design("MF Price card", [
        # barcode column: the bars centred in the column (whole dots per bar, so their length follows the SKU)
        {"id": "barcode", "type": "barcode", "content": "{sku}", "x": L, "y": T, "w": 5.5, "h": B - T, "mode": "integer",
         "rotate": 90, "center": True},
        # the symbol in the header's top-right corner, on the artist's cap height: the same place on every label
        {"id": "symbol", "type": "image", "src": "symbol", "x": round(x1 - inset - MINI_W, 2), "y": round(T + frame + 0.6, 2),
         "w": MINI_W, "h": MINI_H},
        # the frame (2 dots) and the inner rules (1 dot)
        line("frame-left", col, T, frame, B - T), line("frame-top", col, T, R - col, frame),
        line("frame-bottom", col, B - frame, R - col, frame), line("frame-right", R - frame, T, frame, B - T),
        line("rule-head", x0, head, x1 - x0, hair), line("rule-cells", x0, cells, x1 - x0, hair),
        line("div-format", f_end, head, hair, cells - head), line("div-year", y_end, head, hair, cells - head),
        line("div-price", y_end, cells, hair, B - frame - cells),
        # header: artist, then the title right under its last line
        flow("artist", "{artist}", SEMI, 9, xi, round(wi - MINI_W - 1.0, 2), T + frame + 0.6 + cap_mm(9), 9.5, min_pt=7),
        flow("title", "{title}", MED, 7, xi, wi, 9.0, head - 0.8, min_pt=6, after="artist", gap=3.2),
        # cells
        label_("l-format", "Format", x0, label_base(head)), value("format", "{format}", x0, f_end, cells - 0.8, min_pt=5, upper=True, blank="–"),
        label_("l-year", "Year", f_end, label_base(head)), value("year", "{year}", f_end, y_end, cells - 0.8, min_pt=5.5, blank="–"),
        label_("l-genre", "Genre", y_end, label_base(head)), value("genre", "{genre}", y_end, x1, cells - 0.8, min_pt=5.5, first_item=True, blank="–"),
        label_("l-sku", "SKU", x0, label_base(cells)), value("sku", "{sku}", x0, y_end, B - frame - 1.0, pt=6, min_pt=4.5),
        text("price", "{price}", SEMI, 10, y_end + inset, x1 - y_end - 2 * inset, B - frame - 1.0, align="right", min_pt=7),
    ])


MONO, MONO_REG = "dm-mono-medium", "dm-mono"


def passport_row():
    """MF Passport, symbol left. Values only (no tiny labels); a 4.5 mm symbol on the barcode's row at the left, the barcode flush
    right (it flips flush left, and the symbol gives way, when its bars need the whole width to stay 2 dots wide); the genre
    flush right; two 36-character machine-readable lines at the foot (artist and title, then SKU, format, year and price)."""
    col = 31.5                                   # the price column
    fields = 13.8                                # baseline of the fields row
    size = 4.5                                   # the symbol, in mm wide
    sh = round(size * SYMBOL_H / SYMBOL_W, 2)
    tw = col - L - 1.2
    return design("MF Passport · symbol left", [
        flow("artist", "{artist}", SEMI, 8, L, tw, 4.6, 7.6, min_pt=6.5),
        flow("title", "{title}", MED, 6.8, L, tw, 4.6, 10.2, min_pt=5.5, after="artist", gap=2.6),
        text("price", "{price}", SEMI, 10, col, R - col, 5.1, align="right", min_pt=6),
        text("format", "{format}", MED, 6.5, L, 10, fields, upper=True, min_pt=5, blank="–"),
        text("year", "{year}", MED, 6.5, 14.0, 8, fields, min_pt=5, blank="–"),
        text("genre", "{genre}", MED, 6.5, 22.5, 25, fields, min_pt=5, first_item=True, blank="–", align="right"),
        dict(barcode(L, 15.5, W, 6.75), reserve=round(size + 2.5, 2), align="right"),
        {"id": "symbol", "type": "image", "src": "symbol", "x": L, "y": round(15.5 + (6.75 - sh) / 2, 2), "w": size, "h": sh, "gives_way": True},
        text("mrz1", "R<MFX{artist}<<{title}", MONO_REG, 5.9, L, W, 25.3, min_pt=4.5, mrz=36),
        text("mrz2", "{sku}<{format}<{year}<{price}", MONO_REG, 5.9, L, W, 27.4, min_pt=4.5, mrz=36),
    ])


FILES = {"mf-concept-price-card": price_card, "mf-passport-row": passport_row}


def main() -> int:
    for slug, build in FILES.items():
        path = OUT / f"{slug}.json"
        path.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote", path.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
