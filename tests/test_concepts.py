"""The MF Concept designs (Catalogue line, Price card, Format tile) and the turned barcode they rely on."""
import json

import pytest
import zxingcpp
from PIL import Image

from labelprinter import designs, render
from labelprinter.model import Label

CONCEPTS = ["mf-concept-catalogue-line", "mf-concept-price-card", "mf-concept-format-tile"]
SAMPLES = [
    Label("AMEAMET158", "American Football", "American Football (Deluxe Edition)", "CASSETTE", "1999", "Rock", 305000),
    Label("191404155127", "Charli XCX", "Brat", "VINYL", "2024", "Pop", 345000),
    Label("SAKVRIO002", "Ryuichi Sakamoto & Alva Noto", "Vrioon (Remastered 25th Anniversary Edition)", "VINYL", "2002", "Electronic", 1250000),
    Label("ALEHEAC557", "Various Artists", "Cafe de Flore", "CD", "", "", 95000),
]


def load(slug):
    return json.loads((designs.BUILTIN_DIR / f"{slug}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("slug", CONCEPTS)
@pytest.mark.parametrize("label", SAMPLES, ids=lambda label: label.sku)
def test_concept_labels_render_and_the_barcode_decodes(slug, label):
    img = render.render(label, load(slug))
    found = zxingcpp.read_barcodes(img.convert("L").resize((800, 480), Image.NEAREST))
    assert label.sku in [b.text for b in found]


@pytest.mark.parametrize("slug", CONCEPTS)
@pytest.mark.parametrize("label", SAMPLES, ids=lambda label: label.sku)
def test_nothing_prints_inside_the_2_5_mm_margin(slug, label):
    left, top, right, bottom = render.render(label, load(slug)).convert("L").point(lambda v: 255 - v).getbbox()
    assert left >= 19 and top >= 19 and right <= 381 and bottom <= 221, (left, top, right, bottom)


def test_white_text_on_a_black_box_survives_smooth_text():
    """The Catalogue line ticket is a black box with white text on it: the text must show."""
    img = render.render(SAMPLES[0], load("mf-concept-catalogue-line")).convert("L")
    ticket = img.crop((231, 135, 379, 219))            # inside the ticket box
    assert 0 < sum(1 for v in ticket.getdata() if v == 255) < ticket.width * ticket.height // 2


def test_turned_barcode_runs_down_the_box():
    d = {"name": "t", "width_mm": 50, "height_mm": 30, "gap_mm": 2,
         "elements": [{"type": "barcode", "content": "{sku}", "x": 2.5, "y": 2.5, "w": 5.5, "h": 25, "mode": "integer", "rotate": 90}]}
    img = render.render(Label("AMEAMET158"), d).convert("L")
    left, top, right, bottom = img.point(lambda v: 255 - v).getbbox()
    assert right - left <= 44 and bottom - top >= 140           # tall and narrow: bars lie across the box
    assert zxingcpp.read_barcodes(img.resize((800, 480), Image.NEAREST))[0].text == "AMEAMET158"


@pytest.mark.parametrize("value, ok", [(0, True), (90, True), ("90", True), (45, False), ("x", False)])
def test_rotate_accepts_only_0_or_90(value, ok):
    d = {"name": "t", "width_mm": 50, "height_mm": 30, "gap_mm": 2,
         "elements": [{"type": "barcode", "content": "{sku}", "x": 2, "y": 2, "w": 20, "h": 20, "rotate": value}]}
    if ok:
        assert designs.validate(d)["elements"][0]["rotate"] == int(value)
    else:
        with pytest.raises(ValueError):
            designs.validate(d)
