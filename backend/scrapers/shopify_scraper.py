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


def _expand_variants(item: dict, base: str, domain: str) -> List[ScrapedProduct]:
    """Expand one Shopify products.json item into one ScrapedProduct per variant.

    SoR variant consolidation (Stage 1): every variant becomes a first-class
    record keyed by its own SKU/price, with a distinct source_url
    (`…/products/<handle>?variant=<id>`) so the (source_site, source_url)
    uniqueness constraint holds per variant, and a parent reference
    (parent_handle + shopify_product_id) so variants regroup for Shopify sync.
    """
    handle = item.get("handle", "")
    shopify_pid = str(item["id"]) if item.get("id") is not None else None
    base_title = item.get("title", "")
    vendor = item.get("vendor") or None
    product_type = (item.get("product_type") or "").strip() or None
    description = re.sub(r"<[^>]+>", " ", item.get("body_html") or "").strip() or None
    images = [img["src"] for img in item.get("images", []) if img.get("src")]
    option_names = [o.get("name") for o in item.get("options", []) if isinstance(o, dict)]
    product_url = f"{base}/products/{handle}"

    out: List[ScrapedProduct] = []
    for variant in item.get("variants") or [{}]:
        price_raw = variant.get("price")
        price = float(price_raw) if price_raw else None
        variant_id = variant.get("id")
        variant_title = (variant.get("title") or "").strip()

        # Non-default variant titles distinguish the display title.
        if variant_title and variant_title.lower() != "default title":
            title = f"{base_title} - {variant_title}"
        else:
            title = base_title

        url = f"{product_url}?variant={variant_id}" if variant_id is not None else product_url

        # Variant option values → ProductOption rows (skip Shopify's "Default Title").
        options = []
        for i, key in enumerate(("option1", "option2", "option3")):
            val = variant.get(key)
            if not val or str(val).strip().lower() == "default title":
                continue
            name = option_names[i] if i < len(option_names) else f"Option {i + 1}"
            options.append({"name": name, "value": val, "sku_suffix": variant.get("sku") or ""})

        sp = ScrapedProduct(
            url=url,
            title=title,
            price=price,
            price_raw=price_raw,
            in_stock=variant.get("available", True),
            sku=variant.get("sku") or None,
            manufacturer=vendor,
            category=product_type,
            description=description,
            images=images,
            options=options,
            source_site=domain,
            parent_handle=handle or None,
            shopify_product_id=shopify_pid,
        )
        sp.compute_hash()
        out.append(sp)
    return out


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
                products.extend(_expand_variants(item, base, domain))
            logger.info("Shopify %s: page %d → %d products so far", domain, page, len(products))
            if len(batch) < 250:
                break
            page += 1
            if delay > 0:
                await asyncio.sleep(delay)
    return products, rate_limited
