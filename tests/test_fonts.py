"""The font registry: what fonts a label can use, how a family key becomes a file, and the upload safety rules."""
import os
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from labelprinter import fonts, render
from labelprinter.fonts import FontRegistry

WIN = Path("C:/Windows/Fonts")


# ---------------------------------------------------------------- helpers

def need(*names):
    missing = [n for n in names if not (WIN / n).exists()]
    if missing:
        pytest.skip(f"needs {', '.join(missing)} in {WIN}")


def real_system(tmp_path, *names):
    """A 'system' folder holding a few real Windows fonts, so tests do not depend on every installed font."""
    need(*names)
    d = tmp_path / "system"
    d.mkdir()
    for n in names:
        shutil.copy(WIN / n, d / n)
    return d


def stub_files(directory, names):
    """Empty font files plus the (family, style) a stub reader reports for each, keyed by file name."""
    directory.mkdir(parents=True, exist_ok=True)
    for fname in names:
        (directory / fname).write_bytes(b"stub")
    return names


def registry(tmp_path, system=None, custom=None, bundled=None, names=None):
    """A registry over three folders; with `names` the files are stubs read by file name, without it they are real fonts."""
    reader = (lambda p: names[p.name]) if names is not None else None
    return FontRegistry(system or tmp_path / "nosys", custom or tmp_path / "custom", bundled or tmp_path / "nobundled", reader=reader)


def bump(directory):
    """Make the folder's modified time differ from before, even on a coarse file system clock."""
    st = os.stat(directory)
    os.utime(directory, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))


def by_key(reg):
    return {f["key"]: f for f in reg.families()}


# ---------------------------------------------------------------- scanning

def test_scan_reads_family_keys_and_style_slots(tmp_path):
    system = real_system(tmp_path, "arial.ttf", "arialbd.ttf", "calibri.ttf")
    reg = registry(tmp_path, system=system, bundled=fonts.BUNDLED_DIR)
    fam = by_key(reg)
    assert set(fam) == {"arial", "calibri", "dm-sans", "dm-sans-light", "dm-sans-medium", "dm-sans-semibold"}
    assert fam["arial"] == {"key": "arial", "name": "Arial", "source": "system", "styles": ["regular", "bold"]}
    assert fam["calibri"]["styles"] == ["regular"]
    assert fam["dm-sans"] == {"key": "dm-sans", "name": "DM Sans", "source": "bundled", "styles": ["regular", "bold"]}
    assert [f["name"] for f in reg.families()] == ["Arial", "Calibri", "DM Sans", "DM Sans Light", "DM Sans Medium", "DM Sans SemiBold"]  # sorted by name


def test_bundled_dm_sans_files_read_as_dm_sans_regular_and_bold():
    from PIL import ImageFont
    assert ImageFont.truetype(str(fonts.BUNDLED_DIR / "DMSans-Regular.ttf"), 12).getname() == ("DM Sans", "Regular")
    assert ImageFont.truetype(str(fonts.BUNDLED_DIR / "DMSans-Bold.ttf"), 12).getname() == ("DM Sans", "Bold")


def test_scan_skips_ttc_and_other_extensions(tmp_path):
    names = stub_files(tmp_path / "sys", {"a.ttf": ("Alpha", "Regular"), "b.TTF": ("Beta", "Regular"), "c.otf": ("Gamma", "Regular"),
                                          "d.ttc": ("Delta", "Regular"), "e.fon": ("Epsilon", "Regular"), "f.txt": ("Zeta", "Regular")})
    assert set(by_key(registry(tmp_path, system=tmp_path / "sys", names=names))) == {"alpha", "beta", "gamma"}


def test_every_style_name_lands_in_the_right_slot(tmp_path):
    names = stub_files(tmp_path / "sys", {
        "1.ttf": ("Foo", "Regular"), "2.ttf": ("Foo", "Bold"), "3.ttf": ("Foo", "Italic"), "4.ttf": ("Foo", "Bold Italic"),
        "5.ttf": ("Bar", "Book"), "6.ttf": ("Bar", "Oblique"), "7.ttf": ("Bar", "Bold Oblique"),
        "8.ttf": ("Baz", "Normal"), "9.ttf": ("Qux", "Roman")})
    fam = by_key(registry(tmp_path, system=tmp_path / "sys", names=names))
    assert fam["foo"]["styles"] == ["regular", "bold", "italic", "bolditalic"]
    assert fam["bar"]["styles"] == ["regular", "italic", "bolditalic"]
    assert fam["baz"]["styles"] == ["regular"] and fam["qux"]["styles"] == ["regular"]


def test_a_light_style_becomes_its_own_family(tmp_path):
    names = stub_files(tmp_path / "sys", {
        "l1.ttf": ("Lato", "Regular"), "l2.ttf": ("Lato", "Light"), "l3.ttf": ("Lato", "Light Italic"), "l4.ttf": ("Lato", "Black"),
        "l5.ttf": ("Lato", "Semibold Italic"), "l6.ttf": ("Lato", "Italic"), "l7.ttf": ("Lato", "Bold")})
    fam = by_key(registry(tmp_path, system=tmp_path / "sys", names=names))
    assert set(fam) == {"lato", "lato-light", "lato-black", "lato-semibold"}
    assert fam["lato-light"]["name"] == "Lato Light" and fam["lato-light"]["styles"] == ["regular", "italic"]
    assert fam["lato-black"]["styles"] == ["regular"] and fam["lato-semibold"]["styles"] == ["italic"]
    assert fam["lato"]["styles"] == ["regular", "bold", "italic"]


def test_a_style_named_after_its_family_is_read_as_the_plain_style(tmp_path):
    names = stub_files(tmp_path / "sys", {
        "d1.otf": ("D-DIN", "Regular"), "d2.otf": ("D-DIN", "DIN-Bold"), "d3.otf": ("D-DIN", "DIN-Italic"),
        "c1.otf": ("D-DIN Condensed", "Regular"), "c2.otf": ("D-DIN Condensed", "DINCondensed-Bold"),
        "l1.ttf": ("Lato", "Regular"), "l2.ttf": ("Lato", "Semi-Bold")})
    fam = by_key(registry(tmp_path, system=tmp_path / "sys", names=names))
    assert set(fam) == {"d-din", "d-din-condensed", "lato", "lato-semi-bold"}
    assert fam["d-din"]["styles"] == ["regular", "bold", "italic"] and fam["d-din-condensed"]["styles"] == ["regular", "bold"]


def test_a_real_calibri_light_file_is_its_own_family(tmp_path):
    system = real_system(tmp_path, "calibri.ttf", "calibril.ttf")
    fam = by_key(registry(tmp_path, system=system))
    assert fam["calibri-light"]["name"] == "Calibri Light" and fam["calibri"]["styles"] == ["regular"]


@pytest.mark.parametrize("family", ["Segoe UI Symbol", "Wingdings", "Webdings", "Marlett", "Font Awesome 6 Pro", "Segoe MDL2 Assets",
                                    "Segoe Fluent Icons", "Segoe UI Emoji", "Some Dingbats"])
def test_symbol_and_icon_fonts_are_skipped(tmp_path, family):
    names = stub_files(tmp_path / "sys", {"s.ttf": (family, "Regular"), "ok.ttf": ("Plain", "Regular")})
    assert set(by_key(registry(tmp_path, system=tmp_path / "sys", names=names))) == {"plain"}


def test_family_keys_are_slugs_even_for_awkward_names(tmp_path):
    names = stub_files(tmp_path / "sys", {"a.ttf": ("  Ünï  côdé!! 9  ", "Regular"), "b.ttf": ("X" * 100, "Regular"), "c.ttf": ("宋体", "Regular")})
    for key in by_key(registry(tmp_path, system=tmp_path / "sys", names=names)):
        assert fonts.valid_key(key), key


def test_a_file_pillow_cannot_read_is_skipped(tmp_path):
    system = real_system(tmp_path, "arial.ttf")
    (system / "broken.ttf").write_bytes(b"this is not a font")
    assert set(by_key(registry(tmp_path, system=system))) == {"arial"}


def test_font_names_are_cleaned_of_control_characters(tmp_path):
    names = stub_files(tmp_path / "sys", {"a.ttf": ("Evil\r\nHeader: x\x00", "Regular")})
    (family,) = registry(tmp_path, system=tmp_path / "sys", names=names).families()
    assert "\r" not in family["name"] and "\n" not in family["name"] and "\x00" not in family["name"]


# ---------------------------------------------------------------- precedence

def test_custom_beats_bundled_beats_system_and_each_slot_is_decided_separately(tmp_path):
    names = {}
    names.update(stub_files(tmp_path / "sys", {"sys-r.ttf": ("Foo", "Regular"), "sys-b.ttf": ("Foo", "Bold")}))
    names.update(stub_files(tmp_path / "bun", {"bun-r.ttf": ("Foo", "Regular")}))
    names.update(stub_files(tmp_path / "cus", {"cus-r.ttf": ("Foo", "Regular")}))
    reg = registry(tmp_path, system=tmp_path / "sys", bundled=tmp_path / "bun", custom=tmp_path / "cus", names=names)
    assert reg.resolve("foo", False, False) == tmp_path / "cus" / "cus-r.ttf"
    assert reg.resolve("foo", True, False) == tmp_path / "sys" / "sys-b.ttf"   # only the slot the custom file covers is replaced
    assert by_key(reg)["foo"]["source"] == "custom"
    (tmp_path / "cus" / "cus-r.ttf").unlink()
    bump(tmp_path / "cus")
    assert reg.resolve("foo", False, False) == tmp_path / "bun" / "bun-r.ttf" and by_key(reg)["foo"]["source"] == "bundled"
    (tmp_path / "bun" / "bun-r.ttf").unlink()
    bump(tmp_path / "bun")
    assert reg.resolve("foo", False, False) == tmp_path / "sys" / "sys-r.ttf" and by_key(reg)["foo"]["source"] == "system"


# ---------------------------------------------------------------- resolve and status

def slots_registry(tmp_path):
    names = stub_files(tmp_path / "sys", {
        "all-r.ttf": ("All", "Regular"), "all-b.ttf": ("All", "Bold"), "all-i.ttf": ("All", "Italic"), "all-bi.ttf": ("All", "Bold Italic"),
        "one-r.ttf": ("One", "Regular"),
        "rb-r.ttf": ("Rb", "Regular"), "rb-b.ttf": ("Rb", "Bold"),
        "ri-r.ttf": ("Ri", "Regular"), "ri-i.ttf": ("Ri", "Italic"),
        "bo-b.ttf": ("Bo", "Bold"), "bo-i.ttf": ("Bo", "Italic")})
    return registry(tmp_path, system=tmp_path / "sys", names=names), tmp_path / "sys"


@pytest.mark.parametrize("key,bold,italic,want", [
    ("all", False, False, "all-r"), ("all", True, False, "all-b"), ("all", False, True, "all-i"), ("all", True, True, "all-bi"),
    ("one", True, False, "one-r"), ("one", False, True, "one-r"), ("one", True, True, "one-r"),         # everything falls back to regular
    ("rb", False, True, "rb-r"), ("rb", True, True, "rb-b"),                                              # bold italic -> bold
    ("ri", True, False, "ri-r"), ("ri", True, True, "ri-i"),                                              # bold italic -> italic when no bold
    ("bo", True, True, "bo-b"),                                                                           # bold before italic
    ("bo", False, False, "bo-b"),                                                                         # no regular at all: any slot beats nothing
])
def test_resolve_picks_the_exact_slot_or_falls_back(tmp_path, key, bold, italic, want):
    reg, system = slots_registry(tmp_path)
    assert reg.resolve(key, bold, italic) == system / f"{want}.ttf"


def test_legacy_font_names_still_work(tmp_path):
    names = stub_files(tmp_path / "sys", {"t.ttf": ("Times New Roman", "Regular"), "c.ttf": ("Courier New", "Regular")})
    reg = registry(tmp_path, system=tmp_path / "sys", names=names)
    assert reg.resolve("times") == reg.resolve("times-new-roman") == tmp_path / "sys" / "t.ttf"
    assert reg.resolve("courier") == reg.resolve("courier-new") == tmp_path / "sys" / "c.ttf"
    assert reg.status("times", False, False) is None and reg.status("courier", False, False) is None
    assert fonts.canonical_key("times") == "times-new-roman" and fonts.canonical_key("arial") == "arial"


def test_an_unknown_key_falls_back_to_arial_then_to_dm_sans(tmp_path):
    system = real_system(tmp_path, "arial.ttf", "arialbd.ttf")
    reg = registry(tmp_path, system=system, bundled=fonts.BUNDLED_DIR)
    assert reg.resolve("nope", False, False) == system / "arial.ttf"
    assert reg.resolve("nope", True, False) == system / "arialbd.ttf"
    only_bundled = registry(tmp_path, bundled=fonts.BUNDLED_DIR)
    assert only_bundled.resolve("nope", True, True) == fonts.BUNDLED_DIR / "DMSans-Regular.ttf"
    with pytest.raises(FileNotFoundError):
        registry(tmp_path).resolve("nope", False, False)


@pytest.mark.parametrize("key", ["..\\x", "../x", "C:\\Windows\\arial", "", "UP", "x" * 61, None, 5])
def test_keys_that_are_not_keys_never_reach_a_path(tmp_path, key):
    system = real_system(tmp_path, "arial.ttf")
    reg = registry(tmp_path, system=system, bundled=fonts.BUNDLED_DIR)
    assert reg.resolve(key, False, False) == system / "arial.ttf"
    assert "arial" in reg.status(key, False, False).lower()


def test_status_says_in_plain_words_when_the_font_is_not_exact(tmp_path):
    names = stub_files(tmp_path / "sys", {"a.ttf": ("Arial", "Regular"), "c.ttf": ("Calibri", "Regular"), "cb.ttf": ("Calibri", "Bold")})
    reg = registry(tmp_path, system=tmp_path / "sys", names=names)
    assert reg.status("arial", False, False) is None
    assert reg.status("calibri", True, False) is None
    assert reg.status("foo", False, False) == "Font 'foo' is not installed here, using Arial."
    assert reg.status("calibri", False, True) == "Calibri has no italic, showing regular."
    assert reg.status("calibri", True, True) == "Calibri has no bold italic, showing bold."
    assert reg.status("arial", True, False) == "Arial has no bold, showing regular."
    no_arial = registry(tmp_path, system=tmp_path / "empty", bundled=fonts.BUNDLED_DIR)
    assert no_arial.status("foo", False, False) == "Font 'foo' is not installed here, using DM Sans."


# ---------------------------------------------------------------- cache

def test_the_scan_is_cached_until_a_folder_changes(tmp_path):
    names = stub_files(tmp_path / "sys", {"a.ttf": ("Alpha", "Regular")})
    seen = []
    reg = FontRegistry(tmp_path / "sys", tmp_path / "custom", tmp_path / "bundled", reader=lambda p: (seen.append(p.name), names[p.name])[1])
    reg.families(); reg.resolve("alpha"); reg.status("alpha", False, False)
    assert seen == ["a.ttf"]                               # read once, not once per call
    names["b.ttf"] = ("Beta", "Regular")
    (tmp_path / "sys" / "b.ttf").write_bytes(b"stub")
    bump(tmp_path / "sys")
    assert {f["key"] for f in reg.families()} == {"alpha", "beta"}
    assert reg.resolve("beta") == tmp_path / "sys" / "b.ttf"


def test_families_returns_copies(tmp_path):
    names = stub_files(tmp_path / "sys", {"a.ttf": ("Alpha", "Regular")})
    reg = registry(tmp_path, system=tmp_path / "sys", names=names)
    reg.families()[0]["styles"].append("junk")
    assert reg.families()[0]["styles"] == ["regular"]


# ---------------------------------------------------------------- add_custom / remove_custom

def two_folder_registry(tmp_path):
    """System has Arial only, so uploading Verdana makes a family the system does not have."""
    system = real_system(tmp_path, "arial.ttf", "arialbd.ttf", "verdana.ttf", "verdanab.ttf")
    only = tmp_path / "only-arial"
    only.mkdir()
    for n in ("arial.ttf", "arialbd.ttf"):
        shutil.copy(system / n, only / n)
    return registry(tmp_path, system=only, bundled=fonts.BUNDLED_DIR), (system / "verdana.ttf").read_bytes(), (system / "verdanab.ttf").read_bytes()


def test_add_custom_stores_a_real_font_and_returns_a_key_that_resolves(tmp_path):
    reg, verdana, verdana_bold = two_folder_registry(tmp_path)
    key = reg.add_custom("My Verdana.ttf", verdana)
    assert key == "verdana"
    assert by_key(reg)["verdana"]["source"] == "custom" and by_key(reg)["verdana"]["styles"] == ["regular"]
    path = reg.resolve(key, False, False)
    assert path.parent == tmp_path / "custom" and path.read_bytes() == verdana
    assert reg.add_custom("whatever.ttf", verdana_bold) == "verdana"                      # same family, other slot
    assert by_key(reg)["verdana"]["styles"] == ["regular", "bold"]
    assert reg.add_custom("again.ttf", verdana) == "verdana"                              # same slot again replaces, never duplicates
    assert len(list((tmp_path / "custom").iterdir())) == 2


def test_add_custom_refuses_what_is_not_a_font(tmp_path):
    reg, verdana, _ = two_folder_registry(tmp_path)
    with pytest.raises(ValueError, match="Not a font file."):
        reg.add_custom("notes.ttf", b"just some text, renamed")
    with pytest.raises(ValueError, match="Not a font file."):
        reg.add_custom("empty.otf", b"")
    with pytest.raises(ValueError, match=r"\.ttf"):
        reg.add_custom("setup.exe", verdana)
    with pytest.raises(ValueError):
        reg.add_custom("font", verdana)
    with pytest.raises(ValueError):
        reg.add_custom("font.ttf.exe", verdana)
    with pytest.raises(ValueError, match="5 MB"):
        reg.add_custom("big.ttf", b"\0" * (5 * 1024 * 1024 + 1))
    assert not (tmp_path / "custom").exists() or not list((tmp_path / "custom").iterdir())


def test_add_custom_refuses_symbol_fonts(tmp_path):
    need("segmdl2.ttf")
    reg, _, _ = two_folder_registry(tmp_path)
    with pytest.raises(ValueError, match="symbol"):
        reg.add_custom("icons.ttf", (WIN / "segmdl2.ttf").read_bytes())


def test_the_uploaded_file_name_is_never_used(tmp_path):
    reg, verdana, _ = two_folder_registry(tmp_path)
    before = {p for p in tmp_path.rglob("*")}
    reg.add_custom("..\\..\\evil.ttf", verdana)
    reg.add_custom("../../evil2.ttf", verdana)
    reg.add_custom("C:\\Windows\\Fonts\\arial.ttf", verdana)
    new = {p for p in tmp_path.rglob("*")} - before
    assert all(p.is_relative_to(tmp_path / "custom") for p in new)
    assert [p.name for p in (tmp_path / "custom").iterdir()] == ["verdana--regular.ttf"]
    assert (WIN / "arial.ttf").stat().st_size > 0 and not (tmp_path / "evil.ttf").exists()


def test_the_custom_font_count_is_capped(tmp_path, monkeypatch):
    reg, verdana, verdana_bold = two_folder_registry(tmp_path)
    monkeypatch.setattr(fonts, "MAX_CUSTOM_FILES", 1)
    reg.add_custom("a.ttf", verdana)
    reg.add_custom("a2.ttf", verdana)                                                      # replacing is not adding
    with pytest.raises(ValueError, match="Remove"):
        reg.add_custom("b.ttf", verdana_bold)


def test_remove_custom_deletes_only_custom_families(tmp_path):
    reg, verdana, verdana_bold = two_folder_registry(tmp_path)
    reg.add_custom("a.ttf", verdana)
    reg.add_custom("b.ttf", verdana_bold)
    reg.remove_custom("verdana")
    assert "verdana" not in by_key(reg) and not list((tmp_path / "custom").iterdir())
    for key in ("arial", "dm-sans", "nope", "..\\x", "../arial", "", "UP", "x" * 61):     # system, bundled, unknown, not keys
        with pytest.raises(KeyError):
            reg.remove_custom(key)
    assert (tmp_path / "only-arial" / "arial.ttf").exists() and (fonts.BUNDLED_DIR / "DMSans-Regular.ttf").exists()
    with pytest.raises(KeyError):
        reg.remove_custom("verdana")                                                       # already gone


def test_removing_a_custom_font_that_was_used_to_draw_works(tmp_path):
    reg, verdana, _ = two_folder_registry(tmp_path)
    key = reg.add_custom("v.ttf", verdana)
    f = render.font(reg.resolve(key), 20)                       # cached by the renderer, as after a real preview
    ImageDraw.Draw(Image.new("L", (80, 40), 255)).text((0, 0), "Hi", font=f, fill=0)
    reg.remove_custom(key)
    assert not list((tmp_path / "custom").iterdir())


def test_a_custom_family_that_shadows_a_system_one_gives_the_system_one_back_when_removed(tmp_path):
    system = real_system(tmp_path, "verdana.ttf", "verdanab.ttf")
    reg = registry(tmp_path, system=system, bundled=fonts.BUNDLED_DIR)
    reg.add_custom("v.ttf", (system / "verdana.ttf").read_bytes())
    assert by_key(reg)["verdana"]["source"] == "custom"
    reg.remove_custom("verdana")
    assert by_key(reg)["verdana"]["source"] == "system" and by_key(reg)["verdana"]["styles"] == ["regular", "bold"]


def test_key_pattern():
    assert fonts.valid_key("dm-sans") and fonts.valid_key("a") and fonts.valid_key("9x") and fonts.valid_key("a" * 60)
    for bad in ("..\\x", "../x", "-lead", "UPPER", "a b", "", "a" * 61, "a.b", "arial\n"):
        assert not fonts.valid_key(bad), bad
    assert not fonts.valid_key(None) and not fonts.valid_key(5)


def test_the_default_registry_reads_the_environment_and_project_folders():
    assert fonts.BUNDLED_DIR == Path(fonts.__file__).resolve().parent / "fonts"
    assert fonts.CUSTOM_DIR == Path(fonts.__file__).resolve().parents[1] / "data" / "fonts"
