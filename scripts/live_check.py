"""Read real DealPOS data for some SKUs and print what the label would say. Read-only.

  vault run dealpos -- uv run python scripts/live_check.py AMEAMET158 ALEHEAC557 ...
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from labelprinter.catalog import Catalog, read_only_client  # noqa: E402
from labelprinter.model import price_text  # noqa: E402


async def main(codes: list[str]) -> None:
    catalog = Catalog(read_only_client())
    labels, missing = await catalog.resolve(" ".join(codes))
    print(f"catalog: {catalog.status()['products']} products")
    for label in labels:
        info = await catalog.enrich(label.sku)
        year, genre = label.year or info["year"], label.genre or info["genre"]
        print(f"{label.sku:<16} {label.format or '-':<9} {price_text(label.price):<12} year={year or '-':<5} genre={genre or '-':<22} {label.artist} | {label.title}")
        if info.get("error"):
            print("   enrich error:", info["error"])
    if missing:
        print("NOT FOUND:", ", ".join(missing))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
