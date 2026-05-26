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

import sqlalchemy.exc

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


async def _db_write_with_retry(fn, retries: int = 4, base_delay: float = 3.0):
    """Run fn() inside session_scope(), retrying on SQLite 'database is locked'."""
    for attempt in range(retries):
        try:
            with session_scope() as db:
                return fn(db)
        except sqlalchemy.exc.OperationalError as exc:
            if 'database is locked' not in str(exc).lower() or attempt == retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning('[PROD-SEARCH] DB locked, retry %d/%d in %.0fs', attempt + 1, retries, delay)
            await asyncio.sleep(delay)

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
    # Remove everything inside parentheses: (00799579), (APPROX- 226 DOZEN/HR), (4), etc.
    title = re.sub(r'\([^)]*\)', '', title)
    # Compound electrical/voltage specs: 208-240v/60/3-ph, 480V/60Hz/3Ph, 208v
    title = re.sub(r'\b\d+[-/]?\d*\s*[Vv]\b(?:[-/]\d+[\w-]*)*', '', title)
    # Remaining standalone: 60Hz, 3ph, 3-phase, 5kW
    title = re.sub(r'\b\d+\s*[-]?\s*(?:hz|ph|phase|kw|kva)\b[\w/-]*', '', title, flags=re.I)
    # Leading size/package codes: "Small 5.1 ", "3.1-"
    title = re.sub(r'^(?:Small|Medium|Large)?\s*\d+\.\d+[-\s]', '', title, flags=re.I)
    # Standalone part numbers (all-caps/digits with dashes, 6+ chars)
    title = re.sub(r'\b[A-Z0-9]{2,}-[A-Z0-9\-]{3,}\b', '', title)
    # Leftover punctuation noise
    title = re.sub(r'[,;:/]', ' ', title)
    title = re.sub(r'(?<!\w)-|-(?!\w)', ' ', title)
    title = ' '.join(title.split())
    if len(title) > 60:
        words = title.split()
        result, length = [], 0
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
    if mfg_in_title:
        # Strip manufacturer from title so it only appears once in the final query
        cleaned_title = re.sub(r'(?i)\b' + re.escape(mfg) + r'\b', '', cleaned_title)
        cleaned_title = ' '.join(cleaned_title.split())

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


def _snapshot_product(p: Product) -> dict:
    return {
        'id': p.id,
        'title': p.canonical_title,
        'manufacturer': p.manufacturer,
        'model_number': p.model_number,
        'sku': p.sku,
        'price': p.price_canonical,
        'category': p.category,
    }


async def _process_one_product(
    snap: dict,
    criteria: MatchCriteria,
    source_domains: set,
    max_competitors: int,
    max_urls: int,
    emit: Callable,
    search_query_override: Optional[str] = None,
    log_prefix: str = "[PROD-SEARCH]",
) -> int:
    """Search the web for competitor listings of a single product and persist matches.

    Returns the number of NEW competitor-domain matches recorded for this product
    (already-stored matches and price-only updates do not count toward this number).
    """
    query_str = _build_query(_P(snap), search_query_override)

    logger.info("%s ── Product: %r  (id=%d)", log_prefix, snap['title'], snap['id'])
    logger.info("%s    Query:   %r", log_prefix, query_str)

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

    logger.info("%s    Search returned %d result URLs", log_prefix, len(search_results))

    if not search_results:
        logger.info("%s    No search results — skipping this product", log_prefix)
        await emit('product_comp_search_product_done', {
            'product_id': snap['id'],
            'product_title': snap['title'],
            'found': 0,
            'visited': 0,
        })
        return 0

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

            def _do_db_work(db):
                master_products = db.query(Product).filter(Product.is_active == True).all()
                result = match_competitor_product(comp_dict, master_products, criteria)
                if result is None:
                    result = match_similar_product(comp_dict, master_products)

                if result is None:
                    logger.info(
                        "[PROD-SEARCH]       No match  (page title: %r)",
                        comp_dict.get('title', '')[:60],
                    )
                    return False

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

                return True

            if not await _db_write_with_retry(_do_db_work):
                continue

            found_count += 1

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
        "%s ── Done: product=%r  visited=%d  found=%d/%d",
        log_prefix, snap['title'], visited_count, found_count, max_competitors,
    )
    await emit('product_comp_search_product_done', {
        'product_id': snap['id'],
        'product_title': snap['title'],
        'found': found_count,
        'visited': visited_count,
    })
    return found_count


# ---------------------------------------------------------------------------
# Sequential top-level entry (existing API)
# ---------------------------------------------------------------------------

async def run_product_competitor_search(
    product_ids: List[int],
    search_query: Optional[str] = None,
    max_competitors: int = 10,
    max_urls: int = 50,
    callbacks: Optional[List[Callable]] = None,
) -> dict:
    """Sequential per-product competitor search (one product at a time)."""
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
            Product.id.in_(product_ids),
        ).all()
        snaps = [_snapshot_product(p) for p in products]

    await emit('product_comp_search_start', {
        'total_products': len(snaps),
        'max_competitors': max_competitors,
    })

    for snap in snaps:
        total_found += await _process_one_product(
            snap, criteria, source_domains,
            max_competitors, max_urls, emit, search_query,
        )

    return {'product_ids': product_ids, 'total_found': total_found}


# ---------------------------------------------------------------------------
# Parallel top-level entry (new — 4-worker queue + 5-minute DB refresh)
# ---------------------------------------------------------------------------

# Module-level handle so the API can query / cancel the running scan.
_parallel_state: Dict[str, Any] = {
    'task': None,         # asyncio.Task or None
    'progress': None,     # dict, updated in place by workers
    'started_at': None,   # datetime
}


def get_parallel_search_state() -> dict:
    """Snapshot of the currently-running parallel scan (or empty dict if idle)."""
    task = _parallel_state.get('task')
    if task is None or task.done():
        return {'running': False}
    return {
        'running': True,
        'started_at': _parallel_state['started_at'].isoformat() if _parallel_state['started_at'] else None,
        'progress': dict(_parallel_state['progress'] or {}),
    }


def cancel_parallel_search() -> bool:
    task = _parallel_state.get('task')
    if task is None or task.done():
        return False
    task.cancel()
    return True


async def run_parallel_product_competitor_search(
    num_workers: int = 4,
    sync_interval_seconds: int = 300,
    max_competitors: int = 10,
    max_urls: int = 50,
    product_ids: Optional[List[int]] = None,
    callbacks: Optional[List[Callable]] = None,
) -> dict:
    """Run competitor search across many products with a worker pool.

    Spawns *num_workers* async worker tasks that pull product IDs from a
    shared queue. Every *sync_interval_seconds* a refresher re-queries
    active products and enqueues any that weren't there at start (or were
    added since). The scan runs until externally cancelled or until the
    queue is drained and no new products show up in two refresh cycles.
    """
    cbs = callbacks or []
    source_domains = _get_source_domains()
    criteria = MatchCriteria()

    async def emit(event: str, data: dict) -> None:
        for cb in cbs:
            try:
                await cb(event, data)
            except Exception:
                pass

    queue: asyncio.Queue = asyncio.Queue()
    processed_ids: set = set()
    in_flight_ids: set = set()
    progress: Dict[str, Any] = {
        'total_queued': 0,
        'processed': 0,
        'total_found': 0,
        'workers_active': 0,
        'num_workers': num_workers,
        'sync_interval_seconds': sync_interval_seconds,
        'last_refresh_at': None,
        'started_at': datetime.utcnow().isoformat(),
    }
    _parallel_state['progress'] = progress
    _parallel_state['started_at'] = datetime.utcnow()

    def _load_target_snapshots() -> List[dict]:
        with session_scope() as db:
            q = db.query(Product).filter(Product.is_active == True)
            if product_ids:
                q = q.filter(Product.id.in_(product_ids))
            return [_snapshot_product(p) for p in q.all()]

    def _enqueue_new(snaps: List[dict]) -> int:
        added = 0
        for s in snaps:
            if s['id'] in processed_ids or s['id'] in in_flight_ids:
                continue
            in_flight_ids.add(s['id'])
            queue.put_nowait(s)
            progress['total_queued'] += 1
            added += 1
        return added

    # Initial load
    initial = _load_target_snapshots()
    added = _enqueue_new(initial)
    logger.info(
        "[PARALLEL-SEARCH] Starting: %d products queued, %d workers, sync_interval=%ds",
        added, num_workers, sync_interval_seconds,
    )
    await emit('parallel_search_start', {
        'total_products': added,
        'num_workers': num_workers,
        'sync_interval_seconds': sync_interval_seconds,
        'max_competitors': max_competitors,
    })

    async def worker(worker_id: int) -> None:
        prefix = f"[PARALLEL-SEARCH][w{worker_id}]"
        while True:
            snap = await queue.get()
            progress['workers_active'] += 1
            try:
                found = await _process_one_product(
                    snap, criteria, source_domains,
                    max_competitors, max_urls, emit,
                    log_prefix=prefix,
                )
                progress['total_found'] += found
                processed_ids.add(snap['id'])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("%s failed on product id=%d: %s", prefix, snap['id'], exc)
            finally:
                in_flight_ids.discard(snap['id'])
                progress['processed'] += 1
                progress['workers_active'] -= 1
                queue.task_done()
                await emit('parallel_search_progress', {
                    'worker_id': worker_id,
                    'processed': progress['processed'],
                    'total_queued': progress['total_queued'],
                    'remaining': queue.qsize(),
                    'total_found': progress['total_found'],
                    'workers_active': progress['workers_active'],
                })

    async def refresher() -> None:
        while True:
            await asyncio.sleep(sync_interval_seconds)
            try:
                added_n = _enqueue_new(_load_target_snapshots())
                progress['last_refresh_at'] = datetime.utcnow().isoformat()
                if added_n:
                    logger.info(
                        "[PARALLEL-SEARCH] refresh added %d new products (total_queued=%d)",
                        added_n, progress['total_queued'],
                    )
                await emit('parallel_search_refresh', {
                    'new_products': added_n,
                    'total_queued': progress['total_queued'],
                    'processed': progress['processed'],
                    'last_refresh_at': progress['last_refresh_at'],
                })
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("[PARALLEL-SEARCH] refresh failed: %s", exc)

    worker_tasks = [asyncio.create_task(worker(i)) for i in range(num_workers)]
    refresh_task = asyncio.create_task(refresher())

    try:
        # Drain the queue, then wait one refresh cycle to see if more
        # products show up; bail if two consecutive refreshes added nothing.
        empty_refreshes = 0
        while True:
            await queue.join()
            queued_before = progress['total_queued']
            await asyncio.sleep(sync_interval_seconds + 1)
            if progress['total_queued'] == queued_before and queue.empty():
                empty_refreshes += 1
                if empty_refreshes >= 2:
                    break
            else:
                empty_refreshes = 0
    except asyncio.CancelledError:
        logger.info("[PARALLEL-SEARCH] cancelled by caller")
        raise
    finally:
        refresh_task.cancel()
        for w in worker_tasks:
            w.cancel()
        await asyncio.gather(*worker_tasks, refresh_task, return_exceptions=True)
        _parallel_state['task'] = None

    await emit('parallel_search_complete', {
        'total_processed': progress['processed'],
        'total_found': progress['total_found'],
        'total_queued': progress['total_queued'],
    })
    logger.info(
        "[PARALLEL-SEARCH] complete: processed=%d total_found=%d",
        progress['processed'], progress['total_found'],
    )

    return {
        'total_processed': progress['processed'],
        'total_found': progress['total_found'],
        'total_queued': progress['total_queued'],
    }
