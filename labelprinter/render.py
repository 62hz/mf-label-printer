"""Draw one label from a design as a 1-bit image, 8 dots per mm (203 dpi).

This image is the single source for the preview PNG, the PDF page and the printer bitmap, so what
you see is what prints. A design is a list of elements (text, barcode, rect, image) in millimetres;
see designs.py for the schema and labelprinter/designs/*.json for the built-in ones.
"""
import io
import math
import re
from functools import lru_cache
from pathlib import Path

from barcode import Code128
from barcode.errors import BarcodeError
from PIL import Image, ImageChops, ImageDraw, ImageFont

from . import designs, fonts
from .model import Label, price_text

DPM = 8                                  # dots per mm
PX_PER_PT = DPM * 25.4 / 72              # font size in points -> pixels at 203.2 dpi
THRESHOLD = 160                          # grey level below which a dot prints
GIVE_WAY = 4                             # dots of clear space a giving-way logo keeps from a barcode
FOLLOW_GAP = 8                           # dots between a barcode and the logo that follows it (1 mm)
SMOOTH = 4                               # scale of the copy that "smooth text" designs draw their text on
ASSETS = Path(__file__).resolve().parents[1] / "assets"
# Image elements pick one of the brand's logo files (Sara's artwork, used as supplied, never redrawn):
#   logo        the hand-drawn main logotype (signage, packaging; the old designs use it)
#   symbol      the hand-drawn stack of discs on its own (stickers, small spaces; at least 6 mm)
#   screen-logo the symbol + "Medium Format" set in DM Sans (small sizes and transactional documents; at least 30 mm wide)
LOGO_FILES = {"logo": "mf-logo-main-black-1200px.png", "symbol": "mf-symbol-black-1024px.png",
              "screen-logo": "mf-screen-logo-black-2400px.png"}
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@lru_cache(maxsize=256)
def _load(path: str, mtime_ns: int, size: int, px: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, px)


def font(path, px: float) -> ImageFont.FreeTypeFont:
    """The font file at `path` (from fonts.resolve) at `px` pixels, cached. A replaced file is picked up: the file's time and size are part of the key."""
    path = Path(path)
    st = path.stat()
    return _load(str(path), st.st_mtime_ns, st.st_size, px)


def dots(mm: float) -> int:
    return int(math.floor(mm * DPM + 0.5))


def size_dots(design: dict) -> tuple[int, int]:
    return design["width_mm"] * DPM, dots(design["height_mm"])


def values(label: Label) -> dict:
    return {"sku": label.sku, "artist": label.artist, "title": label.title, "format": label.format, "year": label.year,
            "genre": label.genre, "price": price_text(label.price) if label.price else "", "copies": str(label.copies)}


def expand(content: str, label: Label) -> str:
    vals = values(label)
    return _PLACEHOLDER.sub(lambda m: vals.get(m.group(1), ""), content).strip()


def fit(draw, text: str, path: Path, max_px: float, avail: int, min_px: float):
    """Shrink the font down to min_px, then cut the text and add '...' so it always fits `avail` dots.

    Candidate sizes are max_px, max_px - 0.5, ... clamped at min_px. Both searches are binary
    (text width only grows with size and with length), so a very long text costs a handful of
    measurements, not thousands."""
    floor_px = min(min_px, max_px)
    steps = max(0, math.ceil((max_px - floor_px) / 0.5))  # candidate i is max_px - i * 0.5

    def size(i: int) -> float:
        return max(floor_px, max_px - i * 0.5)

    def width(i: int) -> float:
        return draw.textlength(text, font=font(path, size(i)))

    if width(0) <= avail:
        return text, font(path, size(0))
    if width(steps) <= avail:
        lo, hi = 1, steps  # the smallest candidate that fits is in lo..hi, and hi fits
        while lo < hi:
            mid = (lo + hi) // 2
            if width(mid) <= avail:
                hi = mid
            else:
                lo = mid + 1
        return text, font(path, size(hi))
    f = font(path, size(steps))
    lo, hi = 0, len(text)  # the longest prefix whose width plus '...' fits is lo..hi
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if draw.textlength(text[:mid] + "...", font=f) <= avail:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + "...", f


LEADING = 1.15   # line spacing of wrapped text, in em


def _split(draw, words: list[str], f, avail: int) -> int:
    """How many leading words fit on one line (at least 1)."""
    n = 1
    while n < len(words) and draw.textlength(" ".join(words[:n + 1]), font=f) <= avail:
        n += 1
    return n


WRAP_AT = 0.8   # a line may shrink to 80 % of its size before it is allowed to wrap


def _wrap(draw, words: list[str], f, avail: int, lines: int):
    rows, rest = [], words
    while rest and len(rows) < lines - 1:
        n = _split(draw, rest, f, avail)
        rows.append(" ".join(rest[:n]))
        rest = rest[n:]
    return rows, rest


def fit_lines(draw, text: str, path: Path, max_px: float, avail: int, min_px: float, lines: int, max_h: int, flow: bool = False):
    """Like fit(), but a long text may break onto up to `lines` lines at word boundaries.

    One line is kept while it fits at WRAP_AT of the size or more. Then, from the full size down in 0.5 px steps,
    a size wins when the text fits on one line, or when it breaks onto up to `lines` lines that are each
    narrower than `avail` and together no taller than `max_h` (dots). At the smallest size the text is cut
    with '...'. Returns (rows, font)."""
    words = text.split()
    floor_px = min(min_px, max_px)
    sizes, px = [], max_px
    while True:
        sizes.append(px)
        if px <= floor_px:
            break
        px = max(floor_px, px - 0.5)

    def one(px):
        return draw.textlength(text, font=font(path, px)) <= avail

    for px in sizes:
        if px >= max_px * WRAP_AT and one(px):
            return [text], font(path, px)
    for px in sizes:
        if one(px):
            return [text], font(path, px)
        f = font(path, px)
        rows, rest = _wrap(draw, words, f, avail, lines)
        block = (0 if flow else f.getmetrics()[0]) + (len(rows) + (1 if rest else 0) - 1) * round(f.size * LEADING)
        if block > max_h:
            continue
        last = " ".join(rest)
        if all(draw.textlength(r, font=f) <= avail for r in rows) and (not rest or draw.textlength(last, font=f) <= avail):
            return rows + ([last] if rest else []), f
    f = font(path, floor_px)                     # nothing fits: smallest size, cut the end
    rows, rest = _wrap(draw, words, f, avail, lines)
    block = (0 if flow else f.getmetrics()[0]) + len(rows) * round(f.size * LEADING)
    if rest and block <= max_h:
        rows = [r if draw.textlength(r, font=f) <= avail else fit(draw, r, path, floor_px, avail, floor_px)[0] for r in rows]
        return rows + [fit(draw, " ".join(rest), path, floor_px, avail, floor_px)[0]], f
    return [fit(draw, text, path, floor_px, avail, floor_px)[0]], f


def bars(data: str) -> str:
    """Code128 modules as a '1'/'0' string."""
    if not data:
        raise ValueError("Barcode content is empty")
    try:
        return Code128(data).build()[0]
    except BarcodeError as exc:
        raise ValueError(f"{data!r} has characters Code128 cannot print") from exc


def _box(el: dict) -> tuple[int, int, int, int]:
    x0, y0 = dots(el["x"]), dots(el["y"])
    return x0, y0, x0 + max(1, dots(el["w"])), y0 + max(1, dots(el["h"]))


def _text(draw, el: dict, label: Label, k: int = 1, flow_y: int | None = None):
    """Draw one text element. k is the drawing scale: 1 draws straight onto the label, SMOOTH draws on the enlarged copy.

    valign "flow": the box top is the first baseline (or flow_y, the baseline handed on by the element this one
    follows), lines run downward, and the box bottom is the lowest baseline allowed. Returns the last baseline drawn,
    in drawing dots, so a following element can continue under it; None when nothing was drawn."""
    text = expand(el["content"], label)
    if text and el["first_item"]:
        text = text.split(",")[0].strip()
    if not text:
        text = el["blank"]
    if not text:
        return None
    if el["upper"]:
        text = text.upper()
    x0, y0, x1, y1 = (v * k for v in _box(el))
    if el["valign"] == "flow" and flow_y is not None:
        y0 = flow_y
    pad = 2 * k if el["reverse"] else 0
    path = fonts.resolve(el["font"], el["bold"], el["italic"])
    avail = max(1, x1 - x0 - 2 * pad)
    max_px, min_px = el["size_pt"] * PX_PER_PT * k, min(el["min_size_pt"], el["size_pt"]) * PX_PER_PT * k
    if el["lines"] > 1 and el["valign"] != "middle":
        rows, f = fit_lines(draw, text, path, max_px, avail, min_px, el["lines"], y1 - y0, flow=el["valign"] == "flow")
    else:
        rows, f = None, None
    if rows is None or len(rows) == 1:
        text, f = fit(draw, text, path, max_px, avail, min_px) if rows is None else (rows[0], f)
    if el["reverse"]:
        draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=0)
    ax = {"left": x0 + pad, "center": (x0 + x1) // 2, "right": x1 - pad}[el["align"]]
    h = {"left": "l", "center": "m", "right": "r"}[el["align"]]
    if rows is not None and len(rows) > 1:
        lead = round(f.size * LEADING)
        fill = 255 if el["reverse"] else 0
        for i, row in enumerate(rows):
            if el["valign"] == "baseline":   # the last line sits on the baseline, earlier lines above it
                draw.text((ax, y1 - (len(rows) - 1 - i) * lead), row, font=f, fill=fill, anchor=h + "s")
            elif el["valign"] == "flow":     # the first line sits on the first baseline, later lines below it
                draw.text((ax, y0 + i * lead), row, font=f, fill=fill, anchor=h + "s")
            else:
                draw.text((ax, y0 + i * lead), row, font=f, fill=fill, anchor=h + "a")
        return y0 + (len(rows) - 1) * lead if el["valign"] == "flow" else y1
    if el["valign"] == "flow":
        draw.text((ax, y0), text, font=f, fill=255 if el["reverse"] else 0, anchor=h + "s")
        return y0
    if el["valign"] == "middle":
        draw.text((ax, (y0 + y1) // 2), text, font=f, fill=255 if el["reverse"] else 0, anchor=h + "m")
    elif el["valign"] == "baseline":  # the bottom edge of the box is the baseline, so a text that shrinks to fit stays on its line
        draw.text((ax, y1), text, font=f, fill=255 if el["reverse"] else 0, anchor=h + "s")
    else:
        draw.text((ax, y0), text, font=f, fill=255 if el["reverse"] else 0, anchor=h + "a")
    return y1


def _barcode(draw, el: dict, label: Label) -> int:
    """Draw the bars from the left of the box; return how many dots long the drawn barcode is."""
    data = expand(el["content"], label)
    bits = bars(data)
    x0, y0, x1, y1 = _box(el)
    width, n = x1 - x0, len(bits)
    if width < n:
        raise ValueError(f"Barcode {data!r} needs at least {n / DPM:.1f} mm of width, the element is {el['w']} mm")
    scale = (width // n) if el["mode"] == "integer" else width / n
    i = 0
    while i < n:
        if bits[i] == "1":
            j = i
            while j < n and bits[j] == "1":
                j += 1
            a, b = x0 + math.floor(i * scale + 0.5), x0 + math.floor(j * scale + 0.5)
            draw.rectangle((a, y0, b - 1, y1 - 1), fill=0)
            i = j
        else:
            i += 1
    return math.floor(n * scale + 0.5)


@lru_cache(maxsize=16)
def _logo(src: str, w: int, h: int) -> Image.Image:
    logo = Image.open(ASSETS / LOGO_FILES[src]).convert("RGBA")
    if src != "logo":  # the old logo keeps its margin so the existing designs print exactly as before
        logo = logo.crop(logo.getchannel("A").getbbox() or (0, 0, *logo.size))  # trim the file's empty margin: the box is the artwork
    white = Image.new("RGBA", logo.size, (255, 255, 255, 255))
    white.alpha_composite(logo)
    flat = white.convert("L")
    scale = min(w / flat.width, h / flat.height)
    return flat.resize((max(1, round(flat.width * scale)), max(1, round(flat.height * scale))), Image.LANCZOS)


def render(label: Label, design: dict) -> Image.Image:
    design = designs.validate(design)
    width, height = size_dots(design)
    img = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(img)
    smooth = design["smooth_text"]
    if smooth:  # text drawn on a SMOOTH-times copy and shrunk keeps even letter spacing at small sizes; the barcode and boxes stay on whole dots
        big = Image.new("L", (width * SMOOTH, height * SMOOTH), 255)
        big_draw = ImageDraw.Draw(big)
    taken = []  # where barcodes really printed: a logo that gives way is left out when it would touch one
    last_base = {}  # element id -> last baseline drawn, in label dots, for text that follows it
    for el in design["elements"]:
        if not el["visible"]:
            continue
        if el["type"] == "text":
            k = SMOOTH if smooth else 1
            flow_y = None
            if el["after"] and last_base.get(el["after"]) is not None:
                flow_y = round((last_base[el["after"]] + el["after_gap"] * DPM) * k)
            end = _text(big_draw if smooth else draw, el, label, k, flow_y)
            last_base[el["id"]] = None if end is None else end / k
        elif el["type"] == "barcode" and el["rotate"] == 90:
            # bars lying down along the box height: draw upright on a turned box, then turn it a quarter clockwise
            x0, y0, x1, y1 = _box(el)
            upright = Image.new("L", (y1 - y0, x1 - x0), 255)
            length = _barcode(ImageDraw.Draw(upright), dict(el, x=0, y=0, w=el["h"], h=el["w"]), label)
            span, offset = y1 - y0, 0
            if el["center"]:  # centred in the box, or in the box less its reserve (room kept for a logo) when it fits there
                reserve = dots(el["reserve"])
                room = span - reserve if length <= span - reserve else span
                offset = (room - length) // 2
            img.paste(upright.rotate(-90, expand=True).crop((0, 0, x1 - x0, length)), (x0, y0 + offset))
            taken.append((x0, y0 + offset, x1, y0 + offset + length))
        elif el["type"] == "barcode":
            x0, y0, x1, y1 = _box(el)
            taken.append((x0, y0, x0 + _barcode(draw, el, label), y1))
        elif el["type"] == "rect" and smooth:
            # on the text copy, so white text placed on a black box stays white (edges stay on whole dots: k-times coordinates)
            x0, y0, x1, y1 = (v * SMOOTH for v in _box(el))
            big_draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=0)
        elif el["type"] == "rect":
            x0, y0, x1, y1 = _box(el)
            draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=0)
        elif el["type"] == "image":
            x0, y0, x1, y1 = _box(el)
            logo = _logo(el["src"], x1 - x0, y1 - y0)
            px, py = x0 + (x1 - x0 - logo.width) // 2, y0 + (y1 - y0 - logo.height) // 2
            if el["gives_way"]:
                # the logo sits at the top of its box, or just below a barcode that runs into the box;
                # when the barcode leaves no room for it, it is left out
                py = y0
                for bx0, by0, bx1, by1 in taken:
                    if px < bx1 + GIVE_WAY and bx0 - GIVE_WAY < px + logo.width and py < by1 + GIVE_WAY and by0 - GIVE_WAY < py + logo.height:
                        py = by1 + FOLLOW_GAP
                if py + logo.height > y1:
                    continue
            img.paste(logo, (px, py))
    if smooth:
        img = ImageChops.darker(img, big.resize((width, height), Image.LANCZOS))
    return img.point(lambda v: 255 if v >= THRESHOLD else 0).convert("1")


def notes(label: Label, design: dict) -> list[str]:
    """Plain-language warnings for the designer: barcode scanning first, then any font that is not exactly what the design asks for."""
    out = []
    elements = designs.validate(design)["elements"]
    for el in elements:
        if el["type"] != "barcode" or not el["visible"]:
            continue
        data = expand(el["content"], label)
        if not data:
            continue
        n = len(bars(data))
        x0, y0, x1, y1 = _box(el)
        width = (y1 - y0) if el["rotate"] == 90 else (x1 - x0)  # the length the bars are spread along
        if width < n:
            continue  # render() reports this one as an error
        if el["mode"] == "integer":
            mod = width // n
            if mod == 1:
                out.append("Barcode bars are 1 dot (0.125 mm). Imaging scanners read this; some laser scanners need 2 dots. "
                           f"For 2 dots make the barcode {2 * n / DPM:.1f} mm wide.")
        else:
            scale = width / n
            if abs(scale - round(scale)) > 0.01:
                out.append(f"Stretched barcode: bars vary between {math.floor(scale)} and {math.ceil(scale)} dots. "
                           "Some scanners cannot read this. Use mode 'integer' for a scan-safe barcode.")
    for el in elements:
        if el["type"] == "text" and el["visible"]:
            message = fonts.status(el["font"], el["bold"], el["italic"])
            if message and message not in out:
                out.append(message)
    return out


def png_bytes(label: Label, design: dict) -> bytes:
    buf = io.BytesIO()
    render(label, design).save(buf, "PNG")
    return buf.getvalue()
