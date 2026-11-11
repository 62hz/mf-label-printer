"""Font registry: which fonts a label can use, and which file a design's font key means.

Fonts come from three folders, lowest to highest precedence:
  system   C:/Windows/Fonts (env LABEL_FONT_DIR changes it)
  bundled  labelprinter/fonts: DM Sans, Medium Format's brand font
  custom   data/fonts: font files uploaded through the page

Only .ttf and .otf files are read (.ttc collections are skipped), as Pillow draws them. A family key
is the slug of the family name ("Times New Roman" -> "times-new-roman"); a design stores that key. A
file fills one of four style slots of its family (regular, bold, italic, bolditalic). Light, Black,
Semibold and the like are not slots: each is its own family ("Lato Light"). When two folders offer
the same slot of the same family, the higher one wins that slot.

A key that is not installed never breaks a label: resolve() falls back (see there) and status() says so.
"""
import hashlib
import io
import os
import re
import threading
from pathlib import Path

from PIL import ImageFont

KEY_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,59}")   # what slug() makes; nothing here can name a path
ROOT = Path(__file__).resolve().parents[1]
SYSTEM_DIR = Path(os.environ.get("LABEL_FONT_DIR", "C:/Windows/Fonts"))
CUSTOM_DIR = ROOT / "data" / "fonts"
BUNDLED_DIR = Path(__file__).resolve().parent / "fonts"

SOURCES = ("system", "bundled", "custom")          # lowest to highest precedence
SLOTS = ("regular", "bold", "italic", "bolditalic")
SLOT_WORDS = {"regular": "regular", "bold": "bold", "italic": "italic", "bolditalic": "bold italic"}
# what to try, in order, for the style asked for
FALLBACK = {
    "regular": ("regular", "bold", "italic", "bolditalic"),
    "bold": ("bold", "regular", "italic", "bolditalic"),
    "italic": ("italic", "regular", "bold", "bolditalic"),
    "bolditalic": ("bolditalic", "bold", "italic", "regular"),
}
ALIASES = {"times": "times-new-roman", "courier": "courier-new"}   # keys older designs used
EXTENSIONS = (".ttf", ".otf")
MAX_UPLOAD = 5 * 1024 * 1024
MAX_CUSTOM_FILES = 100
NAME_MAX = 80
SYMBOL_WORDS = ("icon", "symbol", "wingdings", "webdings", "marlett", "awesome", "mdl2", "emoji", "dingbats")
_REGULAR_WORDS = {"", "regular", "book", "normal", "roman"}
_SLOT_STYLES = (_REGULAR_WORDS - {""}) | {"bold", "italic", "oblique", "bold italic", "bold oblique"}


def valid_key(key) -> bool:
    return isinstance(key, str) and KEY_RE.fullmatch(key) is not None


def canonical_key(key):
    """The key with legacy names mapped to today's ('times' -> 'times-new-roman'); anything else comes back unchanged."""
    return ALIASES.get(key, key) if isinstance(key, str) else key


def slug(name: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60].strip("-")
    return out or "font-" + hashlib.sha1(name.encode("utf-8", "replace")).hexdigest()[:8]


def clean_name(text) -> str:
    """A font name safe to show and to put in a header: printable characters only, single spaces, not too long."""
    text = "".join(ch if ch.isprintable() else " " for ch in str(text or ""))
    return " ".join(text.split())[:NAME_MAX]


def _without_family_prefix(family: str, style: str) -> str:
    """Some files name the style after the family: 'DIN-Bold' in 'D-DIN'. When what comes before the last dash is part of the
    family name and what follows is a plain style, only the plain style counts ('Semi-Bold' is not touched)."""
    head, dash, tail = style.rpartition("-")
    if dash and tail.lower() in _SLOT_STYLES:
        squash = lambda text: re.sub(r"[^a-z0-9]", "", text.lower())
        if squash(head) and squash(head) in squash(family):
            return tail
    return style


def classify(family: str, style: str) -> tuple[str, str]:
    """(family name, slot) for the names inside a font file. Styles beyond the four slots become a family of their own."""
    family, style = clean_name(family), clean_name(style)
    style = _without_family_prefix(family, style)
    italic, base = False, style
    for word in ("italic", "oblique"):
        if style.lower().endswith(word):
            italic, base = True, style[: -len(word)].strip()
            break
    if base.lower() in _REGULAR_WORDS:
        return family, "italic" if italic else "regular"
    if base.lower() == "bold":
        return family, "bolditalic" if italic else "bold"
    return f"{family} {base}", "italic" if italic else "regular"


def is_symbol(name: str) -> bool:
    low = name.lower()
    return any(word in low for word in SYMBOL_WORDS)


def _pillow_names(path: Path) -> tuple[str, str]:
    return ImageFont.truetype(str(path), 12).getname()


def _stamp(directory: Path):
    try:
        return os.stat(directory).st_mtime_ns
    except OSError:
        return None


class FontRegistry:
    """Scans the three folders (and rescans when one changes) and answers: which families, which file, what to tell the user."""

    def __init__(self, system_dir, custom_dir, bundled_dir, reader=None):
        self.system_dir, self.custom_dir, self.bundled_dir = Path(system_dir), Path(custom_dir), Path(bundled_dir)
        self._read = reader or _pillow_names     # reader(path) -> (family, style); tests pass a stub
        self._lock = threading.RLock()
        self._stamps = None
        self._families: dict[str, dict] = {}
        self._custom_files: dict[str, list[Path]] = {}

    # ------------------------------------------------------------ scanning

    def _dirs(self):
        return ((self.system_dir, "system"), (self.bundled_dir, "bundled"), (self.custom_dir, "custom"))

    def _invalidate(self) -> None:
        self._stamps = None

    def _refresh(self) -> dict[str, dict]:
        with self._lock:
            stamps = tuple(_stamp(d) for d, _ in self._dirs())
            if stamps != self._stamps:
                self._families, self._custom_files = self._scan()
                self._stamps = stamps
            return self._families

    def _scan(self):
        families: dict[str, dict] = {}
        custom_files: dict[str, list[Path]] = {}
        for directory, source in self._dirs():                       # lowest precedence first
            try:
                paths = sorted(directory.iterdir(), key=lambda p: p.name.lower())
            except OSError:
                continue
            rank = SOURCES.index(source)
            for path in paths:
                if path.suffix.lower() not in EXTENSIONS or not path.is_file():
                    continue
                try:
                    family, style = self._read(path)
                except Exception:                                      # unreadable or not a font: leave it out
                    continue
                if not family:
                    continue
                name, slot = classify(family, style or "Regular")
                if not name or is_symbol(name):
                    continue
                key = slug(name)
                entry = families.setdefault(key, {"name": name, "source": source, "slots": {}, "ranks": {}})
                if slot not in entry["slots"] or rank > entry["ranks"][slot]:   # same folder twice: the first file by name stays
                    entry["slots"][slot], entry["ranks"][slot] = path, rank
                if rank > SOURCES.index(entry["source"]):
                    entry["source"], entry["name"] = source, name
                if source == "custom":
                    custom_files.setdefault(key, []).append(path)
        return families, custom_files

    # ------------------------------------------------------------ questions

    def families(self) -> list[dict]:
        """Every usable family, sorted by name: {key, name, source: bundled|custom|system, styles: [slots present]}."""
        entries = self._refresh()
        rows = [{"key": key, "name": e["name"], "source": e["source"], "styles": [s for s in SLOTS if s in e["slots"]]}
                for key, e in entries.items()]
        return sorted(rows, key=lambda r: (r["name"].lower(), r["key"]))

    def _pick(self, key, bold: bool, italic: bool) -> tuple[Path, str | None]:
        """(file, message). The message is None when the file is exactly what was asked for."""
        entries = self._refresh()
        wanted = "bolditalic" if bold and italic else "bold" if bold else "italic" if italic else "regular"
        key = canonical_key(key)
        entry = entries.get(key) if valid_key(key) else None
        if entry is None:
            shown = clean_name(key if isinstance(key, str) else repr(key))
            for fallback in ("arial", "dm-sans"):
                fb = entries.get(fallback)
                if fb is None:
                    continue
                slot = next(s for s in FALLBACK["regular" if fallback == "dm-sans" else wanted] if s in fb["slots"])
                return fb["slots"][slot], f"Font '{shown}' is not installed here, using {fb['name']}."
            raise FileNotFoundError("No fonts are available: the DM Sans files in labelprinter/fonts are missing.")
        slot = next(s for s in FALLBACK[wanted] if s in entry["slots"])
        if slot == wanted:
            return entry["slots"][slot], None
        return entry["slots"][slot], f"{entry['name']} has no {SLOT_WORDS[wanted]}, showing {SLOT_WORDS[slot]}."

    def resolve(self, key, bold: bool = False, italic: bool = False) -> Path:
        """The font file for a family key and style. Missing style: bold and italic fall back to regular, bold italic to
        bold, then italic, then regular. Unknown key (or one that is not a key at all): Arial, then DM Sans regular."""
        return self._pick(key, bool(bold), bool(italic))[0]

    def status(self, key, bold: bool = False, italic: bool = False) -> str | None:
        """A plain sentence when resolve() cannot give exactly what the design asks for, else None."""
        return self._pick(key, bool(bold), bool(italic))[1]

    # ------------------------------------------------------------ your own fonts

    def add_custom(self, filename: str, data: bytes) -> str:
        """Keep an uploaded .ttf/.otf under a name made here (family and style, never the uploaded name). Returns the family key."""
        name = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        ext = os.path.splitext(name)[1].lower()
        if ext not in EXTENSIONS:
            raise ValueError("Only .ttf and .otf font files can be added.")
        if len(data) > MAX_UPLOAD:
            raise ValueError("Font file is over 5 MB.")
        try:
            face = ImageFont.truetype(io.BytesIO(data), 12)
            family, style = face.getname()
            face.getmask("Ag")                                          # a real glyph load, not just a header that parses
        except Exception:
            raise ValueError("Not a font file.") from None
        if not family:
            raise ValueError("Not a font file.")
        family_name, slot = classify(family, style or "Regular")
        if not family_name or is_symbol(family_name):
            raise ValueError("This looks like a symbol or icon font, which cannot print label text.")
        key = slug(family_name)
        stored = f"{key}--{slot}{ext}"
        with self._lock:
            self._refresh()
            existing = {p.name for paths in self._custom_files.values() for p in paths}
            if stored not in existing and len(existing) >= MAX_CUSTOM_FILES:
                raise ValueError(f"Too many added fonts (limit {MAX_CUSTOM_FILES}). Remove some first.")
            self.custom_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.custom_dir / f".{stored}.tmp"
            tmp.write_bytes(data)
            os.replace(tmp, self.custom_dir / stored)
            other = self.custom_dir / f"{key}--{slot}{'.otf' if ext == '.ttf' else '.ttf'}"
            other.unlink(missing_ok=True)                               # the same slot in the other format would shadow this one
            self._invalidate()
        return key

    def remove_custom(self, key) -> None:
        """Delete an added family's files. KeyError for anything that is not an added family (system, bundled, unknown, not a key)."""
        if not valid_key(key):
            raise KeyError(key)
        with self._lock:
            self._refresh()
            files = list(self._custom_files.get(key, ()))
            if not files:
                raise KeyError(key)
            home = self.custom_dir.resolve()
            for path in files:
                if path.parent.resolve() == home:
                    path.unlink(missing_ok=True)
            self._invalidate()


default = FontRegistry(SYSTEM_DIR, CUSTOM_DIR, BUNDLED_DIR)   # what the app uses; tests and the dev server swap it for a throwaway one


def families() -> list[dict]:
    return default.families()


def resolve(key, bold: bool = False, italic: bool = False) -> Path:
    return default.resolve(key, bold, italic)


def status(key, bold: bool = False, italic: bool = False) -> str | None:
    return default.status(key, bold, italic)
