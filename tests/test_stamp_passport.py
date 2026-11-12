"""The MF Stamp and MF Passport designs, and the building blocks they rely on (circle, stamp edge, machine-readable line)."""
import json

import pytest
import zxingcpp
from PIL import Image

from labelprinter import designs, render
from labelprinter.model import Label

PASSPORTS = ["mf-passport", "mf-passport-corner", "mf-passport-inline"]
NEW = ["mf-stamp"] + PASSPORTS
SAMPLES = [
    Label("NOUPASC001", "Nourished By Time", "The Passionate Ones", "CD", "2024", "Soul", 330000),
    Label("4988031465987", "Kikagaku Moyo", "Kumoyo Island", "CD", "2022", "Psychedelic Rock", 299000),
    Label("ABCDEFGHIJKLMNOP", "Orchestral Manoeuvres In The Dark", "Architecture & Morality (40th Anniversary Deluxe Edition)", "CASSETTE", "1981", "Synth-pop, New Wave", 12500000),
    Label("ALEHEAC557", "Various Artists", "Cafe de Flore", "CD", "", "", 95000),
]


def load(slug):
    return json.loads((designs.BUILTIN_DIR / f"{slug}.json").read_text(encoding="utf-8"))


def spy_text(monkeypatch):
    drawn = []
    real = render.ImageDraw.ImageDraw.text
    monkeypatch.setattr(render.ImageDraw.ImageDraw, "text", lambda self, xy, text, *a, **kw: (drawn.append(text), real(self, xy, text, *a, **kw))[1])
    return drawn


@pytest.mark.parametrize("slug", NEW)
@pytest.mark.parametrize("label", SAMPLES, ids=lambda label: label.sku)
def test_barcode_decodes_even_for_the_longest_skus(slug, label):
    img = render.render(label, load(slug)).convert("L").resize((800, 480), Image.NEAREST)
    assert label.sku in [b.text for b in zxingcpp.read_barcodes(img)]


@pytest.mark.parametrize("slug", NEW)
@pytest.mark.parametrize("label", SAMPLES, ids=lambda label: label.sku)
def test_nothing_prints_inside_the_2_5_mm_margin(slug, label):
    left, top, right, bottom = render.render(label, load(slug)).convert("L").point(lambda v: 255 - v).getbbox()
    assert left >= 19 and top >= 19 and right <= 381 and bottom <= 221, (left, top, right, bottom)


@pytest.mark.parametrize("slug", NEW)
@pytest.mark.parametrize("label", SAMPLES, ids=lambda label: label.sku)
def test_the_price_is_never_cut(slug, label, monkeypatch):
    drawn = spy_text(monkeypatch)
    render.render(label, load(slug))
    assert any(t.startswith("Rp") and not t.endswith("...") for t in drawn)


def test_mrz_is_capitals_digits_and_fill_cut_or_padded_to_the_width():
    assert render.mrz("Nourished By Time<<The Passionate Ones", 36) == "NOURISHED<BY<TIME<<THE<PASSIONATE<ONE"[:36]
    assert render.mrz("Rp1.250.000", 12) == "RP1250000<<<"
    assert render.mrz("Sigur Rós & Jónsi's", 20) == "SIGUR<ROS<JONSIS<<<<"
    assert render.mrz("", 10) == "<" * 10
    assert len(render.mrz("x" * 100, 36)) == 36


def test_the_passport_machine_readable_lines_are_36_characters(monkeypatch):
    drawn = spy_text(monkeypatch)
    render.render(SAMPLES[0], load("mf-passport"))
    lines = [t for t in drawn if "<" in t]
    assert len(lines) == 2 and all(len(t) == 36 for t in lines)
    assert lines[0].startswith("R<MFXNOURISHED<BY<TIME<<THE<")
    assert lines[1].startswith("NOUPASC001<CD<2024<RP330000")


@pytest.mark.parametrize("value, ok", [(0, True), (36, True), ("36", True), (9, False), (61, False), ("x", False)])
def test_mrz_accepts_0_or_10_to_60(value, ok):
    d = {"name": "t", "width_mm": 50, "height_mm": 30, "gap_mm": 2,
         "elements": [{"type": "text", "content": "{sku}", "x": 2, "y": 2, "w": 20, "h": 5, "size_pt": 8, "mrz": value}]}
    if ok:
        assert designs.validate(d)["elements"][0]["mrz"] == int(value)
    else:
        with pytest.raises(ValueError):
            designs.validate(d)


def blank(*elements):
    return {"name": "t", "width_mm": 50, "height_mm": 30, "gap_mm": 2, "elements": list(elements)}


def ink(img, box):
    return sum(1 for v in img.convert("L").crop(box).getdata() if v == 0)


def test_a_black_circle_is_round_and_a_white_one_knocks_out_what_is_under_it():
    disc = {"type": "ellipse", "x": 5, "y": 5, "w": 10, "h": 10, "fill": "black", "stroke": 0}
    img = render.render(Label("A"), blank(disc))
    assert img.getpixel((80, 80)) == 0 and img.getpixel((41, 41)) == 255      # the middle is black, the box corner is not
    cut = render.render(Label("A"), blank(disc, {"type": "ellipse", "x": 8, "y": 8, "w": 4, "h": 4, "fill": "white", "stroke": 0}))
    assert cut.getpixel((80, 80)) == 255 and cut.getpixel((50, 80)) == 0


def test_grooves_add_concentric_rings():
    plain = {"type": "ellipse", "x": 5, "y": 5, "w": 12, "h": 12}
    grooved = dict(plain, rings=5, ring_gap=0.5)
    assert ink(render.render(Label("A"), blank(grooved)), (0, 0, 400, 240)) > 2 * ink(render.render(Label("A"), blank(plain)), (0, 0, 400, 240))


def test_the_stamp_edge_is_notched_but_every_corner_is_whole():
    img = render.render(Label("A"), blank({"type": "perforation", "x": 2.5, "y": 2.5, "w": 45, "h": 25, "pitch": 1.25, "radius": 0.4})).convert("L")
    for corner in ((20, 20), (379, 20), (20, 219), (379, 219)):
        assert img.getpixel(corner) == 0, corner
    top = [img.getpixel((x, 20)) for x in range(20, 380)]
    assert 0 in top and 255 in top                                               # the top edge is a row of teeth, not a solid line


@pytest.mark.parametrize("bad", [{"type": "ellipse", "fill": "red"}, {"type": "ellipse", "rings": 99}, {"type": "perforation", "pitch": 0.1}])
def test_new_element_options_are_validated(bad):
    with pytest.raises(ValueError):
        designs.validate(blank(dict({"x": 1, "y": 1, "w": 5, "h": 5}, **bad)))


def test_a_following_flow_text_never_starts_below_its_own_box(monkeypatch):
    """The title under a two-line artist may not drop into the foot line: it stops at its own box bottom."""
    d = designs.validate(load("mf-stamp"))
    title = next(e for e in d["elements"] if e["id"] == "title")
    drawn = []
    real = render.ImageDraw.ImageDraw.text
    monkeypatch.setattr(render.ImageDraw.ImageDraw, "text", lambda self, xy, text, *a, **kw: (drawn.append((text, xy[1])), real(self, xy, text, *a, **kw))[1])
    render.render(Label("GODSPEED01", "Godspeed You! Black Emperor", "Lift Your Skinny Fists Like Antennas To Heaven", "VINYL", "2000", "Post-Rock", 785000), d)
    lowest = max(y for text, y in drawn if text.startswith(("Lift", "Antennas")))
    assert lowest <= (title["y"] + title["h"]) * render.DPM * render.SMOOTH + 1


@pytest.mark.parametrize("label", SAMPLES, ids=lambda label: label.sku)
def test_the_stamp_prints_the_whole_sku_even_a_16_character_one(label, monkeypatch):
    drawn = spy_text(monkeypatch)
    render.render(label, load("mf-stamp"))
    assert label.sku in drawn


# --- the Passport, round 5: no tiny labels, a tall barcode with air below it, and three places for the symbol ---

def boxes(slug):
    return {e["id"]: e for e in designs.validate(load(slug))["elements"]}


def overlap(a, b):
    return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]


@pytest.mark.parametrize("slug", PASSPORTS)
def test_the_passport_has_no_tiny_capital_labels(slug, monkeypatch):
    drawn = spy_text(monkeypatch)
    render.render(SAMPLES[0], load(slug))
    assert not {"ARTIST / TITLE", "PRICE", "FORMAT", "YEAR", "GENRE"} & set(drawn)


@pytest.mark.parametrize("slug", PASSPORTS)
def test_the_passport_barcode_is_tall_and_leaves_air_above_the_machine_readable_lines(slug):
    bar = boxes(slug)["barcode"]
    assert bar["h"] >= 6.5
    img = render.render(SAMPLES[0], load(slug)).convert("L")
    bottom = round((bar["y"] + bar["h"]) * render.DPM)
    first_ink = next(y for y in range(bottom, 240) if any(img.getpixel((x, y)) == 0 for x in range(20, 380)))
    assert first_ink - bottom >= 12, first_ink - bottom       # 1.5 mm


@pytest.mark.parametrize("slug", PASSPORTS)
@pytest.mark.parametrize("label", SAMPLES[:2], ids=lambda label: label.sku)
def test_the_passport_barcode_reads_when_tilted_8_degrees_either_way(slug, label):
    img = render.render(label, load(slug)).convert("L").resize((1600, 960), Image.NEAREST)
    for angle in (-8, 8):
        tilted = img.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=255)
        assert label.sku in [b.text for b in zxingcpp.read_barcodes(tilted)], angle


@pytest.mark.parametrize("slug", PASSPORTS[1:])
def test_the_three_passports_share_one_skeleton_only_the_symbol_moves(slug):
    base, other = boxes("mf-passport"), boxes(slug)
    for key in ("barcode", "mrz1", "mrz2", "format", "year", "artist"):
        assert base[key]["y"] == other[key]["y"] and base[key]["x"] == other[key]["x"], key


@pytest.mark.parametrize("slug", PASSPORTS)
@pytest.mark.parametrize("label", [SAMPLES[2], SAMPLES[1], SAMPLES[0]], ids=lambda label: label.sku)
def test_the_symbol_keeps_0_75_mm_clear_of_everything_else(slug, label):
    from PIL import ImageChops, ImageFilter
    full = load(slug)
    only = dict(full, elements=[e for e in full["elements"] if e["id"] == "symbol"])
    rest = dict(full, elements=[e for e in full["elements"] if e["id"] != "symbol"])
    sym = ImageChops.invert(render.render(label, only).convert("L"))
    others = ImageChops.invert(render.render(label, rest).convert("L")).filter(ImageFilter.MaxFilter(13))   # 6 dots each way
    assert ImageChops.multiply(sym.point(lambda v: 255 if v else 0), others.point(lambda v: 255 if v else 0)).getbbox() is None
    left, top, right, bottom = sym.getbbox()
    assert left >= 20 and top >= 20 and right <= 380 and bottom <= 220


def test_a_horizontal_barcode_can_be_centred_in_its_box():
    bar = {"type": "barcode", "content": "{sku}", "x": 2.5, "y": 5, "w": 45, "h": 6, "mode": "integer"}
    left = render.render(Label("NOUPASC001"), blank(bar)).convert("L")
    mid = render.render(Label("NOUPASC001"), blank(dict(bar, center=True))).convert("L")
    def span(img):
        l, _, r, _ = img.point(lambda v: 255 - v).getbbox()
        return l, 400 - r
    (l0, r0), (l1, r1) = span(left), span(mid)
    assert l0 == 20 and r0 > 40                 # drawn from the left edge, the room is on the right
    assert abs(l1 - r1) <= 1 and l1 > 20        # centred
