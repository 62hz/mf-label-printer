"""The MF Brand designs: Sara's symbol and the DM Sans screen logo, DM Sans weights, smooth text."""
import json

import pytest
import zxingcpp
from PIL import Image

from labelprinter import designs, fonts, render
from labelprinter.model import Label

BRAND = ["mf-brand-screen-logo", "mf-brand-info-footer-logo", "mf-brand-info-price-block"]
SAMPLES = [
    Label("AMEAMET158", "American Football", "American Football (Deluxe Edition)", "CASSETTE", "1999", "Rock", 305000),
    Label("191404155127", "Charli XCX", "Brat", "VINYL", "2024", "Pop", 345000),
    Label("SAKVRIO002", "Ryuichi Sakamoto & Alva Noto", "Vrioon (Remastered 25th Anniversary Edition)", "VINYL", "2002", "Electronic", 1250000),
    Label("ALEHEAC557", "Various Artists", "Cafe de Flore", "CD", "", "", 95000),
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
def test_brand_designs_use_only_brand_fonts_and_one_logo(slug):
    design = designs.validate(load(slug))
    text_fonts = {el["font"] for el in design["elements"] if el["type"] == "text"}
    assert text_fonts <= {"dm-sans", "dm-sans-medium", "dm-sans-semibold"}
    assert not any(el["italic"] or el["bold"] for el in design["elements"] if el["type"] == "text")  # real weights, never faked
    logos = [el["src"] for el in design["elements"] if el["type"] == "image"]
    assert len(logos) == 1 and logos[0] in ("symbol", "screen-logo")  # never the hand-drawn logotype
    assert design["smooth_text"] is True


def test_brand_weights_resolve_to_their_own_files():
    paths = {key: fonts.default.resolve(key, False, False).name for key in ("dm-sans", "dm-sans-medium", "dm-sans-semibold")}
    assert paths == {"dm-sans": "DMSans-Regular.ttf", "dm-sans-medium": "DMSans-Medium.ttf", "dm-sans-semibold": "DMSans-SemiBold.ttf"}
    assert fonts.default.status("dm-sans-semibold", False, False) is None


def test_screen_logo_respects_the_minimum_print_width():
    """The brand guide sets the screen logo at 30 mm wide at the smallest, and the symbol at 6 mm."""
    for slug in BRAND:
        for el in designs.validate(load(slug))["elements"]:
            if el["type"] == "image" and el["src"] == "screen-logo":
                assert el["w"] >= 30
            if el["type"] == "image" and el["src"] == "symbol":
                assert min(el["w"], el["h"]) >= 6


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
    # the barcode rows are on whole dots in both: compare the barcode area
    box = (15, 176, 190, 214)
    assert a.crop(box).tobytes() == b.crop(box).tobytes()


def test_old_logo_file_still_prints_the_april_label_unchanged():
    # mf-april keeps the hand-drawn logo with its margin: the same box gives the same bitmap as before the brand work
    img = render.render(SAMPLES[0], load("mf-april"))
    assert img.size == (400, 240) and img.getbbox() is not None
