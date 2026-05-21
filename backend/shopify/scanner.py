"""
Full-store Shopify scanner.
Fetches all products, variants, images, collections, product↔collection
memberships, and metafields into a structured in-memory snapshot.
Progress is reported via an optional async callback.
"""
import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from .client import ShopifyClient

logger = logging.getLogger(__name__)


async def scan_store(
    store_url: str,
    access_token: str,
    progress_cb: Optional[Callable[[str, int, int], None]] = None,
) -> Dict[str, Any]:
    """
    Returns a snapshot dict:
    {
        "shop": {...},
        "products": {handle: product_dict},          # keyed by handle
        "products_by_id": {shopify_id: handle},
        "collections": {collection_id: collection_dict},
        "collects": [{collection_id, product_id, collect_id}],
        "product_collections": {product_id: [collection_id, ...]},
        "collection_products": {collection_id: [product_id, ...]},
        "metafields": {product_id: [metafield_dict, ...]},
    }
    """
    def _progress(stage: str, done: int = 0, total: int = 0):
        logger.debug("scan_store [%s] %d/%d", stage, done, total)
        if progress_cb:
            progress_cb(stage, done, total)

    snapshot: Dict[str, Any] = {
        "shop": {},
        "products": {},
        "products_by_id": {},
        "collections": {},
        "collects": [],
        "product_collections": {},
        "collection_products": {},
        "metafields": {},
    }

    async with ShopifyClient(store_url, access_token) as client:
        # Shop info
        _progress("shop")
        snapshot["shop"] = await client.get_shop()

        # Products
        _progress("products", 0, 0)
        count = 0
        async for product in client.iter_products():
            handle = product.get("handle", "")
            if handle:
                snapshot["products"][handle] = product
                snapshot["products_by_id"][product["id"]] = handle
            count += 1
            if count % 100 == 0:
                _progress("products", count, count)
        _progress("products", count, count)
        logger.info("scan_store: fetched %d products from %s", count, store_url)

        # Collections
        _progress("collections")
        custom = await client.get_custom_collections()
        smart = await client.get_smart_collections()
        for col in custom + smart:
            col["_type"] = "custom" if col in custom else "smart"
            snapshot["collections"][col["id"]] = col
        logger.info("scan_store: %d collections", len(snapshot["collections"]))

        # Collects (product↔collection membership)
        _progress("collects")
        collects = await client.get_collects()
        snapshot["collects"] = collects
        for c in collects:
            pid = c["product_id"]
            cid = c["collection_id"]
            snapshot["product_collections"].setdefault(pid, []).append(cid)
            snapshot["collection_products"].setdefault(cid, []).append(pid)
        logger.info("scan_store: %d collect mappings", len(collects))

        # Metafields (one request per product — only fetch if store is small enough)
        product_count = len(snapshot["products"])
        if product_count <= 500:
            _progress("metafields", 0, product_count)
            done = 0
            for product_id in list(snapshot["products_by_id"].keys()):
                try:
                    mfs = await client.get_product_metafields(product_id)
                    if mfs:
                        snapshot["metafields"][product_id] = mfs
                except Exception as exc:
                    logger.debug("metafields fetch failed for %s: %s", product_id, exc)
                done += 1
                if done % 50 == 0:
                    _progress("metafields", done, product_count)
            _progress("metafields", done, product_count)
        else:
            logger.info("scan_store: skipping per-product metafields (%d products — too large)", product_count)

    return snapshot
