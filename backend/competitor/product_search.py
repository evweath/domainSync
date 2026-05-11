"""
Per-product sequential competitor search.
Searches for competitors for specific products one URL at a time,
stopping when the desired number of competitor domains are found.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from backend.competitor.matcher import MatchCriteria, match_competitor_product, match_similar_product
from backend.database.db import session_scope
from backend.database.models import (
    Competitor,
    CompetitorProductMatch,
    CompetitorScrapingProfile,
    PriceHistory,
    Product,
)
from backend.search.engine import multi_engine_search

logger = logging.getLogger(__name__)

_FETCH_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) '
        'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15'
    ),
    'Accept': 'text/html,application/xhtml+xml,*/*;q=0.9',
    'Accept-Language': 'en-US,en;q=0.9',
}

_PRICE_RE = re.compile(r'\$\s*([\d,]+(?:\.\d{1,2})?)')
_MODEL_RE = re.compile(r'(?:model|part|item)[#\s:]+([A-Z0-9][\w\-]{2,})', re.I)


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lstrip('www.')
    except Exception:
        return ''


def _build_query(product: Any, override: Optional[str]) -> str:
    if override:
        return override
    parts: List[str] = []
    if product.manufacturer and product.model_number:
        parts.append(product.manufacturer)
        parts.append(f'"{product.model_number}"')
    elif product.model_number:
        parts.append(f'"{product.model_number}"')
    else:
        title = (product.canonical_title or '')[:80]
        parts.append(title)
    parts.append('buy')
    return ' '.join(parts)


def _extract_price(text: str) -> Optional[float]:
    m = _PRICE_RE.search(text or '')
    if m:
        try:
            return float(m.group(1).replace(',', ''))
        except ValueError:
            pass
    return None


def _parse_jsonld(html: str) -> Optional[Dict[str, Any]]:
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.I
    ):
        try:
            data = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            continue
        items = data if isinstance(data, list) else [data]
        if isinstance(data, dict) and '@graph' in data:
            items = data['@graph']
        for item in items:
            if not isinstance(item, dict):
                continue
            type_val = item.get('@type', '')
            if 'Product' not in (type_val if isinstance(type_val, str) else ' '.join(type_val)):
                continue
            price: Optional[float] = None
            offers = item.get('offers', {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if isinstance(offers, dict):
                raw_price = offers.get('price') or offers.get('lowPrice')
                if raw_price is not None:
                    try:
                        price = float(str(raw_price).replace(',', '').replace('$', ''))
                    except ValueError:
                        pass
            brand = item.get('brand', {})
            manufacturer = brand.get('name') if isinstance(brand, dict) else (brand or None)
            in_stock = 'InStock' in json.dumps(item.get('offers', ''))
            return {
                'title': item.get('name', ''),
                'price': price,
                'model_number': item.get('model') or item.get('mpn'),
                'manufacturer': manufacturer,
                'sku': item.get('sku'),
                'in_stock': in_stock,
            }
    return None


def _meta_val(html: str, prop: str) -> Optional[str]:
    m = re.search(
        rf'<meta[^>]+(?:property|name)=["\'][^"\']*{re.escape(prop)}[^"\']*["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.I
    )
    if m:
        return m.group(1).strip()
    m = re.search(
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'][^"\']*{re.escape(prop)}[^"\']*["\']',
        html, re.I
    )
    return m.group(1).strip() if m else None


def _parse_meta(html: str) -> Dict[str, Any]:
    title_tag = re.search(r'<title[^>]*>([^<]{1,300})</title>', html, re.I)
    title = _meta_val(html, 'og:title') or _meta_val(html, 'title') or (title_tag.group(1).strip() if title_tag else '')
    price_str = (
        _meta_val(html, 'price:amount') or _meta_val(html, 'og:price:amount') or
        _meta_val(html, 'product:price:amount') or _meta_val(html, 'price')
    )
    price: Optional[float] = None
    if price_str:
        try:
            price = float(re.sub(r'[^\d.]', '', price_str))
        except ValueError:
            pass
    if price is None:
        price = _extract_price(html[:8000])
    return {
        'title': title or '',
        'price': price,
        'model_number': _meta_val(html, 'model') or _meta_val(html, 'mpn'),
        'manufacturer': _meta_val(html, 'og:brand') or _meta_val(html, 'brand'),
        'sku': _meta_val(html, 'sku') or _meta_val(html, 'product:retailer_item_id'),
        'in_stock': True,
    }


def _get_source_domains() -> set:
    try:
        from backend.config import config
        sites = config.get('source_sites') or []
        return {s['domain'] for s in sites if s.get('domain')}
    except Exception:
        return {'donut-supplies.com', 'donut-equipment.com', 'bakerywholesalers.com'}


class _P:
    """Lightweight product proxy from a snapshot dict."""
    def __init__(self, s: dict) -> None:
        self.__dict__.update(s)
        self.canonical_title = s['title']
        self.price_canonical = s['price']


async def run_product_competitor_search(
    product_ids: List[int],
    search_query: Optional[str] = None,
    max_competitors: int = 5,
    max_urls: int = 30,
    callbacks: Optional[List[Callable]] = None,
) -> dict:
    cbs = callbacks or []
    source_domains = _get_source_domains()
    criteria = MatchCriteria()
    total_found = 0

    async def emit(event: str, data: dict) -> None:
        for cb in cbs:
            try:
                await cb(event, data)
            except Exception:
                pass

    with session_scope() as db:
        products = db.query(Product).filter(
            Product.is_active == True,
            Product.id.in_(product_ids)
        ).all()
        product_snapshots = [
            {
                'id': p.id,
                'title': p.canonical_title,
                'manufacturer': p.manufacturer,
                'model_number': p.model_number,
                'sku': p.sku,
                'price': p.price_canonical,
                'category': p.category,
            }
            for p in products
        ]

    await emit('product_comp_search_start', {
        'total_products': len(product_snapshots),
        'max_competitors': max_competitors,
    })

    for snap in product_snapshots:
        query_str = _build_query(_P(snap), search_query)

        logger.info("[PROD-SEARCH] Searching: product=%r  query=%r", snap['title'], query_str)

        await emit('product_comp_search_progress', {
            'product_id': snap['id'],
            'product_title': snap['title'],
            'phase': 'searching',
            'found': 0,
            'max': max_competitors,
        })

        # Fetch search results
        search_results = await multi_engine_search(
            query=query_str,
            max_results=max_urls,
            exclude_domains=source_domains,
        )

        logger.info("[PROD-SEARCH] Search returned %d results for %r", len(search_results), snap['title'])

        visited_domains: set = set()
        found_count = 0

        async with httpx.AsyncClient(headers=_FETCH_HEADERS, timeout=12, follow_redirects=True) as client:
            for item in search_results:
                if found_count >= max_competitors:
                    break

                url = item.get('href') or item.get('url', '')
                if not url:
                    continue
                domain = _domain(url)
                if not domain or domain in source_domains or domain in visited_domains:
                    continue

                visited_domains.add(domain)

                logger.info("[PROD-SEARCH] Visiting %s  (product=%r  found=%d/%d)", domain, snap['title'], found_count, max_competitors)

                await emit('product_comp_search_progress', {
                    'product_id': snap['id'],
                    'product_title': snap['title'],
                    'phase': 'visiting',
                    'current_url': url,
                    'current_domain': domain,
                    'found': found_count,
                    'max': max_competitors,
                })

                # Fetch and parse the page
                try:
                    r = await client.get(url)
                    if r.status_code not in (200, 206):
                        logger.debug("[PROD-SEARCH] %s returned HTTP %d — skipping", domain, r.status_code)
                        continue
                    html = r.text
                    page_data = _parse_jsonld(html) or _parse_meta(html)
                    if not page_data:
                        page_data = {
                            'title': item.get('title', ''),
                            'price': _extract_price(item.get('body', '')),
                            'model_number': None,
                            'manufacturer': None,
                            'sku': None,
                            'in_stock': True,
                        }
                    else:
                        page_data.setdefault('in_stock', True)
                except Exception as exc:
                    logger.debug("Failed to fetch %s: %s", url, exc)
                    continue

                comp_dict = {
                    'title': page_data.get('title', ''),
                    'price': page_data.get('price'),
                    'model_number': page_data.get('model_number'),
                    'manufacturer': page_data.get('manufacturer'),
                    'sku': page_data.get('sku'),
                    'description': item.get('body', ''),
                    'image_hash': None,
                }

                # Match against all active products, focus on the target product
                with session_scope() as db:
                    master_products = db.query(Product).filter(Product.is_active == True).all()
                    result = match_competitor_product(comp_dict, master_products, criteria)
                    if result is None:
                        result = match_similar_product(comp_dict, master_products)

                    if result is None:
                        logger.debug("[PROD-SEARCH] No match on %s for product=%r  page_title=%r", domain, snap['title'], comp_dict.get('title', '')[:60])
                        continue

                    competitor = db.query(Competitor).filter(Competitor.domain == domain).first()
                    if competitor is None:
                        competitor = Competitor(
                            domain=domain,
                            name=domain,
                            base_url=f'https://{domain}',
                            is_active=True,
                        )
                        db.add(competitor)
                        db.flush()
                        logger.info('[PROD-SEARCH] Auto-created competitor: %s', domain)

                    competitor_id = competitor.id

                    existing = (
                        db.query(CompetitorProductMatch)
                        .filter(
                            CompetitorProductMatch.master_product_id == result.master_product_id,
                            CompetitorProductMatch.competitor_id == competitor_id,
                            CompetitorProductMatch.competitor_url == url,
                        )
                        .first()
                    )

                    price = page_data.get('price')
                    in_stock = page_data.get('in_stock', True)
                    price_str = f"${price:.2f}" if price else "no price"

                    if existing:
                        if price and existing.competitor_price != price:
                            logger.info("[PROD-SEARCH] Price update  domain=%s  product=%r  price=%s", domain, snap['title'], price_str)
                            existing.competitor_price = price
                            existing.scanned_at = datetime.utcnow()
                            db.add(PriceHistory(match_id=existing.id, price=price, in_stock=in_stock))
                    else:
                        logger.info("[PROD-SEARCH] Match found  domain=%s  product=%r  price=%s  confidence=%d%%", domain, snap['title'], price_str, int(result.confidence or 0))
                        match = CompetitorProductMatch(
                            master_product_id=result.master_product_id,
                            competitor_id=competitor_id,
                            competitor_url=url,
                            competitor_title=page_data.get('title', '')[:500],
                            competitor_price=price,
                            match_type='|'.join(result.match_types),
                            match_confidence=result.confidence,
                            match_reasons_json=json.dumps(result.reasons),
                            in_stock=in_stock,
                            is_similar=result.is_similar,
                            similarity_reason=result.similarity_reason,
                            scanned_at=datetime.utcnow(),
                        )
                        db.add(match)
                        db.flush()
                        if price:
                            db.add(PriceHistory(match_id=match.id, price=price, in_stock=in_stock))

                    total_matching = (
                        db.query(CompetitorProductMatch)
                        .filter(
                            CompetitorProductMatch.competitor_id == competitor_id,
                            CompetitorProductMatch.is_active == True,
                        )
                        .count()
                    )
                    competitor.total_matching_products = total_matching
                    competitor.last_scanned_at = datetime.utcnow()
                    if not competitor.first_scanned_at:
                        competitor.first_scanned_at = datetime.utcnow()

                found_count += 1
                total_found += 1

                await emit('product_comp_search_progress', {
                    'product_id': snap['id'],
                    'product_title': snap['title'],
                    'phase': 'found',
                    'found': found_count,
                    'max': max_competitors,
                    'domain': domain,
                    'url': url,
                    'price': page_data.get('price'),
                })

                await asyncio.sleep(0.5)  # brief pause between requests

        await emit('product_comp_search_product_done', {
            'product_id': snap['id'],
            'product_title': snap['title'],
            'found': found_count,
            'visited': len(visited_domains),
        })

    return {
        'product_ids': product_ids,
        'total_found': total_found,
    }
