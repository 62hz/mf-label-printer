"""Make the static DM Sans files the label renderer bundles, from the variable web font.

  py scripts/make_dmsans.py

Needs fontTools, which is only used here: run it with the global interpreter (`py`), it is not a
project dependency. Pillow draws text from static TrueType files, so the variable font that serves
the page (labelprinter/static/fonts/dmsans-latin.woff) is cut into Regular (wght 400), Medium (500),
SemiBold (600) and Bold (700) at the 9 pt optical size (the roomy cut that suits small label text).
The font registry lists Medium and SemiBold as their own families ("DM Sans Medium", "DM Sans SemiBold").

DM Sans is released under the SIL Open Font License 1.1.
"""
import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "labelprinter" / "static" / "fonts" / "dmsans-latin.woff"
OUT_DIR = ROOT / "labelprinter" / "fonts"
FAMILY = "DM Sans"
# The brand uses three weights (SemiBold titles, Medium labels and prices, Regular text); Bold stays for the old designs.
CUTS = (("Regular", 400, False), ("Medium", 500, False), ("SemiBold", 600, False), ("Bold", 700, True))
# name ids that would make FreeType (and so Pillow) report something other than FAMILY + style
DROP_NAME_IDS = {16, 17, 21, 22, 25}


def make(style: str, weight: int, bold: bool) -> Path:
    font = TTFont(SOURCE)
    font = instancer.instantiateVariableFont(font, {"wght": weight, "opsz": 9}, inplace=False)
    font.flavor = None  # plain TTF, not WOFF
    name = font["name"]
    name.names = [n for n in name.names if n.nameID not in DROP_NAME_IDS and n.nameID < 256]
    ps = f"{FAMILY.replace(' ', '')}-{style}"
    for name_id, text in ((1, FAMILY), (2, style), (4, f"{FAMILY} {style}"), (6, ps), (3, f"{ps};static")):
        name.setName(text, name_id, 3, 1, 0x409)
        name.setName(text, name_id, 1, 0, 0)
    os2, head = font["OS/2"], font["head"]
    os2.usWeightClass = weight
    os2.fsSelection = (os2.fsSelection & ~0b1100001) | (0b100000 if bold else 0b1000000)  # BOLD or REGULAR bit
    head.macStyle = 1 if bold else 0
    for table in ("STAT", "fvar", "gvar", "avar", "HVAR", "MVAR"):
        if table in font:
            del font[table]
    path = OUT_DIR / f"DMSans-{style}.ttf"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    font.save(path)
    return path


def main() -> int:
    from PIL import ImageFont  # only to check the result; Pillow is a project dependency

    for style, weight, bold in CUTS:
        path = make(style, weight, bold)
        got = ImageFont.truetype(str(path), 12).getname()
        print(path.name, got, path.stat().st_size, "bytes")
        if got != (FAMILY, style):
            print(f"unexpected family/style {got}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
