import io
from pathlib import Path

import openpyxl
import pymupdf
import pytest
from PIL import Image
from starlette.testclient import TestClient

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
    assert client.get("/").status_code == 303 and client.get("/").headers["location"] == "/login"
    for path in ("/api/status", "/api/search?q=a", "/api/test.tspl", "/api/test.pdf", "/api/designs", "/api/designs/mf-april"):
        assert client.get(path).status_code == 401
    for path in ("/api/resolve", "/api/labels.pdf", "/api/labels.xlsx", "/api/labels.tspl", "/api/label.png", "/api/sheet",
                 "/api/enrich", "/api/designs"):
        assert client.post(path, json={}).status_code == 401
    assert client.delete("/api/designs/x").status_code == 401
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
    assert "1 dot" in r.headers["x-label-notes"]
    by_slug = signed_in.post("/api/label.png", json={"label": LABEL, "design": "mf-large"}).content
    assert by_slug != r.content
    inline = design("mf-april")
    inline["elements"][0]["size_pt"] = 9
    assert signed_in.post("/api/label.png", json={"label": LABEL, "design": inline}).content != r.content
    assert signed_in.post("/api/label.png", json={"label": LABEL, "design": "nope"}).status_code == 400
    bad = design("mf-april")
    bad["elements"][0]["font"] = "comic"
    assert "font" in signed_in.post("/api/label.png", json={"label": LABEL, "design": bad}).json()["error"]


def test_designs_api_list_get_save_delete(signed_in):
    body = signed_in.get("/api/designs").json()
    assert body["default"] == "mf-april" and [d["slug"] for d in body["designs"]][:3] == ["mf-april", "mf-large", "mf-scan-safe"]
    assert "arial" in body["fonts"]
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
