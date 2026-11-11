"""The MF Brand designs: one grid, DM Sans weights, the symbol at its minimum size, smooth text, baselines."""
import json

import pytest
import zxingcpp
from PIL import Image

from labelprinter import designs, fonts, render
from labelprinter.model import Label

BRAND = ["mf-brand-ledger", "mf-brand-barcode-foot", "mf-brand-symbol-column"]
SAMPLES = [
    Label("AMEAMET158", "American Football", "American Football (Deluxe Edition)", "CASSETTE", "1999", "Rock", 305000),
    Label("191404155127", "Charli XCX", "Brat", "VINYL", "2024", "Pop", 345000),
    Label("SAKVRIO002", "Ryuichi Sakamoto & Alva Noto", "Vrioon (Remastered 25th Anniversary Edition)", "VINYL", "2002", "Electronic", 1250000),
    Label("ALEHEAC557", "Various Artists", "Cafe de Flore", "CD", "", "", 95000),
    Label("NOUPASC001", "Nourished By Time", "The Passionate Ones", "CD", "2024", "Soul", 1250000),
]


def load(slug: str) -> dict:
    return json.loads((designs.BUILTIN_DIR / f"{slug}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("slug", BRAND)
@pytest.mark.parametrize("label", SAMPLES, ids=lambda label: label.sku)
def test_brand_labels_render_and_the_barcode_still_decodes(slug, label):
    img = render.render(label, load(slug))
    assert img.size == (400, 240)
    found = zxingcpp.read_barcodes(img.convert("L").resize((800, 480), Image.NEAREST))
    assert [b.text for b in found] == [label.sku]


@pytest.mark.parametrize("slug", BRAND)
@pytest.mark.parametrize("label", SAMPLES, ids=lambda label: label.sku)
def test_nothing_prints_inside_the_2_5_mm_margin(slug, label):
    """The live area is 2.5 mm in from every edge (20 dots); one dot of slack for anti-aliasing."""
    left, top, right, bottom = render.render(label, load(slug)).convert("L").point(lambda v: 255 - v).getbbox()
    assert left >= 19 and top >= 19 and right <= 400 - 19 and bottom <= 240 - 19, (left, top, right, bottom)


@pytest.mark.parametrize("slug", BRAND)
def test_brand_designs_use_only_brand_fonts_weights_and_the_symbol(slug):
    design = designs.validate(load(slug))
    texts = [el for el in design["elements"] if el["type"] == "text"]
    assert {el["font"] for el in texts} <= {"dm-sans", "dm-sans-medium", "dm-sans-semibold"}
    assert not any(el["italic"] or el["bold"] or el["reverse"] for el in texts)  # real weights, no faked bold, no black chips
    assert {el["size_pt"] for el in texts} <= {6, 8, 10, 12}                   # the type scale
    assert all(el["valign"] == "baseline" for el in texts)
    logos = [el["src"] for el in design["elements"] if el["type"] == "image"]
    assert logos in ([], ["symbol"])                                           # never the hand-drawn logotype, never the 30 mm screen logo here
    assert design["smooth_text"] is True


def test_the_symbol_keeps_its_minimum_print_size():
    """The brand guide sets the symbol at 6 mm at the smallest."""
    for slug in BRAND:
        for el in designs.validate(load(slug))["elements"]:
            if el["type"] == "image":
                assert el["w"] >= 6 and el["h"] >= 6


def test_brand_weights_resolve_to_their_own_files():
    paths = {key: fonts.default.resolve(key, False, False).name for key in ("dm-sans", "dm-sans-medium", "dm-sans-semibold")}
    assert paths == {"dm-sans": "DMSans-Regular.ttf", "dm-sans-medium": "DMSans-Medium.ttf", "dm-sans-semibold": "DMSans-SemiBold.ttf"}
    assert fonts.default.status("dm-sans-semibold", False, False) is None


def test_image_src_choices_and_unknown_src_is_refused():
    base = {"name": "x", "width_mm": 50, "height_mm": 30, "gap_mm": 2, "elements": [{"type": "image", "x": 1, "y": 1, "w": 10, "h": 10}]}
    assert designs.validate(base)["elements"][0]["src"] == "logo"
    for src in ("logo", "symbol", "screen-logo"):
        base["elements"][0]["src"] = src
        assert designs.validate(base)["elements"][0]["src"] == src
    base["elements"][0]["src"] = "../../etc/passwd"
    with pytest.raises(ValueError):
        designs.validate(base)


def test_smooth_text_is_off_by_default_and_changes_only_the_text():
    plain = load("mf-april")
    assert designs.validate(plain)["smooth_text"] is False
    smooth = dict(plain, smooth_text=True)
    a, b = render.render(SAMPLES[0], plain), render.render(SAMPLES[0], smooth)
    assert a.tobytes() != b.tobytes()
    box = (15, 176, 190, 214)                    # the barcode area: whole dots in both
    assert a.crop(box).tobytes() == b.crop(box).tobytes()


def one_text(**over):
    el = {"type": "text", "content": "{artist}", "x": 2.5, "y": 2.0, "w": 20, "h": 4.0, "font": "dm-sans-semibold", "size_pt": 12,
          "min_size_pt": 5, "valign": "baseline"}
    el.update(over)
    return {"name": "t", "width_mm": 50, "height_mm": 30, "gap_mm": 2, "elements": [el]}


def last_ink_row(img):
    return img.convert("L").point(lambda v: 255 - v).getbbox()[3]


def test_a_baseline_text_that_shrinks_stays_on_its_line():
    short = render.render(Label("X", artist="HHH"), one_text())
    shrunk = render.render(Label("X", artist="H" * 30), one_text())      # too long: shrinks to fit
    assert last_ink_row(short) == last_ink_row(shrunk)
    top = render.render(Label("X", artist="HHH"), one_text(valign="top"))
    top_shrunk = render.render(Label("X", artist="H" * 30), one_text(valign="top"))
    assert last_ink_row(top) != last_ink_row(top_shrunk)                  # top-anchored text moves, which is why baseline exists


def test_uppercase_option_sets_the_text_in_capitals():
    lower = render.render(Label("X", genre="soul"), one_text(content="{genre}", upper=True))
    caps = render.render(Label("X", genre="SOUL"), one_text(content="{genre}"))
    assert lower.tobytes() == caps.tobytes()
    assert designs.validate(one_text())["elements"][0]["upper"] is False


def test_old_designs_print_as_they_did_before_the_brand_work():
    img = render.render(SAMPLES[0], load("mf-april"))
    assert img.size == (400, 240) and img.getbbox() is not None
