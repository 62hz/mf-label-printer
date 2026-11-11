"""PDF, Excel and sheet-upload formats."""
import csv
import io
import itertools
import re
import zipfile

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

from .model import MAX_COPIES, Label, format_chip, parse_price, price_text
from . import designs
from .render import render

DPI = 203.2  # 8 dots per mm, so a 50 x 30 mm label is exactly a 50 x 30 mm PDF page
MAX_SHEET_ROWS = 2000                 # non-empty data rows (under the header) accepted from an uploaded sheet
MAX_RAW_ROWS = 20000                  # rows read from a sheet, blank or not
MAX_UNPACKED = 100 * 1024 * 1024      # bytes an uploaded xlsx may expand to
XLSX_HEADER = ["Product Type", "Artist", "Title", "Category", "Year", "SKU", "Barcode", "Price"]


def pdf_from_images(pages: list) -> bytes:
    if not pages:
        raise ValueError("No labels to export")
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", resolution=DPI, save_all=True, append_images=pages[1:])
    return buf.getvalue()


def pdf_bytes(labels: list[Label], design: dict) -> bytes:
    """One page per printed label (copies expanded): the same 1-bit image the printer gets."""
    design = designs.validate(design)
    pages = []
    for label in labels:
        pages += [render(label, design)] * label.copies
    return pdf_from_images(pages)


def xlsx_bytes(labels: list[Label]) -> bytes:
    """Rows in the Barcode Templater WEBAMI1 layout, one row per printed label (copies expanded)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Barcode Template"
    ws.append(XLSX_HEADER)
    for label in labels:
        row = [label.format, label.artist, label.title, label.genre, int(label.year) if label.year.isdigit() else label.year,
               label.sku, label.sku, price_text(label.price) if label.price else ""]
        for _ in range(label.copies):
            ws.append(row)
    for col in ("F", "G"):  # SKU / Barcode stay text
        for cell in ws[col][1:]:
            cell.number_format = "@"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _norm(h) -> str:
    return re.sub(r"[\s_]+", "", str(h or "")).lower()


def _rows_to_labels(header: list, rows) -> list[Label]:
    idx = {}
    for i, h in enumerate(header):
        n = _norm(h)
        if n.startswith("inventory"):
            n = "inventory"
        idx.setdefault(n, i)
    labels = []
    for r in rows:
        def cell(name):
            i = idx.get(name)
            return r[i] if i is not None and i < len(r) else None
        sku = str(cell("sku") or cell("barcode") or "").strip()
        if not sku:
            continue
        year = cell("year")
        year = str(int(year)) if isinstance(year, float) and year == int(year) else str(year or "").strip()
        try:
            copies = int(float(cell("inventory"))) if cell("inventory") not in (None, "") else 1
        except (TypeError, ValueError):
            copies = 1
        labels.append(Label(
            sku=sku,
            artist=str(cell("artist") or "").strip(),
            title=str(cell("title") or "").strip(),
            format=format_chip(str(cell("producttype") or "")),
            year=year,
            genre=str(cell("category") or "").strip(),
            price=parse_price(cell("price")),
            copies=max(1, min(MAX_COPIES, copies)),
        ))
    return labels


def _check_zip(data: bytes) -> None:
    """An xlsx is a zip. Refuse non-zips and zip bombs (a few KB that unpack to gigabytes) before openpyxl sees them."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            unpacked = sum(info.file_size for info in zf.infolist())
    except zipfile.BadZipFile:
        raise ValueError("Not an Excel file.") from None
    if unpacked > MAX_UNPACKED:
        raise ValueError("Excel file is too large when unpacked.")


class _TooManyRows(ValueError):
    pass


def _blank(row) -> bool:
    """A row with no cell holding anything but nothing or spaces."""
    return all(c is None or (isinstance(c, str) and not c.strip()) for c in row)


def _sheet_rows(raw):
    """(header, non-empty data rows) from a row iterator, or None when the header has no SKU column.

    Real Templater sheets carry thousands of formatted blank rows, so only non-empty rows count towards
    MAX_SHEET_ROWS. The work is still bounded: at most MAX_RAW_ROWS rows are read, blank or not, and
    reading stops as soon as the cap is passed."""
    rows = iter(raw)
    header = next(rows, None)
    if header is None or "sku" not in [_norm(h) for h in header]:
        return None
    data = []
    for row in itertools.islice(rows, MAX_RAW_ROWS - 1):
        if not _blank(row):
            data.append(row)
            if len(data) > MAX_SHEET_ROWS:
                raise _TooManyRows(f"The sheet has more than {MAX_SHEET_ROWS} rows. Split it.")
    return list(header), data


def read_sheet(data: bytes, filename: str) -> tuple[list[Label], str]:
    """Templater-style xlsx or csv -> (labels, sheet name). For xlsx the first sheet whose header has SKU is used."""
    if filename.lower().endswith(".csv"):
        try:
            found = _sheet_rows(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
        except csv.Error:
            raise ValueError("Could not read the CSV file.") from None
        if found is None:
            raise ValueError("CSV needs a header row with a SKU column")
        return _rows_to_labels(*found), "csv"
    _check_zip(data)
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, KeyError):
        raise ValueError("Not an Excel file.") from None
    except Exception:
        raise ValueError("Could not read the Excel file.") from None
    try:
        for ws in wb.worksheets:
            found = _sheet_rows(ws.iter_rows(values_only=True))  # lazy: never reads the whole sheet
            if found is not None:
                return _rows_to_labels(*found), ws.title
    except _TooManyRows:
        raise
    except Exception:  # a damaged part inside an otherwise valid zip
        raise ValueError("Could not read the Excel file.") from None
    raise ValueError("No sheet with a SKU column found")
