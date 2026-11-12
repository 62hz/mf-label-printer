import copy
import json

import pytest

from labelprinter import designs
from labelprinter.designs import DesignStore, slugify, validate
from tests.fakes import design


def test_builtin_designs_are_listed_valid_and_read_only(tmp_path):
    store = DesignStore(tmp_path / "mine")
    rows = store.list()
    assert [r["slug"] for r in rows] == ["mf-april", "mf-concept-price-card", "mf-large", "mf-passport-row", "mf-scan-safe"] and all(r["builtin"] for r in rows)
    assert store.get(designs.DEFAULT_SLUG)["width_mm"] == 50
    with pytest.raises(ValueError, match="read-only"):
        store.save(design("mf-april"))
    with pytest.raises(ValueError, match="cannot be deleted"):
        store.delete("mf-april")
    with pytest.raises(KeyError):
        store.get("nope")


def test_save_list_get_delete_user_design(tmp_path):
    store = DesignStore(tmp_path / "mine")
    mine = copy.deepcopy(design("mf-april"))
    mine["name"] = "CD shelf 2"
    slug = store.save(mine)
    assert slug == "cd-shelf-2"
    assert {"slug": "cd-shelf-2", "name": "CD shelf 2", "builtin": False} in store.list()
    assert store.get("cd-shelf-2")["name"] == "CD shelf 2"
    store.delete("cd-shelf-2")
    assert all(r["builtin"] for r in store.list())
    with pytest.raises(KeyError):
        store.delete("cd-shelf-2")


def test_a_broken_user_file_is_skipped_not_fatal(tmp_path):
    (tmp_path / "mine").mkdir()
    (tmp_path / "mine" / "bad.json").write_text("{not json", encoding="utf-8")
    assert all(r["builtin"] for r in DesignStore(tmp_path / "mine").list())


def test_slugify():
    assert slugify("  CD Shelf / 2! ") == "cd-shelf-2" and slugify("???") == "design"


@pytest.mark.parametrize("mutate,message", [
    (lambda d: d.update(name=""), "name"),
    (lambda d: d.update(width_mm=500), "width_mm"),
    (lambda d: d.update(gap_mm="x"), "gap_mm"),
    (lambda d: d.update(direction=5), "direction"),
    (lambda d: d.update(elements="no"), "elements"),
    (lambda d: d["elements"].append({"type": "blob", "x": 0, "y": 0, "w": 1, "h": 1}), "type"),
    (lambda d: d["elements"][0].update(content="{bogus}"), "unknown field"),
    (lambda d: d["elements"][0].update(font="Comic Sans"), "font"),
    (lambda d: d["elements"][0].update(font="..\\x"), "font"),
    (lambda d: d["elements"][0].update(font=""), "font"),
    (lambda d: d["elements"][0].update(font="a" * 61), "font"),
    (lambda d: d["elements"][0].update(font=7), "font"),
    (lambda d: d["elements"][0].update(size_pt=500), "size_pt"),
    (lambda d: d["elements"][0].update(w=0), "w must"),
    (lambda d: d["elements"].extend([d["elements"][0]] * 45), "Too many"),
])
def test_validate_rejects_bad_designs_with_a_clear_message(mutate, message):
    d = copy.deepcopy(design("mf-april"))
    mutate(d)
    with pytest.raises(ValueError, match=message):
        validate(d)


def test_validate_fills_defaults_and_makes_ids_unique():
    d = validate({"name": "x", "width_mm": 50, "height_mm": 30, "gap_mm": 2, "elements": [
        {"type": "rect", "x": 0, "y": 0, "w": 5, "h": 1}, {"id": "e1", "type": "text", "x": 1, "y": 1, "w": 5, "h": 2, "size_pt": 6}]})
    assert d["direction"] == 1 and [e["id"] for e in d["elements"]] == ["e1", "e1-2"]
    assert d["elements"][1]["font"] == "arial" and d["elements"][1]["align"] == "left"


def test_any_well_formed_font_key_is_valid_even_if_it_is_not_installed():
    d = copy.deepcopy(design("mf-april"))
    for key in ("dm-sans", "comic", "not-installed-anywhere", "a" * 60):
        d["elements"][0]["font"] = key
        assert validate(d)["elements"][0]["font"] == key
    assert not hasattr(designs, "FONTS")


def test_legacy_font_names_are_upgraded_to_their_family_keys():
    d = copy.deepcopy(design("mf-april"))
    for old, new in (("times", "times-new-roman"), ("courier", "courier-new")):
        d["elements"][0]["font"] = old
        assert validate(d)["elements"][0]["font"] == new


def test_builtin_json_files_round_trip_through_validate():
    for p in designs.BUILTIN_DIR.glob("*.json"):
        raw = json.loads(p.read_text(encoding="utf-8"))
        assert validate(raw)["name"] == raw["name"]
