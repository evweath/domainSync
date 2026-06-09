"""
Shopify /products.json scraper utilities.

Used by source_scraper.py to fetch product listings from Shopify stores
via the public products.json endpoint (no auth required for published products).
"""
import asyncio
import logging
import re
from typing import List

import httpx

from backend.scrapers.base_scraper import ScrapedProduct

logger = logging.getLogger(__name__)


async def _is_shopify_store(base_url: str) -> bool:
    """Quick check: does /products.json?limit=1 return a products array?"""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(f"{base_url.rstrip('/')}/products.json?limit=1")
            return r.status_code == 200 and "products" in r.json()
    except Exception:
        return False


async def scrape_shopify_store(
    base_url: str, domain: str, request_delay_ms: int = 0
) -> tuple[List[ScrapedProduct], bool]:
    """Paginate through Shopify's /products.json. Returns (products, rate_limited)."""
    products: List[ScrapedProduct] = []
    rate_limited = False
    page = 1
    base = base_url.rstrip("/")
    delay = request_delay_ms / 1000.0
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        while True:
            url = f"{base}/products.json?limit=250&page={page}"
            try:
                r = await client.get(url)
                if r.status_code == 429:
                    logger.warning("Shopify %s: rate limited (429) on page %d", domain, page)
                    rate_limited = True
                    break
                r.raise_for_status()
                batch = r.json().get("products", [])
            except httpx.HTTPStatusError as exc:
                logger.warning("Shopify products.json page %d failed: %s", page, exc)
                break
            except Exception as exc:
                logger.warning("Shopify products.json page %d failed: %s", page, exc)
                break
            if not batch:
                break
            for item in batch:
                variant = item["variants"][0] if item.get("variants") else {}
                price_raw = variant.get("price")
                price = float(price_raw) if price_raw else None
                images = [img["src"] for img in item.get("images", []) if img.get("src")]
                product_type = (item.get("product_type") or "").strip() or None
                sp = ScrapedProduct(
                    url=f"{base}/products/{item['handle']}",
                    title=item.get("title", ""),
                    price=price,
                    price_raw=price_raw,
                    in_stock=variant.get("available", True),
                    sku=variant.get("sku") or None,
                    manufacturer=item.get("vendor") or None,
                    category=product_type,
                    description=re.sub(r"<[^>]+>", " ", item.get("body_html") or "").strip() or None,
                    images=images,
                    source_site=domain,
                )
                sp.compute_hash()
                products.append(sp)
            logger.info("Shopify %s: page %d → %d products so far", domain, page, len(products))
            if len(batch) < 250:
                break
            page += 1
            if delay > 0:
                await asyncio.sleep(delay)
    return products, rate_limited
