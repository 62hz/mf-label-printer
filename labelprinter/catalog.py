"""DealPOS catalog for label lookup. Read-only: only list_products and get_variant_detail are used,
and the client is built with read_only=True so any write is refused before it leaves this machine."""
import asyncio
import re
import time

from dealpos_mcp import tools
from dealpos_mcp.client import DealPOSClient, DealPOSError
from dealpos_mcp.config import Settings

from .model import Label, label_from_dealpos, parse_description

CATALOG_TTL = 1800          # seconds before the product list is re-read
DESCRIPTION_TTL = 24 * 3600  # seconds a looked-up year/genre is reused
SEARCH_LIMIT = 20


def read_only_client() -> DealPOSClient:
    """DEALPOS_CLIENT_ID / DEALPOS_CLIENT_SECRET come from the environment (vault project 'dealpos')."""
    return DealPOSClient(Settings(read_only=True))


class Catalog:
    def __init__(self, client, ttl: float = CATALOG_TTL, clock=time.monotonic):
        self.client = client
        self.ttl = ttl
        self._clock = clock
        self._lock = asyncio.Lock()
        self._loaded_at: float | None = None
        self._products: list[dict] = []
        self._by_variant: dict[str, tuple[dict, dict]] = {}
        self._by_product: dict[str, dict] = {}
        self._descriptions: dict[str, tuple[float, dict]] = {}

    async def refresh(self) -> int:
        rows = await tools.list_products(self.client)
        by_variant, by_product = {}, {}
        for p in rows:
            if p.get("Code"):
                by_product[str(p["Code"]).casefold()] = p
            for v in p.get("Variants") or []:
                if v.get("Code"):
                    by_variant[str(v["Code"]).casefold()] = (p, v)
        self._products, self._by_variant, self._by_product = rows, by_variant, by_product
        self._loaded_at = self._clock()
        return len(rows)

    async def ensure(self) -> None:
        async with self._lock:
            if self._loaded_at is None or self._clock() - self._loaded_at > self.ttl:
                await self.refresh()

    def status(self) -> dict:
        age = None if self._loaded_at is None else round(self._clock() - self._loaded_at)
        return {"products": len(self._products), "age_seconds": age}

    async def lookup(self, token: str) -> list[Label]:
        """A variant code gives that one variant. A product code (the barcode) gives all its variants."""
        await self.ensure()
        key = token.strip().casefold()
        if key in self._by_variant:
            p, v = self._by_variant[key]
            return [label_from_dealpos(p, v)]
        if key in self._by_product:
            p = self._by_product[key]
            return [label_from_dealpos(p, v) for v in p.get("Variants") or [] if v.get("Code")]
        return []

    async def resolve(self, text: str) -> tuple[list[Label], list[str]]:
        """Codes separated by spaces, commas or new lines -> (labels, codes not found). Repeats are dropped."""
        labels, missing, seen = [], [], set()
        for token in re.split(r"[\s,;]+", text.strip()):
            if not token or token.casefold() in seen:
                continue
            seen.add(token.casefold())
            found = await self.lookup(token)
            (labels.extend(found) if found else missing.append(token))
        return labels, missing

    async def search(self, text: str, limit: int = SEARCH_LIMIT) -> list[Label]:
        """Every word must appear in the product name or one of its codes."""
        await self.ensure()
        words = text.casefold().split()
        if not words:
            return []
        out: list[Label] = []
        for p in self._products:
            codes = " ".join(str(v.get("Code") or "") for v in p.get("Variants") or [])
            hay = f"{p.get('Name') or ''} {p.get('Code') or ''} {codes}".casefold()
            if all(w in hay for w in words):
                out += [label_from_dealpos(p, v) for v in p.get("Variants") or [] if v.get("Code")]
                if len(out) >= limit:
                    break
        return out[:limit]

    async def enrich(self, sku: str) -> dict:
        """Year and genre from the DealPOS Description. Cached; a DealPOS error returns blanks plus 'error'."""
        key = sku.strip().casefold()
        hit = self._descriptions.get(key)
        if hit and self._clock() - hit[0] < DESCRIPTION_TTL:
            return hit[1]
        try:
            detail = await tools.get_variant_detail(self.client, sku.strip())
        except DealPOSError as exc:
            return {"year": "", "genre": "", "error": str(exc)}
        result = parse_description(detail.get("Description", ""))
        self._descriptions[key] = (self._clock(), result)
        return result
