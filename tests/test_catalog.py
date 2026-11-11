from pathlib import Path

import pytest
from dealpos_mcp.client import DealPOSClient, DealPOSError
from dealpos_mcp.config import Settings

from labelprinter import catalog as catalog_module
from labelprinter.catalog import Catalog
from tests.fakes import FakeClient


async def test_lookup_variant_code_gives_one_label_with_mapped_fields():
    cat = Catalog(FakeClient())
    [label] = await cat.lookup("ameamet158")  # case-insensitive
    assert (label.sku, label.artist, label.title, label.format, label.price) == (
        "AMEAMET158", "American Football", "American Football (Deluxe Edition)", "CASSETTE", 305000)


async def test_lookup_product_code_gives_every_variant():
    cat = Catalog(FakeClient())
    labels = await cat.lookup("191404155127")  # the product barcode
    assert [l.sku for l in labels] == ["NOUPASC001", "NOUPASC002"]
    assert labels[0].artist == "Nourished By Time" and labels[0].format == "CD"


async def test_resolve_reports_missing_and_drops_repeats():
    cat = Catalog(FakeClient())
    labels, missing = await cat.resolve("AMEAMET158, nope1\nAMEAMET158  191404155127")
    assert [l.sku for l in labels] == ["AMEAMET158", "NOUPASC001", "NOUPASC002"]
    assert missing == ["nope1"]


async def test_search_needs_every_word_and_finds_by_name_or_code():
    cat = Catalog(FakeClient())
    assert [l.sku for l in await cat.search("american football")] == ["AMEAMET158"]
    assert [l.sku for l in await cat.search("passionate nourished")] == ["NOUPASC001", "NOUPASC002"]
    assert await cat.search("zzz") == []
    assert await cat.search("   ") == []
    assert len(await cat.search("e", limit=2)) == 2


async def test_catalog_is_cached_until_ttl_then_refreshed():
    now = [0.0]
    client = FakeClient()
    cat = Catalog(client, ttl=100, clock=lambda: now[0])
    await cat.lookup("AMEAMET158")
    await cat.lookup("AMEAMET158")
    assert sum(1 for c in client.calls if c[1] == "/api/v3/Product") == 1
    now[0] = 101
    await cat.lookup("AMEAMET158")
    assert sum(1 for c in client.calls if c[1] == "/api/v3/Product") == 2


async def test_enrich_reads_description_once_then_uses_cache():
    client = FakeClient()
    cat = Catalog(client)
    assert await cat.enrich("AMEAMET158") == {"year": "1999", "genre": "Rock"}
    assert await cat.enrich("AMEAMET158") == {"year": "1999", "genre": "Rock"}
    assert sum(1 for c in client.calls if c[1] == "/api/v3/Variant/Detail") == 1
    assert await cat.enrich("NOUPASC002") == {"year": "", "genre": ""}  # no Released/Genre text


async def test_enrich_survives_a_dealpos_error():
    class Broken(FakeClient):
        async def request(self, method, path, params=None, json=None):
            raise DealPOSError("DealPOS API error (429): slow down")

    result = await Catalog(Broken()).enrich("AMEAMET158")
    assert result["year"] == "" and "429" in result["error"]


async def test_client_refuses_writes():
    client = DealPOSClient(Settings(client_id="x", client_secret="y", read_only=True))
    with pytest.raises(DealPOSError, match="Read-only"):
        await client.request("POST", "/api/v3/Product", json={})
    with pytest.raises(DealPOSError, match="Read-only"):
        await client.request("DELETE", "/api/v3/Product")


def test_read_only_client_builds_with_the_read_only_flag(monkeypatch):
    monkeypatch.setenv("DEALPOS_CLIENT_ID", "x")
    monkeypatch.setenv("DEALPOS_CLIENT_SECRET", "y")
    monkeypatch.setenv("DEALPOS_READ_ONLY", "false")  # the environment must not be able to switch it off
    assert catalog_module.read_only_client().s.read_only is True


def test_app_code_never_touches_a_write_tool():
    src = "".join(p.read_text(encoding="utf-8") for p in Path("labelprinter").glob("*.py"))
    for word in ("create_product", "update_product", "adjust_stock", "upsert_pricebook", "create_customer", "set_variant"):
        assert word not in src
