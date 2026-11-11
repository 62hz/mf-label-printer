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
from PIL import Image, ImageDraw, ImageFont

from . import designs, fonts
from .model import Label, price_text

DPM = 8                                  # dots per mm
PX_PER_PT = DPM * 25.4 / 72              # font size in points -> pixels at 203.2 dpi
THRESHOLD = 160                          # grey level below which a dot prints
LOGO_FILE = Path(__file__).resolve().parents[1] / "assets" / "mf-logo-main-black-1200px.png"
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


def _text(draw, el: dict, label: Label) -> None:
    text = expand(el["content"], label)
    if not text:
        return
    x0, y0, x1, y1 = _box(el)
    pad = 2 if el["reverse"] else 0
    path = fonts.resolve(el["font"], el["bold"], el["italic"])
    text, f = fit(draw, text, path, el["size_pt"] * PX_PER_PT, max(1, x1 - x0 - 2 * pad), min(el["min_size_pt"], el["size_pt"]) * PX_PER_PT)
    if el["reverse"]:
        draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=0)
    ax = {"left": x0 + pad, "center": (x0 + x1) // 2, "right": x1 - pad}[el["align"]]
    h = {"left": "l", "center": "m", "right": "r"}[el["align"]]
    if el["valign"] == "middle":
        draw.text((ax, (y0 + y1) // 2), text, font=f, fill=255 if el["reverse"] else 0, anchor=h + "m")
    else:
        draw.text((ax, y0), text, font=f, fill=255 if el["reverse"] else 0, anchor=h + "a")


def _barcode(draw, el: dict, label: Label) -> None:
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


@lru_cache(maxsize=8)
def _logo(w: int, h: int) -> Image.Image:
    logo = Image.open(LOGO_FILE).convert("RGBA")
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
    for el in design["elements"]:
        if not el["visible"]:
            continue
        if el["type"] == "text":
            _text(draw, el, label)
        elif el["type"] == "barcode":
            _barcode(draw, el, label)
        elif el["type"] == "rect":
            x0, y0, x1, y1 = _box(el)
            draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=0)
        elif el["type"] == "image":
            x0, y0, x1, y1 = _box(el)
            logo = _logo(x1 - x0, y1 - y0)
            img.paste(logo, (x0 + (x1 - x0 - logo.width) // 2, y0 + (y1 - y0 - logo.height) // 2))
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
        width = _box(el)[2] - _box(el)[0]
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
