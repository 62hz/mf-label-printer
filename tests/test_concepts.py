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


LONG = [
    Label("ORCHMANOEUV7", "Orchestral Manoeuvres In The Dark", "Architecture & Morality (40th Anniversary Deluxe Edition)", "CASSETTE", "1981", "Synth-pop, New Wave", 1250000),
    Label("ABCDEFGHIJKLM", "Miles Davis", "Kind Of Blue (Original Mono Recording, Mint Box Set)", "VINYL", "1959", "Jazz", 12500000),
    Label("4988031465987", "Kikagaku Moyo", "Kumoyo Island", "CD", "2022", "Psychedelic Rock", 299000),
]


@pytest.mark.parametrize("label", LONG, ids=lambda label: label.sku)
def test_price_card_never_cuts_the_sku_or_the_price(label, monkeypatch):
    drawn = []
    real = render.ImageDraw.ImageDraw.text

    def spy(self, xy, text, *a, **kw):
        drawn.append(text)
        return real(self, xy, text, *a, **kw)

    monkeypatch.setattr(render.ImageDraw.ImageDraw, "text", spy)
    render.render(label, load("mf-concept-price-card"))
    assert label.sku in drawn
    assert any(t.startswith("Rp") and not t.endswith("...") for t in drawn)


def test_long_artist_and_title_wrap_instead_of_being_cut(monkeypatch):
    drawn = []
    real = render.ImageDraw.ImageDraw.text
    monkeypatch.setattr(render.ImageDraw.ImageDraw, "text", lambda self, xy, text, *a, **kw: (drawn.append(text), real(self, xy, text, *a, **kw))[1])
    render.render(Label("GODSPEED01", "Godspeed You! Black Emperor", "Lift Your Skinny Fists Like Antennas To Heaven (Remastered 2LP)",
                        "VINYL", "2000", "Post-Rock", 785000), load("mf-concept-price-card"))
    assert "Lift Your Skinny Fists Like Antennas" in drawn and "To Heaven (Remastered 2LP)" in drawn


def test_a_short_name_stays_on_one_line(monkeypatch):
    drawn = []
    real = render.ImageDraw.ImageDraw.text
    monkeypatch.setattr(render.ImageDraw.ImageDraw, "text", lambda self, xy, text, *a, **kw: (drawn.append(text), real(self, xy, text, *a, **kw))[1])
    render.render(SAMPLES[1], load("mf-concept-price-card"))
    assert "Charli XCX" in drawn and "Brat" in drawn


@pytest.mark.parametrize("value, ok", [(1, True), (2, True), ("3", True), (0, False), (4, False), ("x", False)])
def test_lines_accepts_1_to_3(value, ok):
    d = {"name": "t", "width_mm": 50, "height_mm": 30, "gap_mm": 2,
         "elements": [{"type": "text", "content": "{artist}", "x": 2, "y": 2, "w": 20, "h": 5, "size_pt": 8, "lines": value}]}
    if ok:
        assert designs.validate(d)["elements"][0]["lines"] == int(value)
    else:
        with pytest.raises(ValueError):
            designs.validate(d)


def _symbol_printed(label):
    img = render.render(label, load("mf-concept-price-card")).convert("L")
    corner = img.crop((20, 192, 64, 220))          # the foot of the barcode column, where the symbol sits
    return sum(1 for v in corner.getdata() if v == 0)


def test_the_symbol_shows_under_a_short_barcode_and_gives_way_to_a_long_one():
    short = Label("NOUPASC001", "Nourished By Time", "The Passionate Ones", "CD", "2024", "Soul", 330000)
    long_ = Label("ABCDEFGHIJKLM", "Miles Davis", "Kind Of Blue", "VINYL", "1959", "Jazz", 345000)
    assert _symbol_printed(short) > 100
    # the long SKU's bars reach into the corner; what is there must be bars only (rows of full-width black), no symbol shape
    img = render.render(long_, load("mf-concept-price-card")).convert("L")
    d = {"name": "t", "width_mm": 50, "height_mm": 30, "gap_mm": 2,
         "elements": [dict(el) for el in load("mf-concept-price-card")["elements"] if el["id"] == "barcode"]}
    bars_only = render.render(long_, d).convert("L")
    box = (20, 192, 64, 220)
    assert img.crop(box).tobytes() == bars_only.crop(box).tobytes()


def test_gives_way_defaults_off():
    d = {"name": "t", "width_mm": 50, "height_mm": 30, "gap_mm": 2, "elements": [{"type": "image", "x": 1, "y": 1, "w": 5, "h": 5}]}
    assert designs.validate(d)["elements"][0]["gives_way"] is False
