"""SKUs or barcodes -> labels PDF + Excel. Reads DealPOS (read-only); never writes to it.

  vault run dealpos -- uv run python scripts/labels_cli.py AMEAMET158 ALEHEAC557 --copies 2 --out outputs
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from labelprinter import outputs  # noqa: E402
from labelprinter.catalog import Catalog, read_only_client  # noqa: E402
from labelprinter.designs import DEFAULT_SLUG, DesignStore  # noqa: E402


async def build(codes: list[str], catalog: Catalog, out_dir: Path, copies: int = 1, stem: str | None = None,
                design: dict | None = None) -> dict:
    labels, missing = await catalog.resolve(" ".join(codes))
    if not labels:
        raise SystemExit("No label found for: " + ", ".join(missing or ["(no codes given)"]))
    for label in labels:
        info = await catalog.enrich(label.sku)
        label.year = label.year or info["year"]
        label.genre = label.genre or info["genre"]
        label.copies = max(1, min(200, copies))
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = stem or time.strftime("mf-labels-%Y-%m-%d-%H%M")
    pdf, xlsx = out_dir / f"{stem}.pdf", out_dir / f"{stem}.xlsx"
    pdf.write_bytes(outputs.pdf_bytes(labels, design or DesignStore(ROOT / "data" / "designs").get(DEFAULT_SLUG)))
    xlsx.write_bytes(outputs.xlsx_bytes(labels))
    return {"pdf": pdf, "xlsx": xlsx, "labels": len(labels), "missing": missing,
            "flagged": [l.sku for l in labels if not l.year or not l.genre]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("codes", nargs="+", help="SKUs (variant codes) or product barcodes")
    ap.add_argument("--copies", type=int, default=1, help="copies of each label (default 1)")
    ap.add_argument("--out", type=Path, default=ROOT / "outputs", help="output folder")
    ap.add_argument("--design", default=DEFAULT_SLUG, help="design slug (see the Design menu in the app), default mf-concept-price-card (MF Price card)")
    args = ap.parse_args()
    design = DesignStore(ROOT / "data" / "designs").get(args.design)
    result = asyncio.run(build(args.codes, Catalog(read_only_client()), args.out, args.copies, design=design))
    print(f"{result['labels']} label rows, {args.copies} copies each")
    print("PDF  ", result["pdf"])
    print("Excel", result["xlsx"])
    if result["missing"]:
        print("Not found:", ", ".join(result["missing"]))
    if result["flagged"]:
        print("No year or genre in DealPOS (blank on the label):", ", ".join(result["flagged"]))


if __name__ == "__main__":
    main()
