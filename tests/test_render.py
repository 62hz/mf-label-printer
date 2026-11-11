import copy

import pytest
import zxingcpp

from labelprinter.model import Label
from labelprinter.render import bars, expand, notes, png_bytes, render, size_dots
from tests.fakes import design

AMERICAN = Label("AMEAMET158", "American Football", "American Football (Deluxe Edition)", "CASSETTE", "2014",
                 "Rock / Punk / New Wave", 305000)
DIGITS = Label("191404155127", "Charli XCX", "Brat", "VINYL", "2024", "Pop", 345000)
LONG = Label("ALEHEAC557", "A" * 80, "B" * 120, "CD", "2025", "G" * 60, 355000)
SLUGS = ["mf-april", "mf-large", "mf-scan-safe"]


def decode(img):
    return [(r.format.name, r.text) for r in zxingcpp.read_barcodes(img.convert("L"))]


def tweak(slug, element_id, **changes):
    d = copy.deepcopy(design(slug))
    for el in d["elements"]:
        if el["id"] == element_id:
            el.update(changes)
    return d


@pytest.mark.parametrize("slug", SLUGS)
@pytest.mark.parametrize("label", [AMERICAN, DIGITS, LONG])
def test_every_builtin_design_renders_one_bit_and_the_barcode_decodes_to_the_sku(slug, label):
    img = render(label, design(slug))
    assert img.mode == "1" and img.size == (400, 240)
    assert decode(img) == [("Code128", label.sku)]


def test_scan_safe_design_uses_two_dot_bars_for_a_ten_char_sku():
    assert notes(AMERICAN, design("mf-scan-safe")) == []
    assert "1 dot" in notes(AMERICAN, design("mf-april"))[0]


def test_stretched_barcode_is_flagged():
    stretched = tweak("mf-april", "barcode", mode="fit", w=23)
    assert "Stretched" in notes(AMERICAN, stretched)[0]


def test_empty_label_fields_do_not_crash_and_empty_chips_are_not_drawn():
    img = render(Label("ABC123"), design("mf-april"))
    assert decode(img) == [("Code128", "ABC123")]
    chip_dots = [img.getpixel((x, y)) for x in range(31 * 8, 47 * 8) for y in range(int(8.6 * 8), int(11 * 8))]
    assert all(v == 255 for v in chip_dots)  # no black chip box without format text


def test_bad_sku_raises_value_error():
    d = design("mf-april")
    with pytest.raises(ValueError, match="empty"):
        render(Label(""), d)
    with pytest.raises(ValueError, match="cannot print"):
        render(Label("SKUé"), d)
    with pytest.raises(ValueError, match="at least"):
        render(Label("X" * 40), d)


def test_changing_a_design_changes_the_output():
    base = render(AMERICAN, design("mf-april")).tobytes()
    assert render(AMERICAN, tweak("mf-april", "artist", size_pt=9)).tobytes() != base
    assert render(AMERICAN, tweak("mf-april", "logo", visible=False)).tobytes() != base
    assert render(AMERICAN, tweak("mf-april", "artist", content="{title}")).tobytes() != base


def test_a_design_can_use_the_bundled_dm_sans():
    base = render(AMERICAN, design("mf-april")).tobytes()
    dm = render(AMERICAN, tweak("mf-april", "artist", font="dm-sans")).tobytes()
    assert dm != base and render(AMERICAN, tweak("mf-april", "artist", font="dm-sans")).tobytes() == dm   # and it is deterministic
    assert render(AMERICAN, tweak("mf-april", "artist", font="dm-sans")).size == (400, 240)


def test_dm_sans_bold_uses_the_bold_file():
    regular = render(AMERICAN, tweak("mf-april", "artist", font="dm-sans", bold=False)).tobytes()
    bold = render(AMERICAN, tweak("mf-april", "artist", font="dm-sans", bold=True)).tobytes()
    assert regular != bold


def test_a_font_that_is_not_installed_still_renders_with_arial_and_says_so():
    ghost = tweak("mf-april", "year", font="no-such-font")
    assert render(AMERICAN, ghost).tobytes() == render(AMERICAN, tweak("mf-april", "year", font="arial")).tobytes()
    assert "Font 'no-such-font' is not installed here, using Arial." in notes(AMERICAN, ghost)


def test_notes_name_each_font_problem_once_and_after_the_barcode_notes():
    d = copy.deepcopy(design("mf-april"))
    for el in d["elements"]:
        if el["type"] == "text":
            el["font"] = "no-such-font"
    out = notes(AMERICAN, d)
    assert "1 dot" in out[0] and out.count("Font 'no-such-font' is not installed here, using Arial.") == 1
    assert len(out) == len(set(out))


def test_a_missing_style_is_reported_in_plain_words():
    italic = tweak("mf-april", "title", font="dm-sans", italic=True)                  # DM Sans is bundled as regular and bold only
    assert "DM Sans has no italic, showing regular." in notes(AMERICAN, italic)


def test_hidden_text_elements_add_no_font_notes():
    hidden = tweak("mf-april", "year", font="no-such-font", visible=False)
    assert not any("no-such-font" in n for n in notes(AMERICAN, hidden))


def test_built_in_designs_have_exact_fonts():
    for slug in SLUGS:
        assert not any("font" in n.lower() or "has no" in n for n in notes(AMERICAN, design(slug)))


def test_label_size_follows_the_design():
    d = copy.deepcopy(design("mf-april"))
    d.update(width_mm=40, height_mm=25)
    d["elements"] = [dict(e, w=30) for e in d["elements"] if e["id"] in ("artist", "barcode")]
    assert size_dots(d) == (320, 200) and render(AMERICAN, d).size == (320, 200)


def test_expand_fills_fields_and_unknown_names_become_empty():
    assert expand("{year} / {genre}", AMERICAN) == "2014 / Rock / Punk / New Wave"
    assert expand("{price}", Label("A", price=1000)) == "Rp1.000"
    assert expand("{nope}", AMERICAN) == ""


def test_long_text_is_cut_not_overflowing_the_element():
    img = render(LONG, design("mf-april"))
    for x in range(int(48.2 * 8), 400):  # right of the artist/title boxes
        assert all(img.getpixel((x, y)) == 255 for y in range(int(1.6 * 8), int(7.8 * 8)))


def test_png_bytes_is_a_png():
    assert png_bytes(AMERICAN, design("mf-april"))[:8] == b"\x89PNG\r\n\x1a\n"


def test_bars_codes():
    assert len(bars("AMEAMET158")) == 145
