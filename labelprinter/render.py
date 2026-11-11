"""Draw one label from a design as a 1-bit image, 8 dots per mm (203 dpi).

This image is the single source for the preview PNG, the PDF page and the printer bitmap, so what
you see is what prints. A design is a list of elements (text, barcode, rect, image) in millimetres;
see designs.py for the schema and labelprinter/designs/*.json for the built-in ones.
"""
import io
import math
import os
import re
from functools import lru_cache
from pathlib import Path

from barcode import Code128
from barcode.errors import BarcodeError
from PIL import Image, ImageDraw, ImageFont

from . import designs
from .model import Label, price_text

DPM = 8                                  # dots per mm
PX_PER_PT = DPM * 25.4 / 72              # font size in points -> pixels at 203.2 dpi
THRESHOLD = 160                          # grey level below which a dot prints
FONT_DIR = Path(os.environ.get("LABEL_FONT_DIR", "C:/Windows/Fonts"))
LOGO_FILE = Path(__file__).resolve().parents[1] / "assets" / "mf-logo-main-black-1200px.png"
FONT_FILES = {  # family -> regular, bold, italic, bold italic
    "arial": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "calibri": ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
    "times": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "verdana": ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
    "tahoma": ("tahoma.ttf", "tahomabd.ttf", "tahoma.ttf", "tahomabd.ttf"),
    "courier": ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
}
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def available_fonts() -> list[str]:
    return [fam for fam, files in FONT_FILES.items() if all((FONT_DIR / f).exists() for f in files)]


def font_file(family: str, bold: bool, italic: bool) -> str:
    return FONT_FILES[family][(1 if bold else 0) + (2 if italic else 0)]


@lru_cache(maxsize=256)
def font(name: str, px: float) -> ImageFont.FreeTypeFont:
    path = FONT_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Font {path} not found. Set LABEL_FONT_DIR to a folder holding {name}.")
    return ImageFont.truetype(str(path), px)


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


def fit(draw, text: str, name: str, max_px: float, avail: int, min_px: float):
    """Shrink the font down to min_px, then cut the text and add '...' so it always fits `avail` dots."""
    px = max_px
    while px > min_px and draw.textlength(text, font=font(name, px)) > avail:
        px -= 0.5
    f = font(name, px)
    if draw.textlength(text, font=f) > avail:
        while text and draw.textlength(text + "...", font=f) > avail:
            text = text[:-1]
        text = text.rstrip() + "..."
    return text, f


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
    name = font_file(el["font"], el["bold"], el["italic"])
    text, f = fit(draw, text, name, el["size_pt"] * PX_PER_PT, max(1, x1 - x0 - 2 * pad), min(el["min_size_pt"], el["size_pt"]) * PX_PER_PT)
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
    """Plain-language warnings for the designer about barcode scanning."""
    out = []
    for el in designs.validate(design)["elements"]:
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
    return out


def png_bytes(label: Label, design: dict) -> bytes:
    buf = io.BytesIO()
    render(label, design).save(buf, "PNG")
    return buf.getvalue()
