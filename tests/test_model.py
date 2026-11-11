import pytest

from labelprinter.model import (
    MAX_COPIES, Label, format_chip, label_from_dealpos, parse_description,
    parse_price, parse_product_name, price_text, split_title_year,
)

DESC = ("<div><br>\n<div>American Football &mdash; Cassette<br>Format: Cassette &mdash; Album &bull; Label: Polyvinyl &bull; Country: US<br>"
        "Released: 1999 (Deluxe reissue) &bull; Genre: Rock &bull; Style: Emo, Indie Rock, Midwest Emo<br>&nbsp;<br>Condition:<br>CASSETTE SEALED</div></div>")


def test_price_text_uses_dot_thousands():
    assert price_text(305000) == "Rp305.000"
    assert price_text(1250000) == "Rp1.250.000"


@pytest.mark.parametrize("raw,expected", [
    (305000, 305000), (305000.0, 305000), ("Rp305.000", 305000), ("305,000", 305000), (None, 0), ("", 0), ("abc", 0),
])
def test_parse_price(raw, expected):
    assert parse_price(raw) == expected


def test_parse_product_name_strips_format_word_and_splits_on_first_dash():
    assert parse_product_name("KASET American Football - American Football (Deluxe Edition)") == (
        "American Football", "American Football (Deluxe Edition)")
    assert parse_product_name("KASET Of Montreal - White Is Relic / Irrealis Mood (SEALED)") == (
        "Of Montreal", "White Is Relic / Irrealis Mood (SEALED)")


def test_parse_product_name_without_dash_is_all_title():
    assert parse_product_name("SYITREN N200 Mini Portable Bluetooth Speaker") == (
        "", "SYITREN N200 Mini Portable Bluetooth Speaker")


@pytest.mark.parametrize("text,chip", [
    ("Cassette Import", "CASSETTE"), ("Cassette Local (Sealed)", "CASSETTE"), ("CD Import", "CD"),
    ("Vinyl Local", "VINYL"), ("CD Accessories", ""), ("Speakers", ""), ("VINYL", "VINYL"), ("CASSETTE", "CASSETTE"),
])
def test_format_chip(text, chip):
    assert format_chip(text) == chip


def test_parse_description_year_and_genre():
    assert parse_description(DESC) == {"year": "1999", "genre": "Rock"}


def test_parse_description_missing_gives_blanks():
    assert parse_description("") == {"year": "", "genre": ""}
    assert parse_description("<div>Selamat datang</div>") == {"year": "", "genre": ""}


def test_label_from_dealpos_maps_fields_and_never_carries_cost():
    product = {"Name": "KASET American Football - American Football (Deluxe Edition)", "Category": "Cassette Import"}
    variant = {"Code": "AMEAMET158", "UnitPrice": 305000, "UnitCost": 207493}
    label = label_from_dealpos(product, variant)
    assert label == Label(sku="AMEAMET158", artist="American Football", title="American Football (Deluxe Edition)",
                          format="CASSETTE", price=305000)
    assert not hasattr(label, "cost") and "207493" not in repr(label)


def test_split_title_year_moves_only_a_trailing_year():
    assert split_title_year("Immunity (2019)") == ("Immunity", "2019")
    assert split_title_year("Baby (2025) ") == ("Baby", "2025")
    assert split_title_year("American Football (Deluxe Edition)") == ("American Football (Deluxe Edition)", "")
    assert split_title_year("1999 (Remastered)") == ("1999 (Remastered)", "")
    assert split_title_year("") == ("", "")


def test_label_from_dealpos_takes_the_year_out_of_the_title():
    label = label_from_dealpos({"Name": "CD Clairo - Immunity (2019)", "Category": "CD Import"},
                               {"Code": "CLAIMMC437", "UnitPrice": 300000})
    assert (label.title, label.year) == ("Immunity", "2019")


def test_label_from_dict_cleans_and_caps_values():
    label = Label.from_dict({"sku": " AB1 ", "artist": "  X ", "price": "Rp1.000", "copies": "999", "bogus": 1})
    assert label.sku == "AB1" and label.artist == "X" and label.price == 1000
    assert label.copies == MAX_COPIES
    assert Label.from_dict({"sku": "A", "copies": 0}).copies == 1
    assert Label.from_dict({"sku": "A", "copies": "x"}).copies == 1
