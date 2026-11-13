import io
import shutil
from pathlib import Path

import openpyxl
import pymupdf
import pytest
from PIL import Image
from starlette.testclient import TestClient

from labelprinter import fonts, server
from labelprinter.catalog import Catalog
from labelprinter.designs import DesignStore
from labelprinter.server import MAX_ROWS, MAX_TOTAL, create_app
from tests.fakes import FakeClient, design

PASSWORD = "correct-horse"
LABEL = {"sku": "AMEAMET158", "artist": "American Football", "title": "Deluxe", "format": "CASSETTE",
         "year": "1999", "genre": "Rock", "price": 305000, "copies": 2}


@pytest.fixture
def client(tmp_path):
    app = create_app(Catalog(FakeClient()), PASSWORD, b"k" * 32, DesignStore(tmp_path / "designs"))
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def signed_in(client):
    r = client.post("/login", data={"password": PASSWORD})
    assert r.status_code == 303 and r.headers["location"] == "/"
    return client


def test_everything_is_closed_until_login(client):
    r = client.get("/")                                  # the sign-in page itself, not a redirect (a bare 303 is saved as a download by some phone browsers)
    assert r.status_code == 200 and 'action="/login"' in r.text and r.headers["content-type"].startswith("text/html")
    for path in ("/api/status", "/api/search?q=a", "/api/test.tspl", "/api/test.pdf", "/api/designs", "/api/designs/mf-april", "/api/fonts"):
        assert client.get(path).status_code == 401
    for path in ("/api/resolve", "/api/labels.pdf", "/api/labels.xlsx", "/api/labels.tspl", "/api/label.png", "/api/sheet",
                 "/api/enrich", "/api/designs", "/api/fonts"):
        assert client.post(path, json={}).status_code == 401
    assert client.delete("/api/designs/x").status_code == 401
    assert client.delete("/api/fonts/x").status_code == 401
    assert client.get("/login").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_wrong_password_and_throttle(client):
    r = client.post("/login", data={"password": "nope"})
    assert r.status_code == 303 and r.headers["location"] == "/login?bad=1"
    for _ in range(12):
        client.post("/login", data={"password": "nope"})
    assert client.post("/login", data={"password": PASSWORD}).status_code == 429


def test_login_then_logout(signed_in):
    assert signed_in.get("/").status_code == 200
    signed_in.post("/logout")
    signed_in.cookies.clear()
    assert signed_in.get("/api/status").status_code == 401


def test_logout_revokes_a_copy_of_the_cookie(signed_in):
    copy = signed_in.cookies.get("lp_session")
    assert copy and signed_in.get("/api/status").status_code == 200
    signed_in.post("/logout")
    signed_in.cookies.set("lp_session", copy)   # an attacker replays the cookie they copied before sign-out
    assert signed_in.get("/api/status").status_code == 401


def test_logout_leaves_another_session_signed_in(client):
    one = client.post("/login", data={"password": PASSWORD}).cookies.get("lp_session")
    two = client.post("/login", data={"password": PASSWORD}).cookies.get("lp_session")
    assert one != two
    client.cookies.set("lp_session", one)
    client.post("/logout")
    client.cookies.set("lp_session", two)
    assert client.get("/api/status").status_code == 200


def test_resolve_search_status_enrich(signed_in):
    body = signed_in.post("/api/resolve", json={"text": "AMEAMET158 nope"}).json()
    assert [l["sku"] for l in body["labels"]] == ["AMEAMET158"] and body["missing"] == ["nope"]
    assert "207493" not in signed_in.post("/api/resolve", json={"text": "AMEAMET158"}).text  # cost never leaves the server
    assert [l["sku"] for l in signed_in.get("/api/search?q=nourished").json()["labels"]] == ["NOUPASC001", "NOUPASC002"]
    assert signed_in.get("/api/status").json()["products"] == 3
    assert signed_in.post("/api/enrich", json={"sku": "AMEAMET158"}).json() == {"year": "1999", "genre": "Rock"}
    assert signed_in.post("/api/enrich", json={}).status_code == 400
    assert signed_in.post("/api/refresh").json() == {"products": 3, "refreshed": False}  # the list was read a moment ago


def test_label_png_uses_the_default_design_a_slug_or_an_inline_design(signed_in):
    r = signed_in.post("/api/label.png", json={"label": LABEL})
    assert r.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(r.content)).size == (400, 240)
    assert r.headers["x-label-notes"] == ""                                  # a 10-character SKU gets 2-dot bars on the default Passport
    long_sku = signed_in.post("/api/label.png", json={"label": dict(LABEL, sku="ABCDEFGHIJKLMNOP")})
    assert long_sku.status_code == 200 and "1 dot" in long_sku.headers["x-label-notes"]   # a 16-character one prints, with the note
    by_slug = signed_in.post("/api/label.png", json={"label": LABEL, "design": "mf-large"}).content
    assert by_slug != r.content
    inline = design("mf-april")
    inline["elements"][0]["size_pt"] = 9
    assert signed_in.post("/api/label.png", json={"label": LABEL, "design": inline}).content != r.content
    assert signed_in.post("/api/label.png", json={"label": LABEL, "design": "nope"}).status_code == 400
    bad = design("mf-april")
    bad["elements"][0]["font"] = "Comic Sans!"            # not a font key at all
    assert "font" in signed_in.post("/api/label.png", json={"label": LABEL, "design": bad}).json()["error"]


def test_a_font_that_is_not_installed_renders_with_a_note(signed_in):
    ghost = design("mf-april")
    ghost["elements"][0]["font"] = "comic"
    r = signed_in.post("/api/label.png", json={"label": LABEL, "design": ghost})
    assert r.status_code == 200 and Image.open(io.BytesIO(r.content)).size == (400, 240)
    assert "Font 'comic' is not installed here, using Arial." in r.headers["x-label-notes"]


def test_notes_with_non_latin_text_still_make_a_valid_header(signed_in, monkeypatch):
    monkeypatch.setattr(server, "notes", lambda label, design: ["Zażółć gęślą jaźń Привет 中文", "line\r\nbreak"])
    r = signed_in.post("/api/label.png", json={"label": LABEL})
    assert r.status_code == 200 and "\r" not in r.headers["x-label-notes"] and "\n" not in r.headers["x-label-notes"]
    assert r.headers["x-label-notes"].startswith("Za")


def test_designs_api_list_get_save_delete(signed_in):
    body = signed_in.get("/api/designs").json()
    assert body["default"] == "mf-passport-row" and [d["slug"] for d in body["designs"]][:5] == ["mf-april", "mf-concept-price-card", "mf-large", "mf-passport-row", "mf-scan-safe"]
    assert "fonts" not in body                                       # the font list has its own route: /api/fonts
    assert signed_in.get("/api/designs/mf-april").json()["width_mm"] == 50
    assert signed_in.get("/api/designs/nope").status_code == 404
    mine = design("mf-april")
    mine["name"] = "CD shelf"
    assert signed_in.post("/api/designs", json=mine).json() == {"slug": "cd-shelf"}
    assert any(d["slug"] == "cd-shelf" and not d["builtin"] for d in signed_in.get("/api/designs").json()["designs"])
    assert signed_in.delete("/api/designs/cd-shelf").json() == {"deleted": "cd-shelf"}
    assert signed_in.delete("/api/designs/cd-shelf").status_code == 404
    builtin = design("mf-april")
    assert "read-only" in signed_in.post("/api/designs", json=builtin).json()["error"]
    assert signed_in.delete("/api/designs/mf-april").status_code == 400
    mine["elements"][0]["content"] = "{bogus}"
    assert "unknown field" in signed_in.post("/api/designs", json=mine).json()["error"]


def test_downloads(signed_in):
    pdf = signed_in.post("/api/labels.pdf", json={"labels": [LABEL]})
    assert pdf.headers["content-type"] == "application/pdf" and len(pymupdf.open(stream=pdf.content, filetype="pdf")) == 2
    xl = signed_in.post("/api/labels.xlsx", json={"labels": [LABEL]})
    assert len(list(openpyxl.load_workbook(io.BytesIO(xl.content)).active.iter_rows())) == 3
    ts = signed_in.post("/api/labels.tspl", json={"labels": [LABEL]})
    assert ts.content.startswith(b"SIZE 50 mm,30 mm\r\nGAP 2 mm") and ts.content.endswith(b"PRINT 1,2\r\n")
    wide = design("mf-april")
    wide["gap_mm"] = 3
    assert b"GAP 3 mm" in signed_in.post("/api/labels.tspl", json={"labels": [LABEL], "design": wide}).content
    assert signed_in.get("/api/test.tspl").content.count(b"BITMAP") == 2
    test_pdf = signed_in.get("/api/test.pdf")
    assert len(pymupdf.open(stream=test_pdf.content, filetype="pdf")) == 2


def test_sheet_upload(signed_in):
    csv_data = b"Product Type,Artist,Title,SKU,Price,Inventory\nCD,Alex G,Headlights,ALEHEAC557,355000,3\n"
    r = signed_in.post("/api/sheet", files={"file": ("t.csv", csv_data, "text/csv")})
    assert r.json()["labels"][0]["sku"] == "ALEHEAC557" and r.json()["labels"][0]["copies"] == 3
    assert signed_in.post("/api/sheet", files={"file": ("t.csv", b"a,b\n1,2\n", "text/csv")}).status_code == 400
    assert signed_in.post("/api/sheet", data={"x": "1"}).status_code == 400


def test_limits_and_bad_input_give_clear_400s(signed_in):
    assert "No labels" in signed_in.post("/api/labels.pdf", json={"labels": []}).json()["error"]
    assert "Too many rows" in signed_in.post("/api/labels.pdf", json={"labels": [LABEL] * (MAX_ROWS + 1)}).json()["error"]
    big = dict(LABEL, copies=200)
    assert "too many" in signed_in.post("/api/labels.pdf", json={"labels": [big] * 3}).json()["error"]
    assert MAX_TOTAL == 500
    assert "no SKU" in signed_in.post("/api/labels.pdf", json={"labels": [dict(LABEL, sku="")]}).json()["error"]
    r = signed_in.post("/api/labels.tspl", json={"labels": [dict(LABEL, sku="X" * 40)]})
    assert r.status_code == 400 and "at least" in r.json()["error"]


def test_dealpos_errors_become_a_502_with_the_message():
    from dealpos_mcp.client import DealPOSError

    class Broken(FakeClient):
        async def request(self, method, path, params=None, json=None):
            raise DealPOSError("DealPOS API error (500): boom")

    c = TestClient(create_app(Catalog(Broken()), PASSWORD, b"k" * 32, DesignStore(Path("no-user-dir"))), follow_redirects=False)
    c.post("/login", data={"password": PASSWORD})
    for r in (c.get("/api/status"), c.post("/api/resolve", json={"text": "A"}), c.get("/api/search?q=abc")):
        assert r.status_code == 502 and "boom" in r.json()["error"]


# ---------------------------------------------------------------- fonts

@pytest.fixture
def font_client(tmp_path, monkeypatch):
    """Signed in, with a font registry whose system folder holds only Arial and Calibri, so Verdana is new when uploaded."""
    system = tmp_path / "system"
    system.mkdir()
    for name in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf", "calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"):
        shutil.copy(Path("C:/Windows/Fonts") / name, system / name)
    monkeypatch.setattr(fonts, "default", fonts.FontRegistry(system, tmp_path / "custom", fonts.BUNDLED_DIR))
    app = create_app(Catalog(FakeClient()), PASSWORD, b"k" * 32, DesignStore(tmp_path / "designs"))
    c = TestClient(app, follow_redirects=False)
    assert c.post("/login", data={"password": PASSWORD}).status_code == 303
    return c


VERDANA = Path("C:/Windows/Fonts/verdana.ttf")


def with_font(key):
    d = design("mf-april")
    d["elements"][0]["font"] = key
    return d


def test_fonts_api_lists_installed_and_bundled_families(font_client):
    body = font_client.get("/api/fonts").json()
    by_key = {f["key"]: f for f in body["fonts"]}
    assert set(by_key) == {"arial", "calibri", "dm-sans", "dm-sans-light", "dm-sans-medium", "dm-sans-semibold", "dm-mono", "dm-mono-medium"}
    assert by_key["dm-sans"] == {"key": "dm-sans", "name": "DM Sans", "source": "bundled", "styles": ["regular", "bold"]}
    assert by_key["arial"]["source"] == "system" and by_key["arial"]["styles"] == ["regular", "bold", "italic", "bolditalic"]


def test_upload_use_and_remove_a_font(font_client):
    if not VERDANA.exists():
        pytest.skip("needs verdana.ttf")
    r = font_client.post("/api/fonts", files={"file": ("../../My Verdana.ttf", VERDANA.read_bytes(), "font/ttf")})
    assert r.status_code == 200 and r.json()["key"] == "verdana"
    added = {f["key"]: f for f in r.json()["fonts"]}["verdana"]
    assert added["source"] == "custom" and added["name"] == "Verdana"
    assert {f["key"] for f in font_client.get("/api/fonts").json()["fonts"]} >= {"verdana", "dm-sans"}
    arial = font_client.post("/api/label.png", json={"label": LABEL, "design": with_font("arial")})
    with_verdana = font_client.post("/api/label.png", json={"label": LABEL, "design": with_font("verdana")})
    assert with_verdana.status_code == 200 and with_verdana.content != arial.content
    assert "not installed" not in with_verdana.headers["x-label-notes"]
    gone = font_client.delete("/api/fonts/verdana")
    assert gone.status_code == 200 and gone.json()["deleted"] == "verdana" and "verdana" not in {f["key"] for f in gone.json()["fonts"]}
    assert font_client.delete("/api/fonts/verdana").status_code == 404
    after = font_client.post("/api/label.png", json={"label": LABEL, "design": with_font("verdana")})
    assert after.status_code == 200 and "Font 'verdana' is not installed here, using Arial." in after.headers["x-label-notes"]


def test_a_bad_upload_is_a_400_with_the_reason(font_client):
    r = font_client.post("/api/fonts", files={"file": ("notes.ttf", b"plain text, not a font", "font/ttf")})
    assert r.status_code == 400 and r.json() == {"error": "Not a font file."}
    r = font_client.post("/api/fonts", files={"file": ("setup.exe", b"MZ" + b"\0" * 100, "application/octet-stream")})
    assert r.status_code == 400 and ".ttf" in r.json()["error"]
    assert font_client.post("/api/fonts", data={"x": "1"}).status_code == 400
    assert not (fonts.default.custom_dir.exists() and list(fonts.default.custom_dir.iterdir()))


def test_font_uploads_are_size_limited_before_parsing(font_client):
    big = font_client.post("/api/fonts", files={"file": ("big.ttf", b"\0" * (6 * 1024 * 1024), "font/ttf")})
    assert big.status_code == 413 and big.json() == {"error": "File is over 5 MB."}
    declared = font_client.post("/api/fonts", content=b"x", headers={"content-type": "multipart/form-data; boundary=b",
                                                                   "content-length": str(10 * 1024 * 1024)})
    assert declared.status_code == 413

    def chunks():
        yield b'--b\r\nContent-Disposition: form-data; name="file"; filename="a.ttf"\r\n\r\nxx\r\n--b--\r\n'
    unsized = font_client.post("/api/fonts", content=chunks(), headers={"content-type": "multipart/form-data; boundary=b"})
    assert unsized.status_code == 413


@pytest.mark.parametrize("key", ["arial", "dm-sans", "nope", "UPPER", "..%5Cx", "%2E%2E", "a%2Fb", "x" * 61, "arial.ttf", "-lead"])
def test_only_added_fonts_can_be_removed_and_odd_keys_are_404(font_client, key):
    r = font_client.delete("/api/fonts/" + key)
    assert r.status_code == 404
    assert (fonts.SYSTEM_DIR / "arial.ttf").exists() and (fonts.BUNDLED_DIR / "DMSans-Regular.ttf").exists()
    assert {f["key"] for f in font_client.get("/api/fonts").json()["fonts"]} == {"arial", "calibri", "dm-sans", "dm-sans-light", "dm-sans-medium", "dm-sans-semibold", "dm-mono", "dm-mono-medium"}
