"""TSPL print jobs for the XP-TT426B: header, then one bitmap + PRINT per label row.

LABELPRINTER_INVERT=1 is the one hardware switch to set after the first test print if black and
white come out swapped. Gap and direction live in each design (gap_mm, direction).
"""
import os

from PIL import Image, ImageDraw

from . import designs
from .model import Label
from .render import font, render

INVERT = os.environ.get("LABELPRINTER_INVERT") == "1"
TEST_W, TEST_H = 400, 240  # the test labels are always 50 x 30 mm

SCAN_TEST = {
    "name": "Scan test", "width_mm": 50, "height_mm": 30, "gap_mm": 2, "direction": 1,
    "elements": [
        {"id": "t0", "type": "text", "content": "SCAN TEST  AMEAMET158", "x": 2, "y": 1, "w": 46, "h": 3, "size_pt": 6, "bold": True},
        {"id": "a", "type": "barcode", "content": "AMEAMET158", "x": 2.6, "y": 5, "w": 18.1, "h": 4.5, "mode": "integer"},
        {"id": "ta", "type": "text", "content": "A  1 dot", "x": 22, "y": 6.5, "w": 20, "h": 3, "size_pt": 6},
        {"id": "b", "type": "barcode", "content": "AMEAMET158", "x": 2.6, "y": 11.5, "w": 23, "h": 4.5, "mode": "fit"},
        {"id": "tb", "type": "text", "content": "B  stretched", "x": 27.5, "y": 13, "w": 20, "h": 3, "size_pt": 6},
        {"id": "c", "type": "barcode", "content": "AMEAMET158", "x": 2.6, "y": 18, "w": 36.6, "h": 4.5, "mode": "integer"},
        {"id": "tc", "type": "text", "content": "C  2 dots", "x": 40, "y": 19.5, "w": 9.5, "h": 3, "size_pt": 5},
        {"id": "t9", "type": "text", "content": "Scan A, B and C. Note which read.", "x": 2, "y": 25, "w": 46, "h": 3, "size_pt": 5},
    ],
}


def _bitmap(img: Image.Image, invert: bool) -> bytes:
    """Pillow mode '1' packs 1 = white, which is what TSPL BITMAP mode 0 expects (0 = printed dot)."""
    raw = img.tobytes()
    return bytes(b ^ 0xFF for b in raw) if invert else raw


def _header(width_mm, height_mm, gap_mm, direction) -> bytes:
    return f"SIZE {width_mm:g} mm,{height_mm:g} mm\r\nGAP {gap_mm:g} mm,0 mm\r\nDIRECTION {direction}\r\n".encode("ascii")


def _page(img: Image.Image, copies: int, invert: bool) -> bytes:
    return (b"CLS\r\n" + f"BITMAP 0,0,{img.width // 8},{img.height},0,".encode("ascii") + _bitmap(img, invert)
            + f"\r\nPRINT 1,{copies}\r\n".encode("ascii"))


def job(labels: list[Label], design: dict, invert: bool = INVERT) -> bytes:
    """One header from the design, then each label row as its own bitmap printed `copies` times."""
    design = designs.validate(design)
    out = bytearray(_header(design["width_mm"], design["height_mm"], design["gap_mm"], design["direction"]))
    for label in labels:
        out += _page(render(label, design), label.copies, invert)
    return bytes(out)


def orientation_image() -> Image.Image:
    """Border, a thick bar on the LEFT edge, 'TOP' with an up arrow: shows direction, inversion, gap and clipping."""
    img = Image.new("L", (TEST_W, TEST_H), 255)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, TEST_W - 1, TEST_H - 1), outline=0, width=3)
    d.rectangle((0, 0, 30, TEST_H - 1), fill=0)
    d.text((TEST_W // 2, 40), "TOP", font=font("arialbd.ttf", 36), fill=0, anchor="mm")
    d.polygon([(TEST_W // 2, 8), (TEST_W // 2 - 14, 22), (TEST_W // 2 + 14, 22)], fill=0)
    d.text((TEST_W // 2, 120), "XP-TT426B TEST", font=font("arialbd.ttf", 26), fill=0, anchor="mm")
    d.text((TEST_W // 2, 160), "50 x 30 mm  bar = LEFT edge", font=font("arial.ttf", 20), fill=0, anchor="mm")
    d.text((TEST_W // 2, 200), "edges must show, nothing cut", font=font("arial.ttf", 20), fill=0, anchor="mm")
    return img.point(lambda v: 255 if v >= 160 else 0).convert("1")


def check_images() -> list[Image.Image]:
    """Two test labels: orientation/size, then three barcodes (1 dot, stretched, 2 dots) to scan."""
    return [orientation_image(), render(Label("TEST"), SCAN_TEST)]


def check_job(gap_mm: float = 2, direction: int = 1, invert: bool = INVERT) -> bytes:
    out = bytearray(_header(50, 30, gap_mm, direction))
    for img in check_images():
        out += _page(img, 1, invert)
    return bytes(out)
