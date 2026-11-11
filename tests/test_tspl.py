import zxingcpp

from labelprinter import tspl
from labelprinter.model import Label
from labelprinter.render import render
from tests.fakes import design

L = Label("AMEAMET158", "American Football", "Deluxe", "CASSETTE", "2014", "Rock", 305000, copies=3)
D = design("mf-april")
BITMAP = b"BITMAP 0,0,50,240,0,"


def test_job_has_header_from_the_design_bitmap_and_copies():
    data = tspl.job([L], D)
    head = b"SIZE 50 mm,30 mm\r\nGAP 2 mm,0 mm\r\nDIRECTION 1\r\n"
    assert data.startswith(head)
    marker = b"CLS\r\n" + BITMAP
    i = data.index(marker)
    assert i == len(head)
    assert data[i + len(marker): i + len(marker) + 12000] == render(L, D).tobytes()
    assert data.endswith(b"\r\nPRINT 1,3\r\n")
    assert len(data) == len(head) + len(marker) + 12000 + len(b"\r\nPRINT 1,3\r\n")


def test_two_rows_share_one_header():
    data = tspl.job([L, Label("ALEHEAC557", copies=1)], D)
    assert data.count(b"SIZE 50 mm") == 1 and data.count(BITMAP) == 2
    assert data.endswith(b"PRINT 1,1\r\n")


def test_invert_flips_every_bit():
    normal, inverted = tspl.job([L], D), tspl.job([L], D, invert=True)
    start = normal.index(BITMAP) + len(BITMAP)
    assert all(x ^ y == 0xFF for x, y in zip(normal[start:start + 12000], inverted[start:start + 12000]))


def test_header_follows_size_gap_and_direction_of_the_design():
    d = dict(D, width_mm=40, height_mm=25, gap_mm=2.5, direction=0)
    d["elements"] = [dict(e, w=30) for e in D["elements"] if e["id"] in ("artist", "barcode")]
    data = tspl.job([L], d)
    assert data.startswith(b"SIZE 40 mm,25 mm\r\nGAP 2.5 mm,0 mm\r\nDIRECTION 0\r\n")
    assert b"BITMAP 0,0,40,200,0," in data


def test_check_job_prints_orientation_label_then_scan_test_label():
    data = tspl.check_job()
    assert data.startswith(b"SIZE 50 mm,30 mm") and data.count(BITMAP) == 2
    start = data.index(BITMAP) + len(BITMAP)
    assert data[start + 100 * 50] == 0x00  # left 8 dots of the orientation label are black (0 = printed)


def test_scan_test_label_barcodes_decode():
    img = tspl.check_images()[1].convert("L")
    assert [r.text for r in zxingcpp.read_barcodes(img)].count("AMEAMET158") >= 2  # A (1 dot) and C (2 dots)
