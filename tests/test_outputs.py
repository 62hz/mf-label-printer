import io

import openpyxl
import pymupdf
import pytest

from labelprinter.model import Label
from labelprinter.outputs import XLSX_HEADER, pdf_bytes, pdf_from_images, read_sheet, xlsx_bytes
from tests.fakes import design

A = Label("AMEAMET158", "American Football", "American Football (Deluxe Edition)", "CASSETTE", "2014",
          "Rock / Punk / New Wave", 305000, copies=2)
B = Label("ALEHEAC557", "Alex G", "Headlights", "CD", "2025", "Alternative / Indie", 355000, copies=1)


def test_pdf_pages_are_50_by_30_mm_and_copies_expand():
    doc = pymupdf.open(stream=pdf_bytes([A, B], design()), filetype="pdf")
    assert len(doc) == 3
    r = doc[0].rect
    assert round(r.width / 72 * 25.4, 1) == 50.0 and round(r.height / 72 * 25.4, 1) == 30.0


def test_pdf_with_nothing_raises():
    with pytest.raises(ValueError):
        pdf_bytes([], design())


def test_pdf_from_images_is_50_by_30_for_the_test_labels():
    from labelprinter.tspl import check_images
    doc = pymupdf.open(stream=pdf_from_images(check_images()), filetype="pdf")
    assert len(doc) == 2 and round(doc[1].rect.width / 72 * 25.4, 1) == 50.0


def test_xlsx_has_templater_header_and_one_row_per_copy():
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes([A, B])))
    rows = list(wb.active.iter_rows(values_only=True))
    assert list(rows[0]) == XLSX_HEADER
    assert len(rows) == 1 + 3
    assert rows[1] == ("CASSETTE", "American Football", "American Football (Deluxe Edition)", "Rock / Punk / New Wave",
                       2014, "AMEAMET158", "AMEAMET158", "Rp305.000")


def test_xlsx_roundtrip_through_read_sheet():
    labels, sheet = read_sheet(xlsx_bytes([B]), "x.xlsx")
    assert sheet == "Barcode Template"
    assert labels == [Label("ALEHEAC557", "Alex G", "Headlights", "CD", "2025", "Alternative / Indie", 355000, 1)]


def _templater_xlsx():
    wb = openpyxl.Workbook()
    wb.active.title = "Notes"
    wb.active.append(["nothing here"])
    ws = wb.create_sheet("Edit Barcode Template JUNO1")
    ws.append(["Product Type", "Inventory", "Artist", "Title", "Category", "Year", "Price", "SKU", "Barcode"])
    ws.append(["CD", 2.0, "Alex G ", "Headlights", "Alternative / Indie", 2025.0, 355000.0, "ALEHEAC557", "ALEHEAC557"])
    ws.append(["VINYL", None, "Bar Italia", "Some Like It Hot", "Rock", 2025.0, "Rp300.000", None, "BARSOMV193"])
    ws.append(["CD", 1.0, "No Sku", "x", "y", 2020.0, 1000.0, None, None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_read_sheet_picks_sheet_with_sku_and_maps_columns():
    labels, sheet = read_sheet(_templater_xlsx(), "Barcode Templater April.xlsx")
    assert sheet == "Edit Barcode Template JUNO1"
    assert labels[0] == Label("ALEHEAC557", "Alex G", "Headlights", "CD", "2025", "Alternative / Indie", 355000, 2)
    assert labels[1].sku == "BARSOMV193" and labels[1].format == "VINYL" and labels[1].price == 300000 and labels[1].copies == 1
    assert len(labels) == 2  # the row without a SKU is skipped


def test_read_sheet_inventory_column_can_have_a_suffix():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Product Type", "Artist", "Inventory_MF Store", "Title", "SKU"])
    ws.append(["CASSETTE", "American Football", 4.0, "Deluxe", "AMEAMET158"])
    buf = io.BytesIO()
    wb.save(buf)
    labels, _ = read_sheet(buf.getvalue(), "w.xlsx")
    assert labels[0].copies == 4 and labels[0].format == "CASSETTE"


def test_read_sheet_csv_and_errors():
    csv_data = "Product Type,Artist,Title,SKU,Price\nCD,Alex G,Headlights,ALEHEAC557,355000\n".encode()
    labels, sheet = read_sheet(csv_data, "x.csv")
    assert sheet == "csv" and labels[0].sku == "ALEHEAC557" and labels[0].price == 355000
    with pytest.raises(ValueError, match="SKU"):
        read_sheet(b"a,b\n1,2\n", "x.csv")
    wb = openpyxl.Workbook()
    wb.active.append(["a", "b"])
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(ValueError, match="SKU"):
        read_sheet(buf.getvalue(), "x.xlsx")
