"""Regression tests for the security and robustness fixes from the final review (F1 to F10)."""
import asyncio
import copy
import io
import sys
import threading
import time
import zipfile

import openpyxl
import pytest
from PIL import Image, ImageDraw
from starlette.testclient import TestClient

from labelprinter import auth, fonts, outputs, render, server, tspl
from labelprinter.catalog import Catalog
from labelprinter.designs import DesignStore
from labelprinter.model import Label
from labelprinter.server import create_app
from tests.fakes import FakeClient, design

PASSWORD = "correct-horse"
ARIAL = fonts.resolve("arial")  # the font file the fit tests measure with


def make_client(tmp_path, fake=None, **kwargs):
    app = create_app(Catalog(fake or FakeClient()), PASSWORD, b"k" * 32, DesignStore(tmp_path / "designs"))
    return TestClient(app, follow_redirects=False, **kwargs)


def signed_in(tmp_path, fake=None, **kwargs):
    c = make_client(tmp_path, fake, **kwargs)
    r = c.post("/login", data={"password": PASSWORD})
    assert r.status_code == 303 and r.headers["location"] == "/"
    return c


# ---------------------------------------------------------------- F1 path traversal in design get/delete

@pytest.mark.parametrize("slug", ["..\\victim", "../victim", "C:\\x", "", "a/b", "UPPER", "-lead", "x" * 61, "a.b"])
def test_f1_delete_rejects_slugs_that_are_not_slugs(tmp_path, slug):
    user = tmp_path / "designs"
    user.mkdir()
    victim = tmp_path / "victim.json"
    victim.write_text("{}", encoding="utf-8")
    inside = user / "victim.json"
    inside.write_text("{}", encoding="utf-8")
    with pytest.raises(KeyError):
        DesignStore(user).delete(slug)
    assert victim.exists() and inside.exists()


def test_f1_get_rejects_slugs_that_are_not_slugs(tmp_path):
    store = DesignStore(tmp_path / "designs")
    for slug in ("..\\x", "../x", "C:\\x", None, 5):
        with pytest.raises(KeyError):
            store.get(slug)


def test_f1_every_slugified_name_is_a_valid_slug(tmp_path):
    store = DesignStore(tmp_path / "designs")
    mine = design("mf-april")
    for name in ("CD shelf", "???", "  --a--  ", "x" * 60, "Ünï côdé 9"):
        mine["name"] = name
        slug = store.save(mine)
        assert store.get(slug)["name"] == name.strip()
        store.delete(slug)


def test_f1_delete_route_cannot_climb_out_of_the_designs_folder(tmp_path):
    c = signed_in(tmp_path)
    (tmp_path / "designs").mkdir(exist_ok=True)
    victim = tmp_path / "victim.json"
    victim.write_text("{}", encoding="utf-8")
    assert c.delete("/api/designs/..%5Cvictim").status_code == 404
    assert c.delete("/api/designs/..%2Fvictim").status_code == 404
    assert victim.exists()


# ---------------------------------------------------------------- F2 login throttle bypass

def test_f2_a_spoofed_forwarded_for_header_does_not_dodge_the_throttle(tmp_path):
    c = make_client(tmp_path)
    codes = [c.post("/login", data={"password": "nope"}, headers={"X-Forwarded-For": f"10.0.0.{n}"}).status_code
             for n in range(12)]
    assert codes[:auth.MAX_FAILURES] == [303] * auth.MAX_FAILURES
    assert codes[auth.MAX_FAILURES] == 429  # the 11th attempt
    assert c.post("/login", data={"password": PASSWORD}, headers={"X-Forwarded-For": "9.9.9.9"}).status_code == 429


def test_f2_global_cap_blocks_a_fresh_client_then_frees_after_the_window():
    now = [0.0]
    t = auth.Throttle(clock=lambda: now[0])
    assert auth.MAX_GLOBAL_FAILURES == 40
    for n in range(auth.MAX_GLOBAL_FAILURES):
        assert not t.blocked("fresh")
        t.record_failure(f"client-{n}")
    assert t.blocked("fresh")
    now[0] = auth.FAILURE_WINDOW + 1
    assert not t.blocked("fresh")


def test_f2_global_cap_is_not_reached_one_failure_early():
    t = auth.Throttle(clock=lambda: 0.0)
    for n in range(auth.MAX_GLOBAL_FAILURES - 1):
        t.record_failure(f"client-{n}")
    assert not t.blocked("fresh")


def test_f2_throttle_forgets_clients_whose_failures_have_all_expired():
    now = [0.0]
    t = auth.Throttle(clock=lambda: now[0])
    for n in range(30):
        t.record_failure(f"client-{n}")
    now[0] = auth.FAILURE_WINDOW + 1
    for n in range(30):
        assert not t.blocked(f"client-{n}")
    assert t._failures == {}


# ---------------------------------------------------------------- F3 unbounded text and slow rendering

def run_within(seconds, fn, *args):
    """Run fn in a daemon thread; fail (instead of hanging the suite) if it takes longer than `seconds`."""
    out = {}
    worker = threading.Thread(target=lambda: out.update(result=fn(*args)), daemon=True)
    start = time.perf_counter()
    worker.start()
    worker.join(seconds)
    elapsed = time.perf_counter() - start
    assert not worker.is_alive(), f"still running after {elapsed:.1f} s (limit {seconds} s)"
    assert elapsed < seconds, f"took {elapsed:.1f} s (limit {seconds} s)"
    return out["result"]


def test_f3_label_from_dict_caps_field_lengths():
    long = "A" * 20000
    label = Label.from_dict({"sku": long, "artist": long, "title": long, "genre": long, "format": long, "year": long})
    assert (len(label.sku), len(label.artist), len(label.title), len(label.genre), len(label.format), len(label.year)) == (
        64, 200, 200, 200, 20, 10)
    padded = Label.from_dict({"artist": "   " + "B" * 300})  # strip first, then cap
    assert padded.artist == "B" * 200


def test_f3_a_20000_character_artist_renders_fast():
    label = Label("ABC123", artist="A" * 20000, title="Title", format="CD", year="2025", genre="G" * 20000)
    img = run_within(3, render.render, label, design("mf-april"))
    assert img.size == (400, 240)


def test_f3_forty_big_text_elements_with_a_long_title_render_fast():
    d = copy.deepcopy(design("mf-april"))
    d["elements"] = [{"id": f"t{n}", "type": "text", "x": 0, "y": 0, "w": 50, "h": 30, "content": "{title}",
                      "size_pt": 60, "min_size_pt": 4} for n in range(40)]
    img = run_within(5, render.render, Label("ABC123", title="B" * 20000), d)
    assert img.size == (400, 240)


def _draw():
    return ImageDraw.Draw(Image.new("L", (10, 10), 255))


def _reference_fit(draw, text, name, max_px, avail, min_px):
    """The slow, obviously right version: try every candidate size from the top, then every prefix from the longest."""
    sizes, i = [], 0
    while True:
        px = max(min_px, max_px - i * 0.5)
        sizes.append(px)
        if px <= min_px:
            break
        i += 1
    for px in sizes:
        if draw.textlength(text, font=render.font(name, px)) <= avail:
            return text, px
    f = render.font(name, min_px)
    for p in range(len(text), -1, -1):
        if draw.textlength(text[:p] + "...", font=f) <= avail:
            return text[:p].rstrip() + "...", min_px
    return "...", min_px  # not even the dots fit


@pytest.mark.parametrize("text", ["Hi", "American Football", "A Very Long Album Title (Deluxe Edition) [Remastered]", "W" * 60, "i" * 300,
                                  "Ünï côdé Ångström", "tight    spaces   here    "])
@pytest.mark.parametrize("avail", [1, 20, 80, 160, 400])
@pytest.mark.parametrize("max_px,min_px", [(16.93, 11.29), (28.2, 5.6), (11.29, 11.29), (40.0, 5.64)])
def test_f3_fit_matches_the_slow_reference(text, avail, max_px, min_px):
    draw = _draw()
    got_text, got_font = render.fit(draw, text, ARIAL, max_px, avail, min_px)
    want_text, want_px = _reference_fit(draw, text, ARIAL, max_px, avail, min_px)
    assert (got_text, got_font.size) == (want_text, want_px)


def test_f3_fit_leaves_text_that_already_fits_alone_and_cuts_with_dots_at_the_minimum_size():
    draw = _draw()
    text, f = render.fit(draw, "Hi", ARIAL, 20, 400, 8)
    assert text == "Hi" and f.size == 20
    cut, f = render.fit(draw, "A" * 5000, ARIAL, 20, 100, 8)
    assert cut.endswith("...") and f.size == 8 and draw.textlength(cut, font=f) <= 100 and len(cut) > 3
    assert render.fit(draw, "A" * 50, ARIAL, 20, 1, 8)[0] == "..."  # not even the dots fit


def test_f3_every_render_runs_in_a_worker_thread_not_on_the_event_loop(tmp_path, monkeypatch):
    on_worker = {}

    def spy(name, result):
        def fake(*args, **kwargs):
            try:
                asyncio.get_running_loop()
                on_worker[name] = False  # a running loop here means we are on the event loop thread
            except RuntimeError:
                on_worker[name] = True
            return result
        return fake

    monkeypatch.setattr(server, "png_bytes", spy("png_bytes", b"png"))
    monkeypatch.setattr(server, "notes", spy("notes", []))
    monkeypatch.setattr(outputs, "pdf_bytes", spy("pdf_bytes", b"pdf"))
    monkeypatch.setattr(tspl, "job", spy("job", b"tspl"))
    monkeypatch.setattr(tspl, "check_job", spy("check_job", b"tspl"))
    monkeypatch.setattr(tspl, "check_images", spy("check_images", []))
    monkeypatch.setattr(outputs, "pdf_from_images", spy("pdf_from_images", b"pdf"))
    c = signed_in(tmp_path)
    label = {"sku": "ABC123"}
    assert c.post("/api/label.png", json={"label": label}).status_code == 200
    assert c.post("/api/labels.pdf", json={"labels": [label]}).status_code == 200
    assert c.post("/api/labels.tspl", json={"labels": [label]}).status_code == 200
    assert c.get("/api/test.tspl").status_code == 200
    assert c.get("/api/test.pdf").status_code == 200
    assert on_worker == {name: True for name in ("png_bytes", "notes", "pdf_bytes", "job", "check_job", "check_images", "pdf_from_images")}


# ---------------------------------------------------------------- F4 upload and JSON limits, zip bombs

MB = 1024 * 1024
JSON_POST_ROUTES = ["/api/resolve", "/api/enrich", "/api/label.png", "/api/labels.pdf", "/api/labels.xlsx", "/api/labels.tspl",
                    "/api/designs"]


def sheet_xlsx(data_rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["SKU", "Artist", "Title"])
    for n in range(data_rows):
        ws.append([f"SKU{n:05d}", "Artist", "Title"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def post_file(c, name, data):
    return c.post("/api/sheet", files={"file": (name, data, "application/octet-stream")})


def test_f4_a_6mb_upload_is_refused_before_it_is_parsed(tmp_path):
    r = post_file(signed_in(tmp_path), "x.xlsx", b"\0" * (6 * MB))
    assert r.status_code == 413 and r.json() == {"error": "File is over 5 MB."}


def test_f4_a_declared_10mb_body_is_refused_even_if_the_body_is_small(tmp_path):
    r = signed_in(tmp_path).post("/api/sheet", content=b"x", headers={"content-type": "multipart/form-data; boundary=b",
                                                                      "content-length": str(10 * MB)})
    assert r.status_code == 413 and r.json() == {"error": "File is over 5 MB."}


def test_f4_a_sheet_upload_without_content_length_is_refused(tmp_path):
    def chunks():
        yield b"--b\r\nContent-Disposition: form-data; name=\"file\"; filename=\"t.csv\"\r\n\r\nSKU\r\nA\r\n--b--\r\n"
    r = signed_in(tmp_path).post("/api/sheet", content=chunks(), headers={"content-type": "multipart/form-data; boundary=b"})
    assert r.status_code == 413 and r.json() == {"error": "File is over 5 MB."}


def test_f4_the_size_check_does_not_hide_the_sign_in_check(tmp_path):
    r = make_client(tmp_path).post("/api/sheet", content=b"x", headers={"content-length": str(10 * MB)})
    assert r.status_code == 401


def test_f4_a_normal_upload_still_works(tmp_path):
    r = post_file(signed_in(tmp_path), "s.xlsx", sheet_xlsx(3))
    assert r.status_code == 200 and len(r.json()["labels"]) == 3


def test_f4_a_file_that_is_not_an_excel_file_is_a_400_not_a_500(tmp_path):
    c = signed_in(tmp_path)
    for data in (b"hello, this is text", b"", b"PK\x03\x04 broken zip"):
        r = post_file(c, "x.xlsx", data)
        assert r.status_code == 400 and r.json() == {"error": "Not an Excel file."}, data
    plain_zip = io.BytesIO()
    with zipfile.ZipFile(plain_zip, "w") as zf:
        zf.writestr("hello.txt", "hi")  # a real zip, but not a workbook
    r = post_file(c, "x.xlsx", plain_zip.getvalue())
    assert r.status_code == 400 and r.json() == {"error": "Not an Excel file."}


def zip_bomb(megabytes):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        with zf.open("xl/big.bin", "w", force_zip64=True) as f:
            chunk = b"\0" * MB
            for _ in range(megabytes):
                f.write(chunk)
    return buf.getvalue()


def test_f4_a_zip_bomb_is_refused_without_unpacking_it(tmp_path):
    bomb = zip_bomb(150)
    assert len(bomb) < MB  # small on the wire, 150 MB when unpacked
    r = post_file(signed_in(tmp_path), "x.xlsx", bomb)
    assert r.status_code == 400 and "too large when unpacked" in r.json()["error"]


def test_f4_a_workbook_just_under_the_unpacked_limit_is_not_called_too_large():
    with pytest.raises(ValueError, match="Not an Excel file"):  # 99 MB unpacked passes the size check, then fails as not a workbook
        outputs.read_sheet(zip_bomb(99), "x.xlsx")


def test_f4_sheets_over_2000_rows_are_refused_but_2000_is_fine(tmp_path):
    c = signed_in(tmp_path)
    assert outputs.MAX_SHEET_ROWS == 2000
    r = post_file(c, "big.xlsx", sheet_xlsx(2500))
    assert r.status_code == 400 and r.json() == {"error": "The sheet has more than 2000 rows. Split it."}
    assert len(post_file(c, "ok.xlsx", sheet_xlsx(2000)).json()["labels"]) == 2000
    assert post_file(c, "over.xlsx", sheet_xlsx(2001)).status_code == 400


def test_f4_csv_has_the_same_row_cap(tmp_path):
    c = signed_in(tmp_path)

    def csv_rows(n):
        return ("SKU,Artist\n" + "".join(f"S{k},A\n" for k in range(n))).encode()

    r = post_file(c, "big.csv", csv_rows(2500))
    assert r.status_code == 400 and "more than 2000 rows" in r.json()["error"]
    assert len(post_file(c, "ok.csv", csv_rows(2000)).json()["labels"]) == 2000


@pytest.mark.parametrize("route", JSON_POST_ROUTES)
def test_f4_a_json_list_body_is_a_400_not_a_500(tmp_path, route):
    r = signed_in(tmp_path).post(route, json=[1, 2, 3])
    assert r.status_code == 400 and r.json() == {"error": "Expected a JSON object."}


@pytest.mark.parametrize("route", JSON_POST_ROUTES)
def test_f4_a_3mb_json_body_is_refused(tmp_path, route):
    r = signed_in(tmp_path).post(route, json={"text": "A" * (3 * MB)})
    assert r.status_code == 400 and "too large" in r.json()["error"]


def test_f4_json_just_under_the_limit_is_still_read(tmp_path):
    r = signed_in(tmp_path).post("/api/resolve", json={"text": "A" * (MB + MB // 2)})
    assert r.status_code == 200 and r.json()["missing"] == ["A" * (MB + MB // 2)]


def test_f4_json_with_absurd_nesting_is_a_400_not_a_500(tmp_path):
    r = signed_in(tmp_path).post("/api/resolve", content=b"[" * 200000, headers={"content-type": "application/json"})
    assert r.status_code == 400


# ---------------------------------------------------------------- F5 multipart on the login page

def test_f5_a_multipart_login_post_is_refused_without_being_parsed(tmp_path):
    c = make_client(tmp_path)
    r = c.post("/login", files={"password": ("p", b"x")})
    assert r.status_code == 415 and "error" in r.json()
    r = c.post("/login", content=b'{"password": "x"}', headers={"content-type": "application/json"})
    assert r.status_code == 415
    assert c.post("/login", content=b"password=x").status_code == 415  # no Content-Type at all


def test_f5_a_normal_urlencoded_login_still_works_with_or_without_parameters(tmp_path):
    c = make_client(tmp_path)
    assert c.post("/login", data={"password": "nope"}).headers["location"] == "/login?bad=1"
    r = c.post("/login", content=f"password={PASSWORD}".encode(),
               headers={"content-type": "application/x-www-form-urlencoded; charset=UTF-8"})
    assert r.status_code == 303 and r.headers["location"] == "/" and auth.COOKIE in r.headers["set-cookie"]


def test_f5_a_long_login_body_is_refused_with_413(tmp_path):
    c = make_client(tmp_path)
    r = c.post("/login", data={"password": "x" * 5000})
    assert r.status_code == 413 and "error" in r.json()
    assert c.post("/login", data={"password": "x" * 3000}).status_code == 303  # under 4096: a normal wrong password


def test_f5_a_login_post_without_content_length_is_refused(tmp_path):
    def chunks():
        yield b"password=x"
    r = make_client(tmp_path).post("/login", content=chunks(), headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 413


def test_f5_refused_login_posts_do_not_count_as_wrong_passwords(tmp_path):
    c = make_client(tmp_path)
    for _ in range(auth.MAX_FAILURES + 2):
        assert c.post("/login", files={"password": ("p", b"x")}).status_code == 415
    assert c.post("/login", data={"password": PASSWORD}).status_code == 303


# ---------------------------------------------------------------- F8 refresh hammering

def product_calls(fake):
    return sum(1 for call in fake.calls if call[1] == "/api/v3/Product")


async def test_f8_refresh_if_stale_calls_dealpos_once_per_minute():
    now = [0.0]
    fake = FakeClient()
    cat = Catalog(fake, clock=lambda: now[0])
    assert await cat.refresh_if_stale() == (3, True) and product_calls(fake) == 1
    now[0] = 10
    assert await cat.refresh_if_stale() == (3, False) and product_calls(fake) == 1  # served from memory
    now[0] = 61
    assert await cat.refresh_if_stale() == (3, True) and product_calls(fake) == 2
    now[0] = 62
    assert await cat.refresh_if_stale(min_age=0) == (3, True) and product_calls(fake) == 3  # min_age is a parameter


def test_f8_the_refresh_route_does_not_hammer_dealpos_and_says_whether_it_read(tmp_path):
    fake = FakeClient()
    c = signed_in(tmp_path, fake)
    assert c.post("/api/refresh").json() == {"products": 3, "refreshed": True}
    for _ in range(2):
        assert c.post("/api/refresh").json() == {"products": 3, "refreshed": False}
    assert product_calls(fake) == 1


# ---------------------------------------------------------------- F10 secure cookie

def test_f10_login_cookie_is_secure_on_a_public_host_and_not_on_a_local_one(tmp_path):
    c = make_client(tmp_path)
    public = c.post("/login", data={"password": PASSWORD}, headers={"Host": "labels.example.ts.net"})
    assert public.status_code == 303 and "secure" in public.headers["set-cookie"].lower()
    with_port = c.post("/login", data={"password": PASSWORD}, headers={"Host": "labels.example.ts.net:10000"})
    assert "secure" in with_port.headers["set-cookie"].lower()
    assert "secure" not in c.post("/login", data={"password": PASSWORD}).headers["set-cookie"].lower()  # TestClient host: testserver
    for host in ("127.0.0.1:8797", "localhost:8797", "[::1]:8797"):
        r = c.post("/login", data={"password": PASSWORD}, headers={"Host": host})
        assert r.status_code == 303 and "secure" not in r.headers["set-cookie"].lower(), host


# ================================================================ Round two

# ---------------------------------------------------------------- R1 the label must be an object

@pytest.mark.parametrize("label", ["x", [1, 2], 5, None, True])
def test_r1_a_label_that_is_not_an_object_is_a_400_not_a_500(tmp_path, label):
    r = signed_in(tmp_path).post("/api/label.png", json={"label": label})
    assert r.status_code == 400 and r.json() == {"error": "Expected a label object."}


def test_r1_a_missing_label_still_gives_the_empty_sku_error(tmp_path):
    r = signed_in(tmp_path).post("/api/label.png", json={})
    assert r.status_code == 400 and "empty" in r.json()["error"]


# ---------------------------------------------------------------- R2 unreadable sheets are a 400, never a 500

def rewritten_xlsx(replace_name, new_body):
    """A real workbook with one part replaced."""
    src = zipfile.ZipFile(io.BytesIO(sheet_xlsx(3)))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for info in src.infolist():
            zf.writestr(info.filename, new_body if info.filename == replace_name else src.read(info.filename))
    return out.getvalue()


def test_r2_a_csv_that_the_csv_reader_rejects_is_a_value_error():
    huge_field = b"SKU,Artist\nS1," + b"x" * 200000 + b"\n"  # over the csv module's 131072-character field limit
    with pytest.raises(ValueError, match="Could not read the CSV file.") as exc:
        outputs.read_sheet(huge_field, "x.csv")
    assert type(exc.value) is ValueError


def test_r2_a_workbook_with_a_broken_sheet_is_a_value_error():
    broken = rewritten_xlsx("xl/worksheets/sheet1.xml", b'<worksheet><sheetData><row r="1"><c r="A1" t="inlineStr"')
    with pytest.raises(ValueError, match="Could not read the Excel file."):
        outputs.read_sheet(broken, "x.xlsx")


def test_r2_a_workbook_with_a_broken_workbook_part_is_a_value_error():
    broken = rewritten_xlsx("xl/workbook.xml", b"<workbook><sheets>")
    with pytest.raises(ValueError, match="Could not read the Excel file."):
        outputs.read_sheet(broken, "x.xlsx")


def test_r2_the_specific_messages_are_kept():
    with pytest.raises(ValueError, match="Not an Excel file."):
        outputs.read_sheet(b"plain text", "x.xlsx")
    with pytest.raises(ValueError, match="CSV needs a header row"):
        outputs.read_sheet(b"a,b\n1,2\n", "x.csv")
    with pytest.raises(ValueError, match="No sheet with a SKU column found"):
        wb = openpyxl.Workbook()
        wb.active.append(["a", "b"])
        buf = io.BytesIO()
        wb.save(buf)
        outputs.read_sheet(buf.getvalue(), "x.xlsx")


def test_r2_the_upload_route_gives_400_with_the_message(tmp_path):
    c = signed_in(tmp_path)
    r = post_file(c, "x.csv", b"SKU,Artist\nS1," + b"x" * 200000 + b"\n")
    assert r.status_code == 400 and r.json() == {"error": "Could not read the CSV file."}
    r = post_file(c, "x.xlsx", rewritten_xlsx("xl/worksheets/sheet1.xml", b"<worksheet><sheetData><row"))
    assert r.status_code == 400 and r.json() == {"error": "Could not read the Excel file."}


# ---------------------------------------------------------------- R3 at most 500 distinct codes per resolve

def codes(n):
    return " ".join(f"CODE{k:04d}" for k in range(n))


def test_r3_resolve_refuses_501_distinct_codes_before_calling_dealpos(tmp_path):
    fake = FakeClient()
    c = signed_in(tmp_path, fake)
    r = c.post("/api/resolve", json={"text": codes(501)})
    assert r.status_code == 400 and r.json() == {"error": "Too many codes (limit 500)."}
    assert fake.calls == []
    assert c.post("/api/resolve", json={"text": codes(500)}).status_code == 200


def test_r3_repeats_in_any_case_and_any_separator_count_once(tmp_path):
    c = signed_in(tmp_path)
    repeats = "A1 a1,A1;a1\n" * 300
    assert c.post("/api/resolve", json={"text": repeats + codes(498)}).status_code == 200  # 499 distinct
    assert c.post("/api/resolve", json={"text": repeats + codes(500)}).status_code == 400  # 501 distinct
    assert c.post("/api/resolve", json={"text": ",".join(f"c{k}" for k in range(501))}).status_code == 400


# ---------------------------------------------------------------- R4 the row cap counts non-empty rows only

def sheet_with_blank_rows(filled, blank):
    """Header, `filled` rows with data, then `blank` rows that are formatted but empty (as in real Templater sheets)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["SKU", "Artist", "Title"])
    for n in range(filled):
        ws.append([f"SKU{n:05d}", "Artist", "Title"])
    for n in range(blank):
        for col in (1, 2, 3):
            ws.cell(row=filled + 2 + n, column=col).number_format = "@"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_r4_1500_filled_rows_then_5000_formatted_blank_rows_import_fine(tmp_path):
    r = post_file(signed_in(tmp_path), "t.xlsx", sheet_with_blank_rows(1500, 5000))
    assert r.status_code == 200 and len(r.json()["labels"]) == 1500


def test_r4_blank_rows_do_not_count_but_2001_filled_rows_still_fail():
    assert len(outputs.read_sheet(sheet_with_blank_rows(2000, 3000), "t.xlsx")[0]) == 2000
    with pytest.raises(ValueError, match="more than 2000 rows"):
        outputs.read_sheet(sheet_with_blank_rows(2001, 3000), "t.xlsx")


def test_r4_csv_blank_and_whitespace_only_rows_do_not_count():
    data = ("SKU,Artist\nS1,A\n" + "\n" * 3000 + " , \n" * 3000 + "S2,B\n").encode()
    labels, _ = outputs.read_sheet(data, "t.csv")
    assert [l.sku for l in labels] == ["S1", "S2"]
    filled = ("SKU,Artist\n" + "".join(f"S{k},A\n\n" for k in range(2001))).encode()  # a blank line after every row
    with pytest.raises(ValueError, match="more than 2000 rows"):
        outputs.read_sheet(filled, "t.csv")


def test_r4_reading_stops_after_20000_raw_rows(monkeypatch):
    consumed = [0]

    def endless_blank_rows(_file):
        yield ["SKU"]
        while True:
            consumed[0] += 1
            yield [""]

    monkeypatch.setattr(outputs.csv, "reader", endless_blank_rows)
    labels, name = outputs.read_sheet(b"x", "x.csv")
    assert labels == [] and name == "csv"
    assert outputs.MAX_RAW_ROWS == 20000 and consumed[0] <= outputs.MAX_RAW_ROWS


# ---------------------------------------------------------------- R5 main(): no proxy headers, 12-character password

def run_main(monkeypatch, tmp_path, password, seen):
    monkeypatch.setattr(server, "read_only_client", lambda: FakeClient())
    monkeypatch.setattr(server, "ROOT", tmp_path)  # the session key goes to a temp folder, not data/
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: seen.update(app=app, **kwargs))
    monkeypatch.setattr(sys, "argv", ["labelprinter.server", "--port", "8797"])
    if password is None:
        monkeypatch.delenv("LABELPRINTER_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("LABELPRINTER_PASSWORD", password)
    server.main()


def test_r5_main_starts_with_a_12_character_password_and_trusts_no_forwarded_header(monkeypatch, tmp_path):
    seen = {}
    run_main(monkeypatch, tmp_path, "x" * 12, seen)
    assert seen["proxy_headers"] is False and seen["host"] == "127.0.0.1" and seen["port"] == 8797
    assert callable(seen["app"])


@pytest.mark.parametrize("password", ["x" * 11, "short", "", None])
def test_r5_main_exits_without_starting_when_the_password_is_under_12_characters(monkeypatch, tmp_path, password):
    seen = {}
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, tmp_path, password, seen)
    assert "12" in str(exc.value) and seen == {}


# ---------------------------------------------------------------- R6 the refresh button says what happened

def test_r6_the_refresh_button_tells_the_two_cases_apart():
    js = (server.STATIC / "app.js").read_text(encoding="utf-8")
    assert "Catalog refreshed." in js and "Catalog was read less than a minute ago." in js and ".refreshed" in js
