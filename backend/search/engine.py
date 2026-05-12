"""
Web search engine for Find This Product, Beat This Price, Find Me Customers,
and web-search-first competitor scanning.
Supports DuckDuckGo, Bing, Google, and Yahoo — no API keys required.
"""
import asyncio
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, unquote, quote_plus

logger = logging.getLogger(__name__)

_PRICE_RE = re.compile(r'\$\s*[\d,]+(?:\.\d{1,2})?')
_MODEL_RE = re.compile(
    r'(?:model|model\s*#|model\s*no|part\s*#|sku|item\s*#)[:\s#]+([A-Z0-9][\w\-/]{2,})', re.I
)


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lstrip('www.')
    except Exception:
        return ''


def _extract_price(text: str) -> Optional[str]:
    m = _PRICE_RE.search(text or '')
    return m.group(0).strip() if m else None


def _extract_model(text: str) -> Optional[str]:
    m = _MODEL_RE.search(text or '')
    return m.group(1).strip() if m else None


async def _run_sync(fn):
    return await asyncio.get_event_loop().run_in_executor(None, fn)


async def _curl_get(url: str, extra_headers: Optional[List[str]] = None, timeout: int = 15) -> str:
    """Fetch a URL via subprocess curl — bypasses Python TLS fingerprint filtering."""
    cmd = [
        'curl', '-s', '-L',
        '--max-time', str(timeout),
        '--compressed',
        '-A', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15',
        '-H', 'Accept: text/html,application/xhtml+xml,*/*;q=0.9',
        '-H', 'Accept-Language: en-US,en;q=0.9',
    ]
    for h in (extra_headers or []):
        cmd += ['-H', h]
    cmd.append(url)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout + 2)
        return stdout.decode('utf-8', errors='replace')
    except Exception as exc:
        logger.debug("curl_get failed for %s: %s", url, exc)
        return ''


async def _text_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    def _search():
        from ddgs import DDGS
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results, backend='duckduckgo'))
    try:
        return await _run_sync(_search)
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


def _cite_to_url(cite_html: str) -> str:
    """Convert a Bing display URL (with › separators) into a real URL."""
    text = re.sub(r'<[^>]+>', '', cite_html).strip()
    text = text.replace(' › ', '/').replace('› ', '/').replace(' ›', '/')
    if not text.startswith('http'):
        text = 'https://' + text
    return text


async def _bing_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Scrape Bing SERP via curl and reconstruct URLs from cite display tags."""
    try:
        q = quote_plus(query)
        url = f"https://www.bing.com/search?q={q}&count={min(max_results * 2, 50)}&mkt=en-US&setlang=en-US&cc=US"
        html = await _curl_get(url)
        if not html:
            return []
        results = []
        seen: set = set()

        # Extract (h2-title, cite-url) pairs from b_algo result blocks
        for block in re.finditer(r'class="b_algo[^"]*"(.*?)</li>', html, re.DOTALL):
            b = block.group(1)
            cite_m = re.search(r'<cite[^>]*>(.*?)</cite>', b, re.DOTALL)
            h2_m = re.search(r'<h2[^>]*>(.*?)</h2>', b, re.DOTALL)
            if not cite_m:
                continue
            href = _cite_to_url(cite_m.group(1))
            title = re.sub(r'<[^>]+>', '', h2_m.group(1)).strip() if h2_m else ''
            d = _domain(href)
            if not d or any(skip in d for skip in _BING_SKIP_DOMAINS):
                continue
            if d in seen:
                continue
            seen.add(d)
            results.append({'href': href, 'title': title, 'body': ''})
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
        # Yahoo encodes real URLs in RU=... query param
        for m in re.finditer(r'RU=(https?%3[Aa]%2[Ff]%2[Ff][^&"]+)', html):
            href = unquote(m.group(1))
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


async def multi_engine_search(
    query: str,
    max_results: int = 20,
    exclude_domains: Optional[set] = None,
    engines: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Search across DuckDuckGo, Bing, Google, Yahoo concurrently.
    Returns up to max_results unique results (by URL), ranked by engine agreement.
    """
    if engines is None:
        engines = ['ddg', 'bing', 'google', 'yahoo']
    exclude = exclude_domains or set()
    fetch = max_results * 3  # over-fetch to account for filtering

    tasks = []
    if 'ddg' in engines:
        # Serialize DDG calls with a small delay to avoid rate-limit bans
        async def _ddg_guarded():
            async with _DDG_SEARCH_LOCK:
                result = await _text_search(f"{query} buy", max_results=fetch)
                await asyncio.sleep(1.5)
                return result
        tasks.append(_ddg_guarded())
    if 'bing' in engines:
        tasks.append(_bing_search(query, max_results=fetch))
    if 'google' in engines:
        tasks.append(_google_search(query, max_results=fetch))
    if 'yahoo' in engines:
        tasks.append(_yahoo_search(query, max_results=fetch))

    raw = await asyncio.gather(*tasks, return_exceptions=True)

    url_score: Dict[str, int] = {}
    url_data: Dict[str, Dict] = {}

    for engine_results in raw:
        if isinstance(engine_results, Exception):
            continue
        for item in (engine_results or []):
            url = item.get('href', '') or item.get('url', '')
            if not url:
                continue
            domain = _domain(url)
            if not domain or domain in exclude:
                continue
            if url not in url_score:
                url_score[url] = 0
                url_data[url] = {
                    'href': url,
                    'url': url,
                    'domain': domain,
                    'title': item.get('title', ''),
                    'body': item.get('body', '') or item.get('description', ''),
                }
            url_score[url] += 1  # boost URLs appearing in multiple engines

    # Sort by engine agreement (higher score = more engines agree) then by insertion order
    ranked = sorted(url_score.keys(), key=lambda u: -url_score[u])
    return [url_data[u] for u in ranked[:max_results]]


async def find_products(
    query: str,
    exclude_domains: Optional[set] = None,
    max_results: int = 5,
) -> List[Dict[str, Any]]:
    """Search the web for products matching query; exclude known competitor domains."""
    product_query = f"{query} buy price"
    texts, images = await asyncio.gather(
        _text_search(product_query, max_results=max_results * 4),
        _image_search(product_query, max_results=max_results * 4),
    )
    img_idx = _img_index(images)
    exclude = exclude_domains or set()
    results: List[Dict] = []
    for item in texts:
        url = item.get('href', '')
        domain = _domain(url)
        if not domain or domain in exclude:
            continue
        snippet = item.get('body', '')
        results.append({
            'url': url,
            'domain': domain,
            'title': item.get('title', ''),
            'description': snippet,
            'price': _extract_price(snippet),
            'model_number': _extract_model(snippet),
            'image': img_idx.get(domain, ''),
        })
        if len(results) >= max_results:
            break
    return results


async def find_suppliers(
    description: str,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    characteristics: Optional[Dict] = None,
    max_results: int = 10,
) -> List[Dict[str, Any]]:
    """Find alternate suppliers and prices for a product description."""
    parts = [description]
    if price_max:
        parts.append(f"under ${price_max:.0f}")
    elif price_min:
        parts.append(f"over ${price_min:.0f}")
    if characteristics:
        for v in characteristics.values():
            if v:
                parts.append(str(v))
    parts.append("supplier wholesale price")
    query = ' '.join(parts)

    texts, images = await asyncio.gather(
        _text_search(query, max_results=max_results * 3),
        _image_search(query, max_results=max_results),
    )
    img_idx = _img_index(images)

    results: List[Dict] = []
    seen: set = set()
    for item in texts:
        url = item.get('href', '')
        domain = _domain(url)
        if not domain or domain in seen:
            continue
        seen.add(domain)
        snippet = item.get('body', '')
        results.append({
            'url': url,
            'domain': domain,
            'title': item.get('title', ''),
            'description': snippet,
            'price': _extract_price(snippet),
            'model_number': _extract_model(snippet),
            'image': img_idx.get(domain, ''),
        })
        if len(results) >= max_results:
            break
    return results


async def find_customers(
    business_type: Optional[str] = None,
    location: Optional[str] = None,
    radius_miles: Optional[int] = None,
    keywords: Optional[List[str]] = None,
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
    parts.append("business contact")
    query = ' '.join(parts)

    texts = await _text_search(query, max_results=max_results * 2)

    results: List[Dict] = []
    seen: set = set()
    for item in texts:
        url = item.get('href', '')
        domain = _domain(url)
        if not domain or domain in seen:
            continue
        seen.add(domain)
        results.append({
            'url': url,
            'domain': domain,
            'name': item.get('title', ''),
            'description': item.get('body', ''),
        })
        if len(results) >= max_results:
            break
    return results
