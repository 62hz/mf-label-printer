"""PDF, Excel and sheet-upload formats."""
import csv
import io
import re

import openpyxl

from .model import MAX_COPIES, Label, format_chip, parse_price, price_text
from . import designs
from .render import render

DPI = 203.2  # 8 dots per mm, so a 50 x 30 mm label is exactly a 50 x 30 mm PDF page
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


def read_sheet(data: bytes, filename: str) -> tuple[list[Label], str]:
    """Templater-style xlsx or csv -> (labels, sheet name). For xlsx the first sheet whose header has SKU is used."""
    if filename.lower().endswith(".csv"):
        rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
        if not rows or "sku" not in [_norm(h) for h in rows[0]]:
            raise ValueError("CSV needs a header row with a SKU column")
        return _rows_to_labels(rows[0], rows[1:]), "csv"
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if rows and "sku" in [_norm(h) for h in rows[0]]:
            return _rows_to_labels(list(rows[0]), rows[1:]), ws.title
    raise ValueError("No sheet with a SKU column found")
