"""
Per-product sequential competitor search.
Searches for a product, then visits result URLs one at a time (skipping already-seen
domains) until the desired number of competitor matches are found.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

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

_PRICE_RE = re.compile(r'\$\s*([\d,]+(?:\.\d{1,2})?)')
_MODEL_RE = re.compile(r'(?:model|part|item)[#\s:]+([A-Z0-9][\w\-]{2,})', re.I)

# Heuristic product-type extraction. The category columns in the DB are
# all NULL (no AI categorization has run), so the "product type" signal
# for the search query is derived from canonical_title via this keyword
# list. Multi-word phrases are listed before single-word catch-alls so
# the longest match wins.
_PRODUCT_TYPE_KEYWORDS = [
    # Donut-specific equipment
    "donut fryer", "donut glazer", "donut depositor", "donut filler", "donut hopper",
    "donut maker", "donut machine", "donut sheeter", "donut cutter", "donut roller",
    "donut robot", "icing machine", "glazing machine", "production sheeter",
    # Mixing / dough
    "spiral mixer", "planetary mixer", "stand mixer", "dough mixer", "dough sheeter",
    "dough divider", "dough rounder", "dough cutter", "dough roller", "rotary cutter",
    # Ovens & baking
    "convection oven", "rotary oven", "rack oven", "deck oven", "pizza oven",
    "conveyor oven", "combi oven",
    # Proofing
    "retarder proofer", "proofing cabinet", "proofer", "retarder",
    # Frying
    "deep fryer", "fryer",
    # Refrigeration
    "walk-in cooler", "walk-in freezer", "reach-in cooler", "reach-in freezer",
    "display case", "merchandiser", "freezer", "refrigerator", "cooler",
    # Holding / warming
    "holding cabinet", "warmer", "heated cabinet",
    # Tables / surfaces
    "feed table", "production table", "work table", "prep table",
    # Ventilation
    "exhaust hood", "ventilation hood", "hood",
    # Smallwares / parts
    "shelving", "scale", "sink", "cart", "rack", "shelf", "screen", "tray", "pan",
    # Ingredients
    "icing", "frosting", "glaze", "filling", "shortening", "syrup", "mix",
    # Generic catch-alls (last resort)
    "sheeter", "cutter", "roller", "robot", "depositor",
    "oven", "mixer", "hopper", "machine", "table",
]


def _extract_product_type(title: Optional[str]) -> str:
    """Return the longest keyword from _PRODUCT_TYPE_KEYWORDS found in *title*, else ''."""
    if not title:
        return ""
    lowered = title.lower()
    for kw in _PRODUCT_TYPE_KEYWORDS:
        if kw in lowered:
            return kw
    return ""


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lstrip('www.')
    except Exception:
        return ''


async def _curl_fetch(url: str, timeout: int = 15) -> str:
    """Fetch a URL via subprocess curl — bypasses Python TLS fingerprint filtering."""
    cmd = [
        'curl', '-s', '-L',
        '--max-time', str(timeout),
        '--compressed',
        '-A', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15',
        '-H', 'Accept: text/html,application/xhtml+xml,*/*;q=0.9',
        '-H', 'Accept-Language: en-US,en;q=0.9',
        url,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout + 2)
        return stdout.decode('utf-8', errors='replace')
    except Exception as exc:
        logger.debug("curl fetch failed for %s: %s", url, exc)
        return ''


def _clean_title_for_search(title: str) -> str:
    title = re.sub(r'\([^)]*\)', '', title)
    title = re.sub(r'\b\d+[/\-]\d+[/\-]?\d*\s*[Vv]?[Hh][Zz]?\S*', '', title)
    title = re.sub(r'\b\d+\s*(?:V|v|Hz|hz|Ph|ph|KW|kW)\b', '', title)
    title = re.sub(r'^(?:Small|Medium|Large)?\s*\d+\.\d+[-\s]', '', title, flags=re.I)
    title = re.sub(r'\b[A-Z0-9]{2,}-[A-Z0-9\-]{3,}\b', '', title)
    title = re.sub(r'[,;:/]', ' ', title)
    title = re.sub(r'\s[-–]\s', ' ', title)
    title = ' '.join(title.split())
    if len(title) > 60:
        words = title.split()
        result = []
        length = 0
        for word in words:
            if length + len(word) + (1 if result else 0) > 60:
                break
            result.append(word)
            length += len(word) + (1 if len(result) > 1 else 0)
        title = ' '.join(result)
    return title.strip()


def _build_query(product: Any, override: Optional[str]) -> str:
    """Build a competitor-search query string from a product.

    Strategy:
      * Anchor on the strongest identifier available — quoted model_number,
        else manufacturer, else cleaned title tokens.
      * Always include a cleaned slice of the title (specs/voltage stripped).
      * Append the heuristically-extracted product_type unless the same
        word(s) are already present in the title — duplicating hurts
        precision more than it helps recall.
    """
    if override:
        return override

    title_raw = product.canonical_title or ''
    cleaned_title = _clean_title_for_search(title_raw)
    mfg = (product.manufacturer or '').strip()
    model = product.model_number
    product_type = _extract_product_type(title_raw)

    parts: List[str] = []
    # Treat all-digit "model numbers" of 12+ chars as UPC barcodes — quoting
    # them as an exact-match phrase in a web search is poison (no competitor
    # site lists products by foreign-vendor UPC, so the SERP collapses to 0).
    clean_model = re.sub(r'[^\w\-]', '', model) if model else ''
    looks_like_upc = clean_model.isdigit() and len(clean_model) >= 12
    use_model = bool(clean_model) and not looks_like_upc

    mfg_in_title = bool(mfg) and mfg.lower() in cleaned_title.lower()

    if use_model:
        if mfg and not mfg_in_title:
            parts.append(mfg)
        parts.append(f'"{clean_model}"')
        # Carry the cleaned title minus the model (the cleaner already
        # strips alnum-dash codes, but be defensive in case the model is
        # plain digits like "5001").
        rest = re.sub(re.escape(clean_model), '', cleaned_title, flags=re.I).strip()
        if rest:
            parts.append(rest)
    else:
        if mfg and not mfg_in_title:
            parts.append(mfg)
        if cleaned_title:
            parts.append(cleaned_title)

    if product_type:
        haystack = ' '.join(parts).lower()
        if product_type.lower() not in haystack:
            parts.append(product_type)

    parts.append('buy')
    return ' '.join(p for p in parts if p)


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

            image_raw = item.get('image')
            if isinstance(image_raw, list):
                image_raw = image_raw[0] if image_raw else None
            if isinstance(image_raw, dict):
                image_url = image_raw.get('url') or image_raw.get('contentUrl')
            else:
                image_url = image_raw

            desc = item.get('description', '')
            if isinstance(desc, str) and len(desc) > 2000:
                desc = desc[:2000]

            return {
                'title': item.get('name', ''),
                'price': price,
                'model_number': item.get('model') or item.get('mpn'),
                'manufacturer': manufacturer,
                'sku': item.get('sku'),
                'in_stock': in_stock,
                'image': image_url or None,
                'description': desc or None,
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
        'image': _meta_val(html, 'og:image') or _meta_val(html, 'twitter:image'),
        'description': _meta_val(html, 'og:description') or _meta_val(html, 'description'),
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
    max_competitors: int = 10,
    max_urls: int = 50,
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

        logger.info("[PROD-SEARCH] ── Product: %r  (id=%d)", snap['title'], snap['id'])
        logger.info("[PROD-SEARCH]    Query:   %r", query_str)

        await emit('product_comp_search_progress', {
            'product_id': snap['id'],
            'product_title': snap['title'],
            'phase': 'searching',
            'found': 0,
            'max': max_competitors,
        })

        search_results = await multi_engine_search(
            query=query_str,
            max_results=max_urls,
            exclude_domains=source_domains,
        )

        logger.info("[PROD-SEARCH]    Search returned %d result URLs", len(search_results))

        if not search_results:
            logger.info("[PROD-SEARCH]    No search results — skipping this product")
            await emit('product_comp_search_product_done', {
                'product_id': snap['id'],
                'product_title': snap['title'],
                'found': 0,
                'visited': 0,
            })
            continue

        visited_domains: set = set()
        found_count = 0
        visited_count = 0

        for idx, item in enumerate(search_results):
            if found_count >= max_competitors:
                break

            url = item.get('href') or item.get('url', '')
            if not url:
                continue
            domain = _domain(url)
            if not domain or domain in source_domains or domain in visited_domains:
                continue

            visited_domains.add(domain)
            visited_count += 1

            logger.info("[PROD-SEARCH]    [%d] Visiting: %s", visited_count, url)

            await emit('product_comp_search_progress', {
                'product_id': snap['id'],
                'product_title': snap['title'],
                'phase': 'visiting',
                'current_url': url,
                'current_domain': domain,
                'found': found_count,
                'max': max_competitors,
            })

            html = await _curl_fetch(url)
            if not html:
                logger.info("[PROD-SEARCH]       Fetch failed — skipping")
                continue

            page_data = _parse_jsonld(html) or _parse_meta(html)
            if not page_data:
                page_data = {
                    'title': item.get('title', ''),
                    'price': _extract_price(item.get('body', '')),
                    'model_number': None,
                    'manufacturer': None,
                    'sku': None,
                    'in_stock': True,
                    'image': None,
                    'description': item.get('body', '') or None,
                }
            else:
                page_data.setdefault('in_stock', True)
                page_data.setdefault('image', None)
                page_data.setdefault('description', None)

            comp_dict = {
                'title': page_data.get('title', ''),
                'price': page_data.get('price'),
                'model_number': page_data.get('model_number'),
                'manufacturer': page_data.get('manufacturer'),
                'sku': page_data.get('sku'),
                'description': page_data.get('description', '') or item.get('body', ''),
                'image_hash': None,
            }

            with session_scope() as db:
                master_products = db.query(Product).filter(Product.is_active == True).all()
                result = match_competitor_product(comp_dict, master_products, criteria)
                if result is None:
                    result = match_similar_product(comp_dict, master_products)

                if result is None:
                    logger.info(
                        "[PROD-SEARCH]       No match  (page title: %r)",
                        comp_dict.get('title', '')[:60],
                    )
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
                    logger.info('[PROD-SEARCH]       Auto-created competitor: %s', domain)

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
                image_url = page_data.get('image')
                price_str = f"${price:.2f}" if price else "no price"

                if existing:
                    if price and existing.competitor_price != price:
                        logger.info(
                            "[PROD-SEARCH]       Price update  domain=%s  %s → %s",
                            domain, existing.competitor_price, price_str,
                        )
                        existing.competitor_price = price
                        existing.scanned_at = datetime.utcnow()
                        db.add(PriceHistory(match_id=existing.id, price=price, in_stock=in_stock))
                    else:
                        logger.info("[PROD-SEARCH]       Already stored  domain=%s", domain)
                else:
                    logger.info(
                        "[PROD-SEARCH]       MATCH  domain=%s  price=%s  confidence=%d%%",
                        domain, price_str, int(result.confidence or 0),
                    )
                    match = CompetitorProductMatch(
                        master_product_id=result.master_product_id,
                        competitor_id=competitor_id,
                        competitor_url=url,
                        competitor_title=page_data.get('title', '')[:500],
                        competitor_price=price,
                        competitor_image_url=(image_url or '')[:2000] or None,
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

            await asyncio.sleep(0.5)

        logger.info(
            "[PROD-SEARCH] ── Done: product=%r  visited=%d  found=%d/%d",
            snap['title'], visited_count, found_count, max_competitors,
        )

        await emit('product_comp_search_product_done', {
            'product_id': snap['id'],
            'product_title': snap['title'],
            'found': found_count,
            'visited': visited_count,
        })

    return {
        'product_ids': product_ids,
        'total_found': total_found,
    }
