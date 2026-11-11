"""Label designs: a design is a small JSON document (size, gap, list of elements in mm).

Built-in designs ship in labelprinter/designs/*.json and are read-only. Your own designs are saved
as data/designs/<slug>.json. Everything that draws, prints or exports a label takes a design dict.
"""
import json
import os
import re
from pathlib import Path

from . import fonts

DEFAULT_SLUG = os.environ.get("LABELPRINTER_DEFAULT_DESIGN", "mf-concept-price-card")  # the design the page opens with
BUILTIN_DIR = Path(__file__).resolve().parent / "designs"
FIELDS = {"sku", "artist", "title", "format", "year", "genre", "price", "copies"}
TYPES = ("text", "barcode", "rect", "image", "ellipse", "perforation")
MAX_ELEMENTS = 40
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,59}")  # everything slugify() makes; nothing that can name a path


def _num(d: dict, key: str, lo: float, hi: float, where: str) -> float:
    try:
        v = float(d[key])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"{where}: {key} must be a number") from None
    if not lo <= v <= hi:
        raise ValueError(f"{where}: {key} must be between {lo:g} and {hi:g}")
    return round(v, 2)


def _choice(d: dict, key: str, options, default, where: str):
    v = d.get(key, default)
    if v not in options:
        raise ValueError(f"{where}: {key} must be one of {', '.join(map(str, options))}")
    return v


def _rotate(d: dict, where: str) -> int:
    """0 (bars upright, read left to right) or 90 (bars lying down, read top to bottom). The page sends it as text."""
    try:
        r = int(d.get("rotate", 0))
    except (TypeError, ValueError):
        r = -1
    if r not in (0, 90):
        raise ValueError(f"{where}: rotate must be 0 or 90")
    return r


def _mrz(d: dict, where: str) -> int:
    """0 (off) or the number of characters of a machine-readable line (like the two 36-character lines of an ID card)."""
    try:
        n = int(d.get("mrz", 0))
    except (TypeError, ValueError):
        n = -1
    if n != 0 and not 10 <= n <= 60:
        raise ValueError(f"{where}: mrz must be 0 or between 10 and 60")
    return n


def _font_key(d: dict, where: str) -> str:
    """A font family key (see fonts.py), with legacy names upgraded. Whether that font is installed is not checked here:
    a design naming a missing font still loads and renders, with a note."""
    key = fonts.canonical_key(d.get("font", "arial"))
    if not fonts.valid_key(key):
        raise ValueError(f"{where}: font must be a font key made of lowercase letters, digits and dashes, like arial or dm-sans")
    return key


def _check_placeholders(text: str, where: str) -> str:
    if len(text) > 200:
        raise ValueError(f"{where}: content is too long")
    for name in _PLACEHOLDER.findall(text):
        if name not in FIELDS:
            raise ValueError(f"{where}: unknown field {{{name}}}. Use: " + ", ".join("{" + f + "}" for f in sorted(FIELDS)))
    return text


def validate(design: dict) -> dict:
    """Return a cleaned copy of a design, or raise ValueError with a message the user can act on."""
    if not isinstance(design, dict):
        raise ValueError("Design must be an object")
    name = str(design.get("name", "")).strip()
    if not 1 <= len(name) <= 60:
        raise ValueError("Design name must be 1 to 60 characters")
    width = int(_num(design, "width_mm", 10, 104, "design"))  # whole mm: 8 dots per mm, so every row is whole bytes
    height = _num(design, "height_mm", 5, 200, "design")
    out = {
        "name": name,
        "width_mm": width,
        "height_mm": height,
        "gap_mm": _num(design, "gap_mm", 0, 10, "design"),
        "direction": int(_choice(design, "direction", (0, 1), 1, "design")),
        "smooth_text": bool(design.get("smooth_text", False)),  # draw text enlarged and shrink it: even spacing for DM Sans at small sizes
        "elements": [],
    }
    elements = design.get("elements")
    if not isinstance(elements, list):
        raise ValueError("Design needs an elements list")
    if len(elements) > MAX_ELEMENTS:
        raise ValueError(f"Too many elements (limit {MAX_ELEMENTS})")
    seen = set()
    for n, el in enumerate(elements, 1):
        where = f"Element {n}"
        if not isinstance(el, dict):
            raise ValueError(f"{where} must be an object")
        etype = _choice(el, "type", TYPES, None, where)
        eid = str(el.get("id") or f"e{n}")
        if eid in seen:
            eid = f"{eid}-{n}"
        seen.add(eid)
        clean = {"id": eid, "type": etype, "visible": bool(el.get("visible", True)),
                 "x": _num(el, "x", -width, width, where), "y": _num(el, "y", -height, height, where),
                 "w": _num(el, "w", 0.1, width, where), "h": _num(el, "h", 0.05, height, where)}
        if etype == "text":
            clean.update(
                content=_check_placeholders(str(el.get("content", "")), where),
                font=_font_key(el, where),
                size_pt=_num(el, "size_pt", 3, 60, where),
                min_size_pt=_num({"min_size_pt": el.get("min_size_pt", 4)}, "min_size_pt", 2, 60, where),
                bold=bool(el.get("bold", False)), italic=bool(el.get("italic", False)), reverse=bool(el.get("reverse", False)),
                align=_choice(el, "align", ("left", "center", "right"), "left", where),
                valign=_choice(el, "valign", ("top", "middle", "baseline", "flow"), "top", where),
                upper=bool(el.get("upper", False)),
                lines=int(_num({"lines": el.get("lines", 1)}, "lines", 1, 3, where)),
                first_item=bool(el.get("first_item", False)),          # only the part before the first comma
                blank=str(el.get("blank", ""))[:4],                     # shown when the field is empty, e.g. an en dash
                after=str(el.get("after", ""))[:60],                    # flow: start under this element's last line
                after_gap=_num({"after_gap": el.get("after_gap", 0)}, "after_gap", 0, 20, where),
                mrz=_mrz(el, where))                                    # passport machine-readable line: fixed width, filled with <
        elif etype == "barcode":
            clean.update(content=_check_placeholders(str(el.get("content", "{sku}")), where),
                         mode=_choice(el, "mode", ("fit", "integer"), "fit", where), rotate=_rotate(el, where),
                         center=bool(el.get("center", False)),
                         reserve=_num({"reserve": el.get("reserve", 0)}, "reserve", 0, 100, where))
        elif etype == "image":
            clean.update(src=_choice(el, "src", ("logo", "symbol", "screen-logo"), "logo", where),
                         gives_way=bool(el.get("gives_way", False)))  # left out when a barcode needs the room
        elif etype == "ellipse":      # a disc or a ring (a circle when w = h), optionally with concentric grooves inside
            clean.update(fill=_choice(el, "fill", ("none", "black", "white"), "none", where),
                         stroke=_num({"stroke": el.get("stroke", 0.125)}, "stroke", 0, 5, where),
                         rings=int(_num({"rings": el.get("rings", 0)}, "rings", 0, 12, where)),
                         ring_gap=_num({"ring_gap": el.get("ring_gap", 0.5)}, "ring_gap", 0.1, 3, where))
        elif etype == "perforation":  # a stamp edge: a hairline frame with half-round notches cut into it
            clean.update(pitch=_num({"pitch": el.get("pitch", 1.25)}, "pitch", 0.6, 5, where),
                         radius=_num({"radius": el.get("radius", 0.4)}, "radius", 0.15, 1.5, where),
                         stroke=_num({"stroke": el.get("stroke", 0.125)}, "stroke", 0.1, 1, where))
        out["elements"].append(clean)
    return out


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "design"


class DesignStore:
    def __init__(self, user_dir: Path, builtin_dir: Path = BUILTIN_DIR):
        self.user_dir = user_dir
        self.builtin_dir = builtin_dir

    def _builtin(self) -> dict[str, dict]:
        return {p.stem: validate(json.loads(p.read_text(encoding="utf-8"))) for p in sorted(self.builtin_dir.glob("*.json"))}

    def _user(self) -> dict[str, dict]:
        out = {}
        if self.user_dir.exists():
            for p in sorted(self.user_dir.glob("*.json")):
                try:
                    out[p.stem] = validate(json.loads(p.read_text(encoding="utf-8")))
                except (ValueError, json.JSONDecodeError):
                    continue  # a hand-edited broken file must not take the app down
        return out

    def list(self) -> list[dict]:
        rows = [{"slug": s, "name": d["name"], "builtin": True} for s, d in self._builtin().items()]
        rows += [{"slug": s, "name": d["name"], "builtin": False} for s, d in self._user().items()]
        return rows

    def get(self, slug: str) -> dict:
        if not isinstance(slug, str) or not _SLUG_RE.fullmatch(slug):
            raise KeyError(slug)
        found ={**self._user(), **self._builtin()}.get(slug)
        if found is None:
            raise KeyError(slug)
        return found

    def save(self, design: dict) -> str:
        """Save a user design under a slug made from its name. Built-in names are reserved."""
        clean = validate(design)
        slug = slugify(clean["name"])
        if slug in self._builtin():
            raise ValueError(f"'{clean['name']}' is a built-in design and is read-only. Save it under a new name.")
        self.user_dir.mkdir(parents=True, exist_ok=True)
        (self.user_dir / f"{slug}.json").write_text(json.dumps(clean, indent=2), encoding="utf-8")
        return slug

    def delete(self, slug: str) -> None:
        if not isinstance(slug, str) or not _SLUG_RE.fullmatch(slug):
            raise KeyError(slug)
        if slug in self._builtin():
            raise ValueError("Built-in designs cannot be deleted.")
        path = self.user_dir / f"{slug}.json"
        if not path.exists():
            raise KeyError(slug)
        path.unlink()
