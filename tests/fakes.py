"""A DealPOS stand-in for tests and the dev server: same two endpoints the app uses, no network."""

PRODUCTS = [
    {"ID": "p1", "Code": "AMEAMET158", "Category": "Cassette Import", "Name": "KASET American Football - American Football (Deluxe Edition)",
     "Brand": "", "SupplierName": "X", "Released": True, "Discontinued": False,
     "Variants": [{"ID": "v1", "Code": "AMEAMET158", "Model": "Default", "UnitCost": 207493, "UnitPrice": 305000, "Discontinued": False}]},
    {"ID": "p2", "Code": "191404155127", "Category": "CD Import", "Name": "CD Nourished By Time - The Passionate Ones",
     "Brand": "", "SupplierName": "X", "Released": True, "Discontinued": False,
     "Variants": [{"ID": "v2", "Code": "NOUPASC001", "Model": "Default", "UnitCost": 150000, "UnitPrice": 330000, "Discontinued": False},
                  {"ID": "v3", "Code": "NOUPASC002", "Model": "Used", "UnitCost": 90000, "UnitPrice": 200000, "Discontinued": False}]},
    {"ID": "p3", "Code": "SYIN200SPKCW65", "Category": "Speakers", "Name": "SYITREN N200 Mini Portable Bluetooth Speaker",
     "Brand": "", "SupplierName": "S", "Released": True, "Discontinued": False,
     "Variants": [{"ID": "v4", "Code": "SYIN200SPKCW65", "Model": "Cream White", "UnitCost": 612429, "UnitPrice": 949000, "Discontinued": False}]},
]

DESCRIPTIONS = {
    "AMEAMET158": "<div>American Football<br>Released: 1999 (Deluxe reissue) &bull; Genre: Rock &bull; Style: Emo</div>",
    "NOUPASC001": "<div>Format: CD<br>Released: 2024 &bull; Genre: Soul</div>",
}


def design(slug="mf-april"):
    """A built-in design dict, for tests."""
    from pathlib import Path

    from labelprinter.designs import DesignStore

    return DesignStore(Path("no-such-user-dir")).get(slug)


class FakeClient:
    """Mimics the DealPOSClient.request calls used by dealpos_mcp.tools.list_products / get_variant_detail."""

    def __init__(self, products=None, descriptions=None):
        self.products = PRODUCTS if products is None else products
        self.descriptions = DESCRIPTIONS if descriptions is None else descriptions
        self.calls = []

    async def request(self, method, path, params=None, json=None):
        self.calls.append((method, path, dict(params or {})))
        if method == "GET" and path == "/api/v3/Product":
            page, size = params["PageNumber"], params["PageSize"]
            return {"DataArray": self.products[(page - 1) * size: page * size], "RecordsCount": -1}
        if method == "GET" and path == "/api/v3/Variant/Detail":
            code = params["Code"]
            return {"Code": code, "Description": self.descriptions.get(code, ""), "UnitCost": 1}
        raise AssertionError(f"unexpected call {method} {path}")
