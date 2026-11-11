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
MAX_SHEET_ROWS = 2000                 # data rows (under the header) read from an uploaded sheet
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


def _check_row_count(rows: list) -> None:
    """`rows` is the header plus at most MAX_SHEET_ROWS + 1 data rows, so one extra row means over the cap."""
    if len(rows) - 1 > MAX_SHEET_ROWS:
        raise ValueError(f"The sheet has more than {MAX_SHEET_ROWS} rows. Split it.")


def read_sheet(data: bytes, filename: str) -> tuple[list[Label], str]:
    """Templater-style xlsx or csv -> (labels, sheet name). For xlsx the first sheet whose header has SKU is used."""
    if filename.lower().endswith(".csv"):
        rows = list(itertools.islice(csv.reader(io.StringIO(data.decode("utf-8-sig"))), MAX_SHEET_ROWS + 2))
        if not rows or "sku" not in [_norm(h) for h in rows[0]]:
            raise ValueError("CSV needs a header row with a SKU column")
        _check_row_count(rows)
        return _rows_to_labels(rows[0], rows[1:]), "csv"
    _check_zip(data)
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, KeyError):
        raise ValueError("Not an Excel file.") from None
    for ws in wb.worksheets:
        rows = list(itertools.islice(ws.iter_rows(values_only=True), MAX_SHEET_ROWS + 2))  # lazy: never reads the whole sheet
        if rows and "sku" in [_norm(h) for h in rows[0]]:
            _check_row_count(rows)
            return _rows_to_labels(list(rows[0]), rows[1:]), ws.title
    raise ValueError("No sheet with a SKU column found")
