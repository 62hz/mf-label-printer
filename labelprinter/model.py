"""Label data model and the DealPOS / Templater text rules. No I/O here."""
import html
import re
from dataclasses import asdict, dataclass

MAX_COPIES = 200  # per row
MAX_LEN = {"sku": 64, "artist": 200, "title": 200, "genre": 200, "format": 20, "year": 10}  # characters, after strip
_FORMAT_WORDS = ("KASET", "CASSETTE", "CD", "LP", "VINYL", "PIRINGAN")
_BR = re.compile(r"<\s*br\s*/?\s*>|</\s*(div|p)\s*>", re.I)
_TAG = re.compile(r"<[^>]+>")


def price_text(n: int) -> str:
    """305000 -> 'Rp305.000'."""
    return "Rp" + f"{int(n):,}".replace(",", ".")


def parse_price(v) -> int:
    """305000, 305000.0, 'Rp305.000' or '305,000' -> 305000. Empty or invalid -> 0."""
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(round(v))
    digits = re.sub(r"\D", "", str(v))
    return int(digits) if digits else 0


def parse_product_name(name: str) -> tuple[str, str]:
    """'KASET American Football - American Football (Deluxe Edition)' -> (artist, title)."""
    s = (name or "").strip()
    first, _, rest = s.partition(" ")
    if first.upper() in _FORMAT_WORDS and rest:
        s = rest.strip()
    if " - " in s:
        artist, _, title = s.partition(" - ")
        return artist.strip(), title.strip()
    return "", s


_TRAILING_YEAR = re.compile(r"\s*\(((?:19|20)\d{2})\)\s*$")


def split_title_year(title: str) -> tuple[str, str]:
    """'Immunity (2019)' -> ('Immunity', '2019'). Other brackets, like '(Deluxe Edition)', stay in the title."""
    m = _TRAILING_YEAR.search(title or "")
    return (title[:m.start()].strip(), m.group(1)) if m else ((title or "").strip(), "")


def format_chip(text: str) -> str:
    """DealPOS Category or Templater Product Type -> CASSETTE / CD / VINYL, else ''."""
    t = (text or "").lower()
    if "accessor" in t:
        return ""
    for key, chip in (("cassette", "CASSETTE"), ("kaset", "CASSETTE"), ("vinyl", "VINYL"), ("lp", "VINYL"), ("cd", "CD")):
        if re.search(rf"\b{key}\b", t):
            return chip
    return ""


def parse_description(desc_html: str) -> dict:
    """Pull 'Released: 1999 ...' and 'Genre: Rock' out of a DealPOS Description. Missing -> ''."""
    text = _BR.sub("\n", desc_html or "")
    text = html.unescape(_TAG.sub("", text)).replace("\xa0", " ")
    year = re.search(r"Released:\s*(\d{4})", text)
    genre = re.search(r"Genre:\s*([^\n•]+)", text)
    return {"year": year.group(1) if year else "", "genre": genre.group(1).strip() if genre else ""}


@dataclass
class Label:
    sku: str
    artist: str = ""
    title: str = ""
    format: str = ""
    year: str = ""
    genre: str = ""
    price: int = 0
    copies: int = 1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Label":
        """Tolerant: strips text, parses price, clamps copies to 1..MAX_COPIES, ignores unknown keys."""
        try:
            copies = int(float(d.get("copies", 1)))
        except (TypeError, ValueError):
            copies = 1
        def text(key: str) -> str:
            return str(d.get(key) or "").strip()[:MAX_LEN[key]]

        return cls(
            sku=text("sku"),
            artist=text("artist"),
            title=text("title"),
            format=text("format").upper(),
            year=text("year"),
            genre=text("genre"),
            price=parse_price(d.get("price")),
            copies=max(1, min(MAX_COPIES, copies)),
        )


def label_from_dealpos(product: dict, variant: dict) -> Label:
    """One compact DealPOS product row plus one of its variants -> a Label. Year and genre
    come later from the Description (Catalog.enrich). Cost is never read."""
    artist, title = parse_product_name(product.get("Name", ""))
    title, year = split_title_year(title)
    return Label(
        sku=str(variant.get("Code") or "").strip(),
        artist=artist,
        title=title,
        format=format_chip(product.get("Category", "")),
        year=year,
        price=parse_price(variant.get("UnitPrice")),
    )
