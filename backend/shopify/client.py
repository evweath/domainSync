"""
Shopify Admin REST API client.
Handles authentication, pagination (cursor-based Link headers), and
light rate-limit back-off (leaky bucket: 40 calls / 2 per second).
"""
import asyncio
import logging
import re
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from . import connlog

logger = logging.getLogger(__name__)

_API_VERSION = "2024-01"


def _host_of(store_url: str) -> str:
    """Extract a bare host (no scheme/path) for connection-log messages."""
    u = (store_url or "").strip().rstrip("/")
    u = re.sub(r"^https?://", "", u)
    return u.split("/")[0] or "(unknown)"


async def fetch_access_token(store_url: str, client_id: str, client_secret: str) -> str:
    """Exchange client_id + client_secret for a short-lived Admin API access token (~24h)."""
    url = store_url.strip().rstrip("/")
    if not url.startswith("http"):
        url = "https://" + url
    host = _host_of(url)
    connlog.record(f"→ Auth: requesting access token from {host}")
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(
                f"{url}/admin/oauth/access_token",
                data={"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except Exception as exc:
        connlog.record(f"✗ Auth: network error to {host}: {type(exc).__name__}: {exc}", level="error")
        raise
    if resp.status_code >= 400:
        connlog.record(f"✗ Auth: {host} returned {resp.status_code} {resp.text[:120]}", level="error")
        raise ShopifyError(resp.status_code, resp.text)
    connlog.record(f"✓ Auth: received access token from {host}")
    return resp.json()["access_token"]


class ShopifyError(Exception):
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"Shopify API {status}: {body[:300]}")


class ShopifyClient:
    def __init__(self, store_url: str, access_token: str):
        url = store_url.strip().rstrip("/")
        if not url.startswith("http"):
            url = "https://" + url
        self.base = f"{url}/admin/api/{_API_VERSION}"
        self._host = _host_of(url)
        self._headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        }
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(headers=self._headers, timeout=30)
        connlog.record(f"→ Opening session to {self._host}")
        return self

    async def __aexit__(self, *_):
        if self._client:
            await self._client.aclose()

    async def _get(self, path: str, params: Optional[Dict] = None) -> httpx.Response:
        assert self._client, "Use as async context manager"
        for attempt in range(4):
            try:
                resp = await self._client.get(f"{self.base}{path}", params=params)
            except Exception as exc:
                connlog.record(f"✗ GET {self._host}{path}: {type(exc).__name__}: {exc}", level="error")
                raise
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 2 ** attempt))
                connlog.record(f"… Rate limited by {self._host} — retrying in {retry_after:.1f}s")
                logger.debug("Shopify rate limit — sleeping %.1fs", retry_after)
                await asyncio.sleep(retry_after)
                continue
            if resp.status_code >= 400:
                connlog.record(f"✗ GET {self._host}{path} → {resp.status_code}", level="error")
                raise ShopifyError(resp.status_code, resp.text)
            return resp
        connlog.record(f"✗ GET {self._host}{path} → rate limited after retries", level="error")
        raise ShopifyError(429, "Rate limited after retries")

    async def _post(self, path: str, data: Dict) -> Dict:
        assert self._client
        for attempt in range(4):
            resp = await self._client.post(f"{self.base}{path}", json=data)
            if resp.status_code == 429:
                await asyncio.sleep(2 ** attempt)
                continue
            if resp.status_code >= 400:
                raise ShopifyError(resp.status_code, resp.text)
            return resp.json()
        raise ShopifyError(429, "Rate limited")

    async def _put(self, path: str, data: Dict) -> Dict:
        assert self._client
        for attempt in range(4):
            resp = await self._client.put(f"{self.base}{path}", json=data)
            if resp.status_code == 429:
                await asyncio.sleep(2 ** attempt)
                continue
            if resp.status_code >= 400:
                raise ShopifyError(resp.status_code, resp.text)
            return resp.json()
        raise ShopifyError(429, "Rate limited")

    async def _delete(self, path: str) -> None:
        assert self._client
        resp = await self._client.delete(f"{self.base}{path}")
        if resp.status_code == 429:
            await asyncio.sleep(2)
            resp = await self._client.delete(f"{self.base}{path}")
        if resp.status_code not in (200, 204):
            raise ShopifyError(resp.status_code, resp.text)

    def _next_page_info(self, resp: httpx.Response) -> Optional[str]:
        link = resp.headers.get("Link", "")
        m = re.search(r'<[^>]+[?&]page_info=([^&>]+)[^>]*>;\s*rel="next"', link)
        return m.group(1) if m else None

    # -----------------------------------------------------------------------
    # Shop
    # -----------------------------------------------------------------------

    async def get_shop(self) -> Dict:
        resp = await self._get("/shop.json")
        shop = resp.json().get("shop", {})
        name = shop.get("name") or shop.get("myshopify_domain") or self._host
        connlog.record(f"✓ Connected to {self._host} (shop: {name})")
        return shop

    # -----------------------------------------------------------------------
    # Products (cursor-paginated)
    # -----------------------------------------------------------------------

    async def iter_products(self, limit: int = 250, status: str = "active") -> AsyncIterator[Dict]:
        params: Dict[str, Any] = {"limit": limit, "status": status}
        while True:
            resp = await self._get("/products.json", params=params)
            for p in resp.json().get("products", []):
                yield p
            page_info = self._next_page_info(resp)
            if not page_info:
                break
            params = {"limit": limit, "page_info": page_info}

    async def get_product(self, product_id: int) -> Dict:
        resp = await self._get(f"/products/{product_id}.json")
        return resp.json().get("product", {})

    async def create_product(self, data: Dict) -> Dict:
        result = await self._post("/products.json", {"product": data})
        return result.get("product", {})

    async def update_product(self, product_id: int, data: Dict) -> Dict:
        result = await self._put(f"/products/{product_id}.json", {"product": data})
        return result.get("product", {})

    # -----------------------------------------------------------------------
    # Collections
    # -----------------------------------------------------------------------

    async def get_custom_collections(self) -> List[Dict]:
        collections = []
        params: Dict[str, Any] = {"limit": 250}
        while True:
            resp = await self._get("/custom_collections.json", params=params)
            batch = resp.json().get("custom_collections", [])
            collections.extend(batch)
            page_info = self._next_page_info(resp)
            if not page_info:
                break
            params = {"limit": 250, "page_info": page_info}
        return collections

    async def get_smart_collections(self) -> List[Dict]:
        collections = []
        params: Dict[str, Any] = {"limit": 250}
        while True:
            resp = await self._get("/smart_collections.json", params=params)
            batch = resp.json().get("smart_collections", [])
            collections.extend(batch)
            page_info = self._next_page_info(resp)
            if not page_info:
                break
            params = {"limit": 250, "page_info": page_info}
        return collections

    async def get_collects(self, collection_id: Optional[int] = None) -> List[Dict]:
        """Return product↔collection membership records."""
        collects = []
        params: Dict[str, Any] = {"limit": 250}
        if collection_id:
            params["collection_id"] = collection_id
        while True:
            resp = await self._get("/collects.json", params=params)
            batch = resp.json().get("collects", [])
            collects.extend(batch)
            page_info = self._next_page_info(resp)
            if not page_info:
                break
            params = {"limit": 250, "page_info": page_info}
        return collects

    async def add_to_collection(self, collection_id: int, product_id: int) -> Dict:
        result = await self._post("/collects.json", {
            "collect": {"collection_id": collection_id, "product_id": product_id}
        })
        return result.get("collect", {})

    async def remove_from_collection(self, collect_id: int) -> None:
        await self._delete(f"/collects/{collect_id}.json")

    # -----------------------------------------------------------------------
    # Metafields
    # -----------------------------------------------------------------------

    async def get_product_metafields(self, product_id: int) -> List[Dict]:
        resp = await self._get(f"/products/{product_id}/metafields.json")
        return resp.json().get("metafields", [])

    async def set_product_metafield(self, product_id: int, namespace: str,
                                    key: str, value: str, value_type: str = "string") -> Dict:
        result = await self._post(f"/products/{product_id}/metafields.json", {
            "metafield": {"namespace": namespace, "key": key,
                          "value": value, "type": value_type}
        })
        return result.get("metafield", {})

    # -----------------------------------------------------------------------
    # Webhooks
    # -----------------------------------------------------------------------

    async def list_webhooks(self) -> List[Dict]:
        """Return all webhook subscriptions registered in this store."""
        webhooks: List[Dict] = []
        params: Dict[str, Any] = {"limit": 250}
        while True:
            resp = await self._get("/webhooks.json", params=params)
            batch = resp.json().get("webhooks", [])
            webhooks.extend(batch)
            page_info = self._next_page_info(resp)
            if not page_info:
                break
            params = {"limit": 250, "page_info": page_info}
        return webhooks

    async def create_webhook(self, topic: str, address: str, format: str = "json") -> Dict:
        """Register a new webhook subscription."""
        result = await self._post("/webhooks.json", {
            "webhook": {"topic": topic, "address": address, "format": format}
        })
        return result.get("webhook", {})

    async def delete_webhook(self, webhook_id: int) -> None:
        """Delete a webhook subscription by its Shopify ID."""
        await self._delete(f"/webhooks/{webhook_id}.json")
