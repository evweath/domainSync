"""
Web search engine for Find This Product, Beat This Price, Find Me Customers,
and web-search-first competitor scanning.
Supports DuckDuckGo, Bing, Google, Yahoo, and Google Shopping — no API keys required.
"""
import asyncio
import base64
import json
import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, unquote, quote_plus

logger = logging.getLogger(__name__)

_PRICE_RE = re.compile(r'\$\s*[\d,]+(?:\.\d{1,2})?')
_MODEL_RE = re.compile(
    r'(?:model|model\s*#|model\s*no|part\s*#|sku|item\s*#)[:\s#]+([A-Z0-9][\w\-/]{2,})', re.I
)
_PHONE_RE = re.compile(
    r'(?<!\d)(?:\+1[\s.\-]?)?\(?(\d{3})\)?[\s.\-](\d{3})[\s.\-](\d{4})(?!\d)'
)
_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.I,
)
_LOCAL_SCHEMA_TYPES = {
    'LocalBusiness', 'FoodEstablishment', 'Restaurant', 'Bakery',
    'CafeOrCoffeeShop', 'Store', 'Organization', 'Florist',
    'HealthAndBeautyBusiness', 'FoodService',
}
_GEOCODE_SEM = asyncio.Semaphore(1)  # one Nominatim call at a time


def _extract_phone(text: str) -> str:
    m = _PHONE_RE.search(text or '')
    return f'({m.group(1)}) {m.group(2)}-{m.group(3)}' if m else ''


def _parse_schema_nap(html: str) -> Dict[str, str]:
    """Extract name/phone/address from JSON-LD schema.org markup."""
    nap: Dict[str, str] = {}
    for m in _JSONLD_RE.finditer(html):
        try:
            data = json.loads(m.group(1))
            if isinstance(data, list):
                data = next((d for d in data if d.get('@type') in _LOCAL_SCHEMA_TYPES), None)
                if not data:
                    continue
            if data.get('@type') not in _LOCAL_SCHEMA_TYPES:
                continue
            if not nap.get('name'):
                nap['name'] = str(data.get('name', ''))
            if not nap.get('phone'):
                nap['phone'] = str(data.get('telephone', ''))
            if not nap.get('address'):
                addr = data.get('address', {})
                if isinstance(addr, dict):
                    parts = [
                        addr.get('streetAddress', ''),
                        addr.get('addressLocality', ''),
                        addr.get('addressRegion', ''),
                        addr.get('postalCode', ''),
                    ]
                    nap['address'] = ', '.join(p for p in parts if p)
                elif isinstance(addr, str):
                    nap['address'] = addr
        except Exception:
            pass
    return nap


async def _fetch_nap(url: str) -> Dict[str, str]:
    html = await _curl_get(url, timeout=7)
    if not html:
        return {}
    nap = _parse_schema_nap(html)
    # Fallback: extract phone from page if schema didn't have one
    if not nap.get('phone'):
        nap['phone'] = _extract_phone(html[:20000])
    return nap


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


async def _geocode(location: str) -> Optional[Tuple[float, float]]:
    """Geocode a string via Nominatim (OSM). Rate-limited to 1 req/s."""
    async with _GEOCODE_SEM:
        try:
            import httpx
            url = (
                'https://nominatim.openstreetmap.org/search'
                f'?q={quote_plus(location)}&format=json&limit=1'
            )
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    url,
                    headers={'User-Agent': 'DonutIntel/1.0'},
                    timeout=8.0,
                )
                data = resp.json()
                if data:
                    await asyncio.sleep(1.1)  # respect Nominatim 1 req/s policy
                    return float(data[0]['lat']), float(data[0]['lon'])
        except Exception as exc:
            logger.debug('Geocode failed for %r: %s', location, exc)
        return None


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lstrip('www.')
    except Exception:
        return ''


def _is_homepage(url: str) -> bool:
    """Return True if the URL is a bare domain homepage with no meaningful path."""
    try:
        path = urlparse(url).path
        return not path or path == '/'
    except Exception:
        return False


def _extract_price(text: str) -> Optional[str]:
    m = _PRICE_RE.search(text or '')
    return m.group(0).strip() if m else None


def _extract_model(text: str) -> Optional[str]:
    m = _MODEL_RE.search(text or '')
    return m.group(1).strip() if m else None


async def _run_sync(fn):
    return await asyncio.get_event_loop().run_in_executor(None, fn)


async def _curl_get(url: str, extra_headers: Optional[List[str]] = None, timeout: int = 15) -> str:
    """Fetch a URL via primp browser impersonation — same TLS fingerprinting as curl, but URL stays
    in-process memory and is not visible in the process table (ps/top)."""
    import primp
    headers = {
        'Accept': 'text/html,application/xhtml+xml,*/*;q=0.9',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    for h in (extra_headers or []):
        if ': ' in h:
            k, v = h.split(': ', 1)
            headers[k] = v
    try:
        async with primp.AsyncClient(impersonate='random', timeout=timeout) as client:
            r = await asyncio.wait_for(client.get(url, headers=headers), timeout + 2)
            return r.text
    except Exception as exc:
        logger.debug("primp_get failed for %s: %s", url, exc)
        return ''


async def _text_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Search DuckDuckGo HTML endpoint via curl (avoids httpx socket issues)."""
    try:
        q = quote_plus(query)
        # Use the HTML endpoint — no JS required, returns structured result anchors
        html = await _curl_get(
            f'https://html.duckduckgo.com/html/?q={q}&kl=us-en',
            extra_headers=['Referer: https://duckduckgo.com/'],
        )
        if not html:
            return []
        results = []
        seen: set = set()
        # DDG HTML: result links are in <a class="result__a" href="...">
        for m in re.finditer(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            html, re.DOTALL
        ):
            href = m.group(1).replace('&amp;', '&')
            href = unquote(href)
            # DDG wraps some links in its redirect: //duckduckgo.com/l/?uddg=...
            redir = re.search(r'uddg=([^&"]+)', href)
            if redir:
                href = unquote(redir.group(1))
            # Skip any remaining duckduckgo.com URLs (ads, trackers)
            if 'duckduckgo.com' in href:
                continue
            title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            d = _domain(href)
            if not d or d in seen:
                continue
            seen.add(d)
            results.append({'href': href, 'title': title, 'body': ''})
            if len(results) >= max_results:
                break
        logger.debug("DDG returned %d results for %r", len(results), query[:60])
        return results
    except Exception as exc:
        logger.debug("DDG text search failed: %s", exc)
        return []


async def _image_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    def _search():
        from ddgs import DDGS
        with DDGS() as ddgs:
            return list(ddgs.images(query, max_results=max_results, backend='duckduckgo'))
    try:
        return await _run_sync(_search)
    except Exception as exc:
        logger.warning(f"DDG image search failed (images will be missing): {exc}")
        return []


def _img_index(images: List[Dict]) -> Dict[str, str]:
    """Build domain → image-url index from DDG image results."""
    idx: Dict[str, str] = {}
    for img in images:
        d = _domain(img.get('url', ''))
        if d and d not in idx:
            idx[d] = img.get('image') or img.get('thumbnail', '')
    return idx


_SEARCH_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) '
        'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15'
    ),
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'en-US,en;q=0.9',
}


_DDG_SEARCH_LOCK = asyncio.Lock()  # serialize DDG calls to avoid rate-limit bans


_BING_SKIP_DOMAINS = frozenset({'bing.com', 'r.bing.com', 'go.microsoft.com', 'microsoft.com',
                                  'facebook.com', 'youtube.com'})

# Domains that should never appear as product results regardless of search engine
_NOISE_DOMAINS = frozenset({
    'google.com', 'shopping.google.com',
    'merriam-webster.com', 'dictionary.com', 'dictionary.cambridge.org',
    'wikipedia.org', 'wikimedia.org',
    'reddit.com', 'quora.com',
    'twitter.com', 'x.com', 'instagram.com', 'pinterest.com', 'tiktok.com',
    'youtube.com', 'facebook.com',
    'yelp.com',
    'offerup.com', 'letgo.com', 'craigslist.org',
    # Own/source stores — should never appear as competitor or supplier results
    'bakerywholesalers.com', 'donut-supplies.com', 'donut-equipment.com',
})


def _cite_to_url(cite_html: str) -> str:
    """Convert a Bing display URL (with › separators) into a real URL."""
    text = re.sub(r'<[^>]+>', '', cite_html).strip()
    text = text.replace(' › ', '/').replace('› ', '/').replace(' ›', '/')
    # Strip Bing's display ellipsis — path was truncated, keep only what we have
    text = re.sub(r'[…\.]{2,}\s*$', '', text).rstrip('/')
    if not text.startswith('http'):
        text = 'https://' + text
    return text


async def _bing_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Scrape Bing SERP via curl — reconstructs URLs from cite display tags."""
    try:
        q = quote_plus(query)
        url = f"https://www.bing.com/search?q={q}&count={min(max_results * 2, 50)}&mkt=en-US&setlang=en-US&cc=US"
        html = await _curl_get(url)
        if not html:
            return []
        results = []
        seen: set = set()

        for block in re.finditer(r'class="b_algo[^"]*"(.*?)</li>', html, re.DOTALL):
            b = block.group(1)
            cite_m = re.search(r'<cite[^>]*>(.*?)</cite>', b, re.DOTALL)
            h2_m = re.search(r'<h2[^>]*>(.*?)</h2>', b, re.DOTALL)
            if not cite_m:
                continue
            href = _cite_to_url(cite_m.group(1))
            if _is_homepage(href):
                continue
            title = re.sub(r'<[^>]+>', '', h2_m.group(1)).strip() if h2_m else ''
            d = _domain(href)
            if not d or any(skip in d for skip in _BING_SKIP_DOMAINS) or d in _NOISE_DOMAINS:
                continue
            if d in seen:
                continue
            seen.add(d)
            # Extract snippet from first paragraph in the result block
            snip_m = re.search(r'<p[^>]*>(.*?)</p>', b, re.DOTALL)
            body = re.sub(r'<[^>]+>', '', snip_m.group(1)).strip() if snip_m else ''
            results.append({'href': href, 'title': title, 'body': body})
            if len(results) >= max_results:
                break

        logger.debug("Bing returned %d results for %r", len(results), query[:60])
        return results
    except Exception as exc:
        logger.debug("Bing search failed: %s", exc)
        return []


async def _google_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Scrape Google SERP via curl (best-effort — may be blocked)."""
    try:
        q = quote_plus(query)
        url = f"https://www.google.com/search?q={q}&num={min(max_results * 2, 50)}&hl=en&gl=us"
        html = await _curl_get(url)
        if not html:
            return []
        results = []
        seen: set = set()
        for m in re.finditer(r'href="/url\?q=(https?://(?!www\.google\.com)[^&"]+)&', html):
            href = unquote(m.group(1))
            d = _domain(href)
            if d and d not in seen:
                seen.add(d)
                results.append({'href': href, 'title': '', 'body': ''})
            if len(results) >= max_results:
                break
        logger.debug("Google returned %d results for %r", len(results), query[:60])
        return results
    except Exception as exc:
        logger.debug("Google search failed: %s", exc)
        return []


async def _yahoo_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Scrape Yahoo SERP via curl."""
    try:
        q = quote_plus(query)
        url = f"https://search.yahoo.com/search?p={q}&n={min(max_results * 2, 50)}"
        html = await _curl_get(url)
        if not html:
            return []
        results = []
        seen: set = set()
        # Yahoo encodes real URLs in RU=... query param; strip tracking suffixes
        for m in re.finditer(r'RU=(https?%3[Aa]%2[Ff]%2[Ff][^&"]+)', html):
            href = unquote(m.group(1))
            href = re.sub(r'/RK=\d+/RS=[^/\s"]+', '', href)  # remove Yahoo tracking
            d = _domain(href)
            if d and 'yahoo.com' not in d and d not in seen:
                seen.add(d)
                results.append({'href': href, 'title': '', 'body': ''})
            if len(results) >= max_results:
                break
        return results
    except Exception as exc:
        logger.debug("Yahoo search failed: %s", exc)
        return []


async def _serpapi_shopping_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Fetch Google Shopping via SerpAPI.

    Stage 1: organic engine — inline_shopping_results have direct merchant link fields (query-dependent).
    Stage 2: google_shopping engine + immersive product API — fetches direct store URLs and prices
             for the top N results (costs one extra SerpAPI credit per item).
    """
    from backend.config import Config
    api_key = (Config().get('serpapi', 'api_key') or '').strip()
    if not api_key:
        return []
    try:
        import json as _json
        q = quote_plus(query)
        results: List[Dict[str, Any]] = []
        seen: set = set()

        # Stage 1: organic engine (1 credit) — works when Google shows inline shopping results
        organic_url = (
            f"https://serpapi.com/search.json"
            f"?engine=google&q={q}&api_key={api_key}&num=10&gl=us&hl=en"
        )
        html = await _curl_get(organic_url, timeout=20)
        if html:
            data = _json.loads(html)
            for item in data.get('inline_shopping_results', []):
                href = item.get('link', '')
                if not href or 'google.com' in href or href in seen:
                    continue
                domain = _domain(href)
                if not domain:
                    continue
                seen.add(href)
                price_raw = str(item.get('price', '') or '')
                results.append({
                    'href': href, 'url': href, 'domain': domain,
                    'title': item.get('title', '')[:200],
                    'body': f"{item.get('source', domain)} — {price_raw}".strip(' —'),
                    'price': price_raw,
                    'source': 'shopping',
                })
                if len(results) >= max_results:
                    break

        if results:
            logger.info("SerpAPI inline shopping: %d results for %r", len(results), query[:60])
            return results

        # Stage 2: google_shopping engine + immersive API for direct store links
        shop_url = (
            f"https://serpapi.com/search.json"
            f"?engine=google_shopping&q={q}&api_key={api_key}&num=20&gl=us&hl=en"
        )
        html2 = await _curl_get(shop_url, timeout=20)
        if not html2:
            return []
        data2 = _json.loads(html2)

        # Concurrently fetch immersive API for up to 8 top products
        imm_items = [
            item for item in data2.get('shopping_results', [])[:8]
            if item.get('serpapi_immersive_product_api')
        ]
        if not imm_items:
            return []
        imm_resps = await asyncio.gather(
            *[_curl_get(f"{item['serpapi_immersive_product_api']}&api_key={api_key}", timeout=15)
              for item in imm_items],
            return_exceptions=True,
        )
        for resp in imm_resps:
            if isinstance(resp, Exception) or not resp:
                continue
            try:
                imm_data = _json.loads(resp)
                for store in imm_data.get('product_results', {}).get('stores', []):
                    href = store.get('link', '')
                    if not href or href in seen:
                        continue
                    domain = _domain(href)
                    if not domain or 'google.com' in domain:
                        continue
                    seen.add(href)
                    price_raw = str(store.get('price', '') or '')
                    results.append({
                        'href': href, 'url': href, 'domain': domain,
                        'title': store.get('title', store.get('name', domain))[:200],
                        'body': f"{store.get('name', domain)} — {price_raw}".strip(' —'),
                        'price': price_raw,
                        'source': 'shopping',
                    })
                    if len(results) >= max_results:
                        break
            except Exception:
                pass
            if len(results) >= max_results:
                break

        logger.info("SerpAPI Shopping (immersive): %d results for %r", len(results), query[:60])
        return results
    except Exception as exc:
        logger.debug("SerpAPI Shopping failed: %s", exc)
        return []


async def _google_shopping_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Google Shopping: try SerpAPI first, fall back to HTML scraping."""
    results = await _serpapi_shopping_search(query, max_results)
    if results:
        return results
    # Fallback: HTML scraping (works only when Google doesn't serve a JS-gate page)
    try:
        q = quote_plus(query)
        url = f"https://www.google.com/search?q={q}&tbm=shop&num=40&hl=en&gl=us"
        html = await _curl_get(url)
        if not html:
            return []
        results: List[Dict[str, Any]] = []
        seen: set = set()

        # Shopping results embed structured blocks. Parse with multiple strategies.
        # Strategy 1: blocks identified by Google Shopping CSS classes / data attributes
        for block_m in re.finditer(
            r'<(?:div|li)[^>]*(?:class="[^"]*(?:sh-dgr|sh-dlr|sh-pr|KZmu8e|i0X6df)[^"]*"|'
            r'data-docid="[^"]+")[^>]*>(.*?)</(?:div|li)>',
            html, re.DOTALL | re.I,
        ):
            block = block_m.group(1)
            price_m = _PRICE_RE.search(block)
            if not price_m:
                continue
            price = price_m.group(0).strip()

            title = ''
            t_m = re.search(r'<h[2-4][^>]*>(.*?)</h[2-4]>', block, re.DOTALL | re.I)
            if t_m:
                title = re.sub(r'<[^>]+>', '', t_m.group(1)).strip()
            if not title:
                al_m = re.search(r'aria-label="([^"]{5,})"', block)
                if al_m:
                    title = al_m.group(1)

            href = ''
            href_m = re.search(r'href="/url\?q=(https?://(?!www\.google\.com)[^&"]+)&', block)
            if href_m:
                href = unquote(href_m.group(1))
            if not href:
                href_m2 = re.search(r'href="(https?://(?!(?:www\.)?google\.com)[^"]+)"', block)
                if href_m2:
                    href = href_m2.group(1)
            if not href:
                continue

            domain = _domain(href)
            if not domain or href in seen:
                continue
            seen.add(href)

            merch_m = re.search(
                r'class="[^"]*(?:aULzUe|NbK1N|merchant|seller)[^"]*"[^>]*>(.*?)</(?:span|div)>',
                block, re.DOTALL | re.I,
            )
            merchant = re.sub(r'<[^>]+>', '', merch_m.group(1)).strip() if merch_m else ''

            results.append({
                'href': href, 'url': href, 'domain': domain,
                'title': title or merchant or domain,
                'body': f"{merchant} — {price}" if merchant else price,
                'price': price, 'source': 'shopping',
            })
            if len(results) >= max_results:
                break

        # Strategy 2: fallback — any non-Google link near a price in the page
        if not results:
            stripped = re.sub(r'<(?:script|style)[^>]*>.*?</(?:script|style)>', ' ', html,
                              flags=re.DOTALL | re.I)
            for m in re.finditer(r'href="(https?://(?!(?:www\.)?google\.com)[^"]+)"', stripped):
                href = m.group(1)
                domain = _domain(href)
                if not domain or href in seen:
                    continue
                ctx = stripped[max(0, m.start() - 100): m.end() + 300]
                price_m = _PRICE_RE.search(ctx)
                if not price_m:
                    continue
                seen.add(href)
                results.append({
                    'href': href, 'url': href, 'domain': domain,
                    'title': domain, 'body': price_m.group(0),
                    'price': price_m.group(0).strip(), 'source': 'shopping',
                })
                if len(results) >= max_results:
                    break

        logger.debug("Google Shopping returned %d results for %r", len(results), query[:60])
        return results
    except Exception as exc:
        logger.debug("Google Shopping search failed: %s", exc)
        return []


async def _bing_shopping_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Scrape Bing Shopping — merchant URLs are base64-encoded in the u= param of aclick redirects."""
    try:
        q = quote_plus(query)
        url = f"https://www.bing.com/shop?q={q}&count={min(max_results * 2, 40)}&cc=US&setlang=en-US"
        html = await _curl_get(url)
        if not html:
            return []
        results: List[Dict[str, Any]] = []
        seen: set = set()

        # Bing Shopping product cards use anchors with class="br-offLink" that href to
        # https://www.bing.com/aclick?...&u=<URL-safe-base64-encoded-merchant-URL>&...
        for m in re.finditer(r'br-offLink[^>]+href="([^"]+)"', html):
            aclick_url = m.group(1).replace('&amp;', '&')
            u_m = re.search(r'[?&]u=([A-Za-z0-9+/\-_]+=*)', aclick_url)
            if not u_m:
                continue
            b64 = u_m.group(1).replace('-', '+').replace('_', '/')
            b64 += '=' * (-len(b64) % 4)
            try:
                merchant_url = unquote(base64.b64decode(b64).decode('utf-8', errors='replace'))
            except Exception:
                continue
            if not merchant_url.startswith('http'):
                continue
            domain = _domain(merchant_url)
            if not domain or domain in _NOISE_DOMAINS or domain in seen:
                continue

            # Look in a 2000-char window around the anchor for title and price
            card = html[max(0, m.start() - 2000): min(len(html), m.end() + 2000)]

            title = ''
            title_m = re.search(r'<span[^>]+title="([^"]{5,200})"', card)
            if title_m:
                title = title_m.group(1)
            if not title:
                h_m = re.search(r'<h[2-4][^>]*>(.*?)</h[2-4]>', card, re.DOTALL)
                if h_m:
                    title = re.sub(r'<[^>]+>', '', h_m.group(1)).strip()

            price = ''
            br_price_m = re.search(r'class="br-price"[^>]*>(.*?)</', card, re.DOTALL)
            if br_price_m:
                price = re.sub(r'<[^>]+>', '', br_price_m.group(1)).strip()
            if not price:
                price_re_m = _PRICE_RE.search(card)
                if price_re_m:
                    price = price_re_m.group(0).strip()

            seen.add(domain)
            results.append({
                'href': merchant_url, 'url': merchant_url, 'domain': domain,
                'title': title or domain,
                'body': price,
                'price': price or None,
                'source': 'bing_shopping',
            })
            if len(results) >= max_results:
                break

        logger.debug('Bing Shopping: %d results for %r', len(results), query[:60])
        return results
    except Exception as exc:
        logger.debug('Bing Shopping failed: %s', exc)
        return []


async def _duckduckgo_shopping_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Scrape DuckDuckGo Shopping tab using Playwright (JS-rendered).

    DDG shopping has no server-rendered endpoint, so we use a headless browser
    with a short timeout. Returns empty list on failure rather than raising.
    """
    try:
        from playwright.async_api import async_playwright

        q = quote_plus(query)
        url = f"https://duckduckgo.com/?q={q}&ia=shopping&iax=shopping"
        results: List[Dict[str, Any]] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = await ctx.new_page()
            try:
                await page.goto(url, timeout=15000, wait_until="domcontentloaded")
                # Wait for shopping results to appear (or timeout)
                try:
                    await page.wait_for_selector('[data-testid="shopping-result"], .js-shopping-result, .tile--shopping', timeout=8000)
                except Exception:
                    pass  # No shopping results loaded — still try to parse

                html = await page.content()
            finally:
                await browser.close()

        seen: set = set()
        # DDG shopping cards typically contain product links with prices
        # Try multiple selector patterns across DDG versions
        for link_m in re.finditer(
            r'href="(https?://[^"]+)"[^>]*>[^<]*<[^>]+>[^<]*</[^>]+>\s*[^<]*(\$[\d,.]+)',
            html
        ):
            merchant_url, price_str = link_m.group(1), link_m.group(2)
            domain = _domain(merchant_url)
            if not domain or domain in _NOISE_DOMAINS or domain in seen or 'duckduckgo' in domain:
                continue
            seen.add(domain)
            results.append({
                'href': merchant_url, 'url': merchant_url, 'domain': domain,
                'title': domain,
                'body': price_str,
                'price': price_str,
                'source': 'ddg_shopping',
            })
            if len(results) >= max_results:
                break

        # Also try JSON-LD embedded product data
        for script_m in re.finditer(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL):
            try:
                data = json.loads(script_m.group(1))
                if not isinstance(data, dict):
                    continue
                if data.get('@type') in ('Product', 'ItemList', 'Offer'):
                    offers = data.get('offers', {})
                    if isinstance(offers, dict):
                        offers = [offers]
                    for offer in (offers or []):
                        merchant_url = offer.get('url', '')
                        if not merchant_url:
                            continue
                        domain = _domain(merchant_url)
                        if not domain or domain in seen or 'duckduckgo' in domain:
                            continue
                        seen.add(domain)
                        price = offer.get('price') or offer.get('lowPrice')
                        results.append({
                            'href': merchant_url, 'url': merchant_url, 'domain': domain,
                            'title': data.get('name', domain),
                            'body': str(price or ''),
                            'price': str(price) if price else None,
                            'source': 'ddg_shopping',
                        })
            except Exception:
                continue

        logger.debug('DDG Shopping: %d results for %r', len(results), query[:60])
        return results[:max_results]
    except Exception as exc:
        logger.debug('DDG Shopping failed: %s', exc)
        return []


async def _yahoo_shopping_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Scrape Walmart search via __NEXT_DATA__ JSON (replaces Yahoo Shopping which is JS-only).

    Walmart embeds all search results in a __NEXT_DATA__ blob that is accessible via curl.
    Results map to walmart.com product URLs so they count as one competitor domain.
    """
    try:
        import json as _json
        q = quote_plus(query)
        url = f"https://www.walmart.com/search?q={q}"
        html = await _curl_get(url)
        if not html:
            return []

        nd_m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL | re.I)
        if not nd_m:
            return []

        nd = _json.loads(nd_m.group(1))
        stacks = (
            nd.get('props', {})
            .get('pageProps', {})
            .get('initialData', {})
            .get('searchResult', {})
            .get('itemStacks', [])
        )
        results: List[Dict[str, Any]] = []
        seen_urls: set = set()
        for stack in stacks:
            for item in stack.get('items', []):
                canon = item.get('canonicalUrl', '')
                if not canon:
                    continue
                href = f"https://www.walmart.com{canon.split('?')[0]}"
                if href in seen_urls:
                    continue
                price_raw = item.get('price')
                if not price_raw:
                    price_raw = (item.get('priceInfo') or {}).get('currentPrice', '')
                price_str = f"${float(price_raw):,.2f}" if price_raw else None
                seen_urls.add(href)
                results.append({
                    'href': href, 'url': href, 'domain': 'walmart.com',
                    'title': item.get('name', '')[:200],
                    'body': price_str or '',
                    'price': price_str,
                    'source': 'yahoo_shopping',
                })
                if len(results) >= max_results:
                    break
            if len(results) >= max_results:
                break

        logger.debug('Walmart Shopping: %d results for %r', len(results), query[:60])
        return results
    except Exception as exc:
        logger.debug('Walmart Shopping failed: %s', exc)
        return []


# URL patterns to try when searching a competitor's own site, ordered by likelihood.
_SITE_SEARCH_PATTERNS = [
    '/search?q={q}',
    '/search/?q={q}',
    '/search?query={q}',
    '/search.php?search_query={q}',     # BigCommerce
    '/catalogsearch/result/?q={q}',     # Magento
    '/?s={q}',                          # WordPress / WooCommerce
    '/?search={q}',
    '/search/{q}',                      # Shopify path-style
    '/search?keywords={q}',
    '/search?term={q}',
]

_SITE_SKIP_HREFS = frozenset([
    '/cart', '/login', '/account', '/blog', '/category', '/categories',
    '/collections', '/tag/', '/page/', '/checkout', 'javascript:', 'mailto:',
])


def _parse_site_search_results(html: str, base_domain: str) -> List[Dict[str, Any]]:
    """Extract product cards from a competitor site's search-results page."""
    clean = re.sub(r'<(?:script|style)[^>]*>.*?</(?:script|style)>', ' ', html,
                   flags=re.DOTALL | re.I)
    results: List[Dict[str, Any]] = []
    seen_urls: set = set()

    for m in re.finditer(r'<a\b[^>]+href="([^"#][^"]*)"[^>]*>(.*?)</a>', clean,
                         re.DOTALL | re.I):
        raw_href = m.group(1).strip()
        link_text = re.sub(r'<[^>]+>', ' ', m.group(2))
        link_text = re.sub(r'\s+', ' ', link_text).strip()
        if len(link_text) < 4:
            continue
        if any(s in raw_href.lower() for s in _SITE_SKIP_HREFS):
            continue

        if raw_href.startswith('http'):
            href = raw_href
        elif raw_href.startswith('/'):
            href = f'https://{base_domain}{raw_href}'
        else:
            continue

        if _domain(href) != base_domain:
            continue
        if href in seen_urls:
            continue

        ctx = clean[max(0, m.start() - 50): m.end() + 400]
        price_m = _PRICE_RE.search(ctx)
        if not price_m:
            continue

        seen_urls.add(href)
        plain_ctx = re.sub(r'<[^>]+>', ' ', ctx)
        plain_ctx = re.sub(r'\s+', ' ', plain_ctx).strip()

        results.append({
            'url': href,
            'domain': base_domain,
            'title': link_text[:200],
            'description': plain_ctx[:300],
            'price': price_m.group(0).strip(),
            'model_number': _extract_model(plain_ctx),
        })
        if len(results) >= 25:
            break

    return results


async def _search_competitor_site(
    domain: str,
    query: str,
    max_results: int = 10,
) -> List[Dict[str, Any]]:
    """Try common search URL patterns against a competitor site and return product hits."""
    q = quote_plus(query)
    base = f'https://{domain}'

    for pattern in _SITE_SEARCH_PATTERNS:
        url = base + pattern.format(q=q)
        try:
            html = await _curl_get(url, timeout=10)
        except Exception:
            continue
        if not html or len(html) < 300:
            continue
        if not _PRICE_RE.search(html):
            continue
        results = _parse_site_search_results(html, domain)
        if results:
            logger.debug("Site search: %s query=%r → %d hits via %s",
                         domain, query[:40], len(results), pattern)
            return results[:max_results]

    return []


def fuzzy_score(candidate_title: str, candidate_desc: str, target: str) -> int:
    """Return 0–100 fuzzy match score of a candidate product against the target string."""
    from rapidfuzz import fuzz
    combined = f"{candidate_title} {candidate_desc}".strip()
    if not combined or not target:
        return 0
    return int(fuzz.token_set_ratio(combined.lower(), target.lower()))


async def _enrich_prices(results: List[Dict[str, Any]], concurrency: int = 8) -> List[Dict[str, Any]]:
    """For results that have no price, attempt a lightweight page fetch to find one."""
    sem = asyncio.Semaphore(concurrency)

    async def _try(item: Dict) -> Dict:
        if item.get('price'):
            return item
        async with sem:
            try:
                html = await _curl_get(item['url'], timeout=6)
                if html:
                    price = _extract_price(html[:15000])
                    if price:
                        return {**item, 'price': price}
            except Exception:
                pass
        return item

    enriched = await asyncio.gather(*[_try(r) for r in results], return_exceptions=True)
    return [r if not isinstance(r, Exception) else orig
            for r, orig in zip(enriched, results)]


async def multi_engine_search(
    query: str,
    max_results: int = 20,
    exclude_domains: Optional[set] = None,
    engines: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Search across DuckDuckGo, Bing, Google, Yahoo, and Google Shopping concurrently.

    Google Shopping results are always included first and are URL-deduplicated (so
    multiple products from the same seller are all captured). Organic results from the
    other engines fill remaining slots up to max_results, domain-deduplicated and
    ranked by cross-engine agreement.
    """
    if engines is None:
        engines = ['ddg', 'bing', 'google', 'yahoo', 'shopping', 'bing_shopping', 'yahoo_shopping', 'ddg_shopping']
    exclude = exclude_domains or set()
    fetch = max_results * 3  # over-fetch to account for filtering

    # Build tasks; track which indices are shopping sources.
    tasks: List = []
    shopping_indices: List[int] = []
    if 'ddg' in engines:
        tasks.append(_text_search(query, max_results=fetch))
    if 'bing' in engines:
        tasks.append(_bing_search(query, max_results=fetch))
    if 'google' in engines:
        tasks.append(_google_search(query, max_results=fetch))
    if 'yahoo' in engines:
        tasks.append(_yahoo_search(query, max_results=fetch))
    if 'shopping' in engines:
        shopping_indices.append(len(tasks))
        tasks.append(_google_shopping_search(query, max_results=fetch))
    if 'bing_shopping' in engines:
        shopping_indices.append(len(tasks))
        tasks.append(_bing_shopping_search(query, max_results=fetch))
    if 'yahoo_shopping' in engines:
        shopping_indices.append(len(tasks))
        tasks.append(_yahoo_shopping_search(query, max_results=fetch))
    if 'ddg_shopping' in engines:
        shopping_indices.append(len(tasks))
        tasks.append(_duckduckgo_shopping_search(query, max_results=fetch))

    raw = await asyncio.gather(*tasks, return_exceptions=True)

    # --- Pass 1: collect all Shopping results (URL-keyed, multiple per domain allowed) ---
    shopping_results: List[Dict[str, Any]] = []
    seen_shopping_urls: set = set()
    for sidx in shopping_indices:
        if isinstance(raw[sidx], Exception):
            continue
        for item in (raw[sidx] or []):
            url = item.get('href', '') or item.get('url', '')
            if not url or _is_homepage(url) or url in seen_shopping_urls:
                continue
            domain = _domain(url)
            if not domain or domain in exclude or domain in _NOISE_DOMAINS:
                continue
            seen_shopping_urls.add(url)
            shopping_results.append({
                'href': url, 'url': url, 'domain': domain,
                'title': item.get('title', ''),
                'body': item.get('body', '') or item.get('description', ''),
                'price': item.get('price'),
            })

    # --- Pass 2: score organic results at domain level, skip URLs already in Shopping ---
    domain_score: Dict[str, int] = {}
    domain_best: Dict[str, Dict] = {}
    organic_indices = [i for i in range(len(tasks)) if i not in shopping_indices]

    for i in organic_indices:
        engine_results = raw[i]
        if isinstance(engine_results, Exception):
            continue
        for item in (engine_results or []):
            url = item.get('href', '') or item.get('url', '')
            if not url or _is_homepage(url) or url in seen_shopping_urls:
                continue
            domain = _domain(url)
            if not domain or domain in exclude or domain in _NOISE_DOMAINS:
                continue
            domain_score[domain] = domain_score.get(domain, 0) + 1
            entry = {
                'href': url, 'url': url, 'domain': domain,
                'title': item.get('title', ''),
                'body': item.get('body', '') or item.get('description', ''),
                'price': item.get('price'),
            }
            cur = domain_best.get(domain)
            if cur is None:
                domain_best[domain] = entry
            else:
                if not cur['title'] and entry['title']:
                    cur['title'] = entry['title']
                if not cur['body'] and entry['body']:
                    cur['body'] = entry['body']
                if not cur['price'] and entry['price']:
                    cur['price'] = entry['price']

    ranked_organic = sorted(domain_score.keys(), key=lambda d: -domain_score[d])
    # Shopping results first (have embedded prices), organic fills remaining slots.
    organic_slots = max(0, max_results - len(shopping_results))
    return shopping_results + [domain_best[d] for d in ranked_organic[:organic_slots]]


def _aggregate_and_rank(
    all_raw: list,
    img_idx: Dict[str, str],
    max_results: int,
    exclude_fn=None,
) -> List[Dict[str, Any]]:
    """Shared result aggregation for find_products / find_suppliers.

    Merges results from multiple concurrent engine calls, scores by cross-engine
    agreement (shopping results weighted 2×), deduplicates by domain, and returns
    up to max_results enriched result dicts.
    """
    domain_score: Dict[str, int] = {}
    domain_best: Dict[str, Dict] = {}

    for engine_results in all_raw:
        if isinstance(engine_results, Exception):
            continue
        for item in (engine_results or []):
            url = item.get('href', '') or item.get('url', '')
            if not url or _is_homepage(url):
                continue
            domain = _domain(url)
            if not domain or domain in _NOISE_DOMAINS:
                continue
            if exclude_fn and exclude_fn(domain):
                continue
            is_shopping = item.get('source') == 'shopping'
            domain_score[domain] = domain_score.get(domain, 0) + (2 if is_shopping else 1)
            entry = {
                'url': url, 'domain': domain,
                'title': item.get('title', ''),
                'body': item.get('body', '') or item.get('description', ''),
                'price': item.get('price'),
            }
            cur = domain_best.get(domain)
            if cur is None:
                domain_best[domain] = entry
            else:
                if not cur['title'] and entry['title']:
                    cur['title'] = entry['title']
                    cur['url'] = url
                if not cur['body'] and entry['body']:
                    cur['body'] = entry['body']
                if not cur['price'] and entry['price']:
                    cur['price'] = entry['price']

    ranked = sorted(domain_score.keys(), key=lambda d: -domain_score[d])
    out: List[Dict] = []
    for domain in ranked:
        item = domain_best[domain]
        snippet = item.get('body', '') or ''
        out.append({
            'url': item['url'],
            'domain': domain,
            'title': item.get('title', ''),
            'description': snippet,
            'price': item.get('price') or _extract_price(snippet),
            'model_number': _extract_model(snippet),
            'image': img_idx.get(domain, ''),
        })
        if len(out) >= max_results:
            break
    return out


async def find_products(
    product_name: str,
    model_number: Optional[str] = None,
    category: Optional[str] = None,
    competitor_model_map: Optional[Dict[str, set]] = None,
    exclude_own_domains: Optional[set] = None,
    max_results: int = 5,
) -> List[Dict[str, Any]]:
    """
    Search the web for products using multiple targeted queries.

    Runs three independent searches — buy <name>, buy <model>, buy <category> —
    plus Google Shopping for each, then merges by engine-agreement score.

    competitor_model_map: {domain: {model_numbers already tracked}} — a competitor
    domain is excluded only when the specific model_number being searched is already
    present in its tracked set. Pass None to exclude no competitors.
    """
    own = exclude_own_domains or set()

    def _should_exclude(domain: str) -> bool:
        if domain in own:
            return True
        if model_number and competitor_model_map:
            tracked = competitor_model_map.get(domain, set())
            if any(model_number.lower() == m.lower() for m in tracked):
                return True
        return False

    # Build per-query tasks: text search + shopping search for each query variant
    search_tasks: List[Any] = []
    search_tasks.append(multi_engine_search(
        f"buy {product_name}", max_results=max_results * 4,
        engines=['ddg', 'bing', 'google', 'yahoo'],
    ))
    search_tasks.append(_google_shopping_search(f"buy {product_name}", max_results=max_results * 3))

    if model_number:
        search_tasks.append(multi_engine_search(
            f"buy {product_name} {model_number}", max_results=max_results * 3,
            engines=['bing', 'google', 'yahoo'],
        ))
        search_tasks.append(_google_shopping_search(f"buy {model_number}", max_results=max_results * 2))

    if category:
        search_tasks.append(multi_engine_search(
            f"buy {category}", max_results=max_results * 3,
            engines=['ddg', 'bing', 'google', 'yahoo'],
        ))
        search_tasks.append(_google_shopping_search(f"buy {category}", max_results=max_results * 2))

    img_query = f"buy {product_name}"
    all_raw, images = await asyncio.gather(
        asyncio.gather(*search_tasks, return_exceptions=True),
        _image_search(img_query, max_results=max_results * 2),
    )
    img_idx = _img_index(images) if isinstance(images, list) else {}

    pre_enrich = _aggregate_and_rank(all_raw, img_idx, max_results, exclude_fn=_should_exclude)
    return await _enrich_prices(pre_enrich)


async def find_suppliers(
    description: str,
    model_number: Optional[str] = None,
    category: Optional[str] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    characteristics: Optional[Dict] = None,
    max_results: int = 10,
    pattern_queries: Optional[List[Tuple[str, str]]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Find alternate suppliers using pattern-based title queries.

    pattern_queries is an ordered list of (pattern_id, query_text) produced by
    pattern_learner.generate_queries().  Each pattern runs its own concurrent
    search; all results are fuzzy-scored against the original description,
    deduplicated by domain, sorted best-first, and filtered to >=30%.

    Returns (results, per_pattern_best_fuzzy) where per_pattern_best_fuzzy maps
    each pattern_id to the highest fuzzy score any of its results achieved.
    """
    from rapidfuzz import fuzz as _fuzz

    char_parts: List[str] = [str(v) for v in (characteristics or {}).values() if v]
    price_hint = f"under ${price_max:.0f}" if price_max else (f"over ${price_min:.0f}" if price_min else '')

    if not pattern_queries:
        pattern_queries = [("full", description)]

    # Build all search tasks; track which pattern each task belongs to.
    all_tasks: List[Any] = []
    task_pids: List[str] = []   # parallel list: pattern_id per task slot

    for pid, query in pattern_queries:
        base = ' '.join(filter(None, [query] + char_parts + [price_hint]))
        all_tasks.append(multi_engine_search(
            f"buy {base} supplier wholesale price", max_results=max_results * 2,
            engines=['ddg', 'bing', 'google', 'yahoo'],
        ))
        task_pids.append(pid)
        all_tasks.append(_google_shopping_search(f"buy {base}", max_results=max_results))
        task_pids.append(pid)

    # Supplemental searches on model/category (no pattern attribution).
    supp_start = len(all_tasks)
    if model_number:
        all_tasks.append(multi_engine_search(
            f"buy {model_number} {price_hint}".strip(), max_results=max_results * 2,
            engines=['bing', 'google', 'yahoo'],
        ))
        all_tasks.append(_google_shopping_search(f"buy {model_number}", max_results=max_results))
    if category:
        all_tasks.append(multi_engine_search(
            f"buy {category} wholesale {price_hint}".strip(), max_results=max_results * 2,
            engines=['ddg', 'bing', 'google', 'yahoo'],
        ))

    all_raw, images = await asyncio.gather(
        asyncio.gather(*all_tasks, return_exceptions=True),
        _image_search(f"buy {description}", max_results=max_results),
    )
    img_idx = _img_index(images) if isinstance(images, list) else {}

    # Group task results back by pattern.
    pattern_raw: Dict[str, List] = {pid: [] for pid, _ in pattern_queries}
    for i, raw in enumerate(all_raw[:supp_start]):
        pattern_raw[task_pids[i]].append(raw)
    supp_raw = list(all_raw[supp_start:])

    # Score every result with fuzzy match; dedup by domain keeping best score.
    domain_best: Dict[str, Dict] = {}
    per_pattern_best: Dict[str, int] = {pid: 0 for pid, _ in pattern_queries}

    def _score_and_merge(result: Dict, pid: str) -> None:
        score = fuzzy_score(result.get('title', ''), result.get('description', ''), description)
        result['fuzzy_score'] = score
        result['pattern_id'] = pid
        if score > per_pattern_best.get(pid, 0):
            per_pattern_best[pid] = score
        domain = result['domain']
        if domain not in domain_best or score > domain_best[domain].get('fuzzy_score', 0):
            domain_best[domain] = result

    for pid, raw in pattern_raw.items():
        if not raw or all(isinstance(r, Exception) for r in raw):
            continue
        for result in _aggregate_and_rank(raw, img_idx, max_results * 5):
            _score_and_merge(result, pid)

    if supp_raw and not all(isinstance(r, Exception) for r in supp_raw):
        for result in _aggregate_and_rank(supp_raw, img_idx, max_results * 3):
            _score_and_merge(result, 'supplemental')

    # Sort by fuzzy score, filter <30%, cap at max_results, then enrich prices.
    ranked = sorted(domain_best.values(), key=lambda r: -(r.get('fuzzy_score') or 0))
    filtered = [r for r in ranked if (r.get('fuzzy_score') or 0) >= 30]
    results = await _enrich_prices(filtered[:max_results])
    return results, per_pattern_best


async def search_competitor_websites(
    product_name: str,
    model_number: Optional[str],
    category: Optional[str],
    competitor_domains: List[str],
    max_results_per_competitor: int = 5,
    min_fuzzy_score: int = 0,
) -> List[Dict[str, Any]]:
    """
    Search each competitor's own site for the target product.

    For each competitor, tries queries in this order:
      1. product_name  (without "buy")
      2. model_number  (if provided)
      3. category      (if provided)

    Each result is scored 0–100 against the target using fuzzy token matching.
    Results below min_fuzzy_score are filtered out.
    Returns a flat list sorted by fuzzy_score descending.
    """
    target = ' '.join(filter(None, [model_number, product_name]))
    queries = list(filter(None, [product_name, model_number, category]))

    _sem = asyncio.Semaphore(5)

    async def _search_one(domain: str) -> List[Dict[str, Any]]:
        async with _sem:
            seen_urls: set = set()
            collected: List[Dict] = []
            for query in queries:
                try:
                    items = await _search_competitor_site(domain, query, max_results=15)
                    for item in items:
                        url = item.get('url', '')
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            score = fuzzy_score(
                                item.get('title', ''), item.get('description', ''), target
                            )
                            collected.append({**item, 'fuzzy_score': score, 'source_query': query})
                except Exception:
                    pass

            collected.sort(key=lambda x: -x['fuzzy_score'])
            if min_fuzzy_score > 0:
                collected = [x for x in collected if x['fuzzy_score'] >= min_fuzzy_score]
            return collected[:max_results_per_competitor]

    raw = await asyncio.gather(*[_search_one(d) for d in competitor_domains],
                               return_exceptions=True)

    flat: List[Dict] = []
    for domain, chunk in zip(competitor_domains, raw):
        if isinstance(chunk, Exception):
            continue
        for item in chunk:
            flat.append({**item, 'competitor_domain': domain})

    flat.sort(key=lambda x: -x.get('fuzzy_score', 0))
    return flat


async def find_customers(
    business_type: Optional[str] = None,
    location: Optional[str] = None,
    radius_miles: Optional[int] = None,
    keywords: Optional[List[str]] = None,
    exclude_websites: Optional[List[str]] = None,
    exclude_names: Optional[List[str]] = None,
    max_results: int = 20,
) -> List[Dict[str, Any]]:
    """Search for potential customers matching the given profile."""
    parts: List[str] = []
    if business_type:
        parts.append(business_type)
    if location:
        loc_str = f"near {location}" if not radius_miles else f"within {radius_miles} miles of {location}"
        parts.append(loc_str)
    if keywords:
        parts.extend(keywords)
    parts.append("business phone address")
    query = ' '.join(parts)

    # Build domain exclusion set
    exclude_domains: set = set()
    for entry in (exclude_websites or []):
        entry = entry.strip().lower().lstrip('https://').lstrip('http://').lstrip('www.').split('/')[0]
        if entry:
            exclude_domains.add(entry)

    exclude_name_terms = [n.strip().lower() for n in (exclude_names or []) if n.strip()]

    texts = await multi_engine_search(query, max_results=max_results * 3, exclude_domains=exclude_domains)

    # Post-filter by excluded names
    if exclude_name_terms:
        def _name_excluded(item: Dict) -> bool:
            haystack = (item.get('title', '') + ' ' + item.get('body', '')).lower()
            return any(term in haystack for term in exclude_name_terms)
        texts = [t for t in texts if not _name_excluded(t)]

    # Deduplicate and cap the fetch batch
    seen: set = set()
    candidates = []
    for item in texts:
        url = item.get('href', '') or item.get('url', '')
        domain = _domain(url)
        if not domain or domain in seen:
            continue
        seen.add(domain)
        candidates.append(item)
        if len(candidates) >= max_results * 2:
            break

    # Geocode search center (once) if radius filtering is needed
    center_coords: Optional[Tuple[float, float]] = None
    if location and radius_miles:
        center_coords = await _geocode(location)

    # Fetch NAP (name/address/phone) from each candidate's homepage in parallel
    fetch_urls = [c.get('href', '') or c.get('url', '') for c in candidates]
    nap_list = await asyncio.gather(*[_fetch_nap(u) for u in fetch_urls], return_exceptions=True)

    # Geocode addresses in parallel (best-effort; failures = no radius check for that result)
    addr_coords: List[Optional[Tuple[float, float]]] = [None] * len(candidates)
    if center_coords and radius_miles:
        async def _geocode_idx(i: int, addr: str) -> None:
            if addr:
                coords = await _geocode(addr)
                addr_coords[i] = coords

        await asyncio.gather(*[
            _geocode_idx(i, (nap_list[i] if not isinstance(nap_list[i], Exception) else {}).get('address', ''))  # type: ignore[union-attr]
            for i in range(len(candidates))
        ])

    results: List[Dict] = []
    for i, item in enumerate(candidates):
        url = item.get('href', '') or item.get('url', '')
        domain = _domain(url)
        nap = nap_list[i] if i < len(nap_list) and not isinstance(nap_list[i], Exception) else {}
        snippet = item.get('body', '') or item.get('description', '')

        phone = nap.get('phone', '') or _extract_phone(snippet)  # type: ignore[union-attr]
        address = nap.get('address', '')  # type: ignore[union-attr]
        name = nap.get('name', '') or item.get('title', '')  # type: ignore[union-attr]

        # Radius filter: exclude if we geocoded an address and it's outside the radius
        if center_coords and radius_miles and addr_coords[i]:
            dist = _haversine_miles(center_coords[0], center_coords[1], addr_coords[i][0], addr_coords[i][1])  # type: ignore[index]
            if dist > radius_miles:
                continue

        results.append({
            'url': url,
            'domain': domain,
            'name': name,
            'description': snippet,
            'phone': phone,
            'address': address,
        })
        if len(results) >= max_results:
            break

    return results
