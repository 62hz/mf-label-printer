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
SEMI, MED, REG, LIGHT = "dm-sans-semibold", "dm-sans-medium", "dm-sans", "dm-sans-light"
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


def artist_at(baseline, x=L, w=W, pt=12, min_pt=6.5, lines=1, top=None):
    return text("artist", "{artist}", SEMI, pt, x, w, baseline, min_pt=min_pt, lines=lines, top=top)


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


MONO, MONO_REG = "dm-mono-medium", "dm-mono"


def ellipse(eid, x, y, w, h, *, fill="none", stroke=0.125, rings=0, ring_gap=0.5):
    return {"id": eid, "type": "ellipse", "x": x, "y": y, "w": w, "h": h, "fill": fill, "stroke": stroke,
            "rings": rings, "ring_gap": ring_gap}


def stamp():
    """After Japanese postage stamps: a perforated edge, a printed hairline border, a vignette (a record, grooves and label),
    the price as the denomination, and a postmark that overlaps the vignette and carries the year.

    Left: the record and its postmark. Right: price, a rule, artist and title. Foot: format, genre, SKU, then the barcode."""
    frame = 1.3
    xi0, xi1, yi0, yi1 = L + frame, R - frame, T + frame, B - frame      # the printed border, inside the perforation
    disc = 11.5
    cx = cy = 5.2 + disc / 2
    pm = 7.0                                                         # postmark diameter
    pcx = pcy = 15.4
    rx = 19.5                                                        # the right column
    rw = xi1 - 0.8 - rx
    hair = 0.125
    return design("MF Stamp", [
        {"id": "perforation", "type": "perforation", "x": L, "y": T, "w": W, "h": B - T, "pitch": 1.25, "radius": 0.4, "stroke": hair},
        line("in-top", xi0, yi0, xi1 - xi0, hair), line("in-bottom", xi0, yi1 - hair, xi1 - xi0, hair),
        line("in-left", xi0, yi0, hair, yi1 - yi0), line("in-right", xi1 - hair, yi0, hair, yi1 - yi0),
        # the vignette: a record with grooves, a black label and a spindle hole
        ellipse("disc", 5.2, 5.2, disc, disc, rings=7, ring_gap=0.5),
        ellipse("disc-label", round(cx - 1.7, 2), round(cy - 1.7, 2), 3.4, 3.4, fill="black", stroke=0),
        ellipse("disc-hole", round(cx - 0.3, 2), round(cy - 0.3, 2), 0.6, 0.6, fill="white", stroke=0),
        # the postmark over the vignette's corner: a white double ring with the year in it
        ellipse("postmark", round(pcx - pm / 2, 2), round(pcy - pm / 2, 2), pm, pm, fill="white", stroke=hair, rings=1, ring_gap=0.4),
        text("pm-name", "MF", SEMI, 6.5, pcx - 2.8, 5.6, pcy - 0.5, align="center", min_pt=5),
        text("pm-year", "{year}", MED, 5, pcx - 2.8, 5.6, pcy + 1.6, align="center", min_pt=4, blank="–"),
        # the denomination, a rule, then the name
        text("price", "{price}", SEMI, 11, rx, rw, 8.8, align="right", min_pt=7),
        line("rule", rx, 10.0, rw, hair),
        flow("artist", "{artist}", SEMI, 8, rx, rw, 12.7, 15.9, min_pt=6.5),
        flow("title", "{title}", MED, 6.5, rx, rw, 12.7, 18.6, min_pt=5.5, after="artist", gap=2.7),
        # the foot line, then the barcode
        text("format", "{format}", SEMI, 5.5, 5.2, 9.0, 20.7, upper=True, min_pt=4.5, blank="–"),
        text("genre", "{genre}", MED, 5.5, 15.0, 13.0, 20.7, upper=True, first_item=True, min_pt=4.5, blank="–"),
        text("sku", "{sku}", MONO, 5, 28.5, xi1 - 0.8 - 28.5, 20.7, align="right", min_pt=4.5),
        barcode(5.2, 22.0, xi1 - 0.8 - 5.2, 3.4),
    ])


def passport():
    """After old passports: tiny capital labels over every value, the seal beside the price, and the two machine-readable
    lines (36 characters each, like an ID card) at the foot, carrying the artist and title, then SKU, format, year and price."""
    inset_r = W - MINI_W
    col = 31.5                                   # the price column
    return design("MF Passport", [
        text("l-name", "Artist / Title", REG, 4.5, L, 28, 4.8, upper=True),
        flow("artist", "{artist}", SEMI, 8, L, col - L - 1.2, 7.8, 10.8, min_pt=6.5),
        flow("title", "{title}", MED, 6.8, L, col - L - 1.2, 7.8, 13.4, min_pt=5.5, after="artist", gap=2.6),
        text("l-price", "Price", REG, 4.5, col, R - col, 4.8, upper=True, align="right"),
        text("price", "{price}", SEMI, 10, col, R - col, 8.4, align="right", min_pt=6),
        {"id": "symbol", "type": "image", "src": "symbol", "x": round(R - MINI_W, 2), "y": 9.6, "w": MINI_W, "h": MINI_H},
        text("l-format", "Format", REG, 4.5, L, 10, 16.4, upper=True),
        text("format", "{format}", MED, 6.5, L, 10, 18.7, upper=True, min_pt=5, blank="–"),
        text("l-year", "Year", REG, 4.5, 13.0, 8, 16.4, upper=True),
        text("year", "{year}", MED, 6.5, 13.0, 8, 18.7, min_pt=5, blank="–"),
        text("l-genre", "Genre", REG, 4.5, 21.5, 26, 16.4, upper=True),
        text("genre", "{genre}", MED, 6.5, 21.5, 26, 18.7, min_pt=5, first_item=True, blank="–"),
        barcode(L, 19.7, W, 3.9),
        text("mrz1", "R<MFX{artist}<<{title}", MONO_REG, 5.9, L, W, 25.3, min_pt=4.5, mrz=36),
        text("mrz2", "{sku}<{format}<{year}<{price}", MONO_REG, 5.9, L, W, 27.4, min_pt=4.5, mrz=36),
    ])


FILES = {"mf-brand-ledger": ledger, "mf-brand-barcode-foot": barcode_foot, "mf-brand-symbol-column": symbol_column,
         "mf-concept-catalogue-line": catalogue_line, "mf-concept-price-card": price_card, "mf-concept-format-tile": format_tile,
         "mf-stamp": stamp, "mf-passport": passport}


def main() -> int:
    for slug, build in FILES.items():
        path = OUT / f"{slug}.json"
        path.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote", path.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
