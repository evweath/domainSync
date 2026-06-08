"""
Find Me Customers page — find local potential customers by business type + location.

Page-specific: NAP (name/address/phone) extraction from schema.org markup and
geocoding/radius filtering live here because only this page needs them. Web search
goes through core/rank.multi_engine_search.
"""
import asyncio
import json
import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from backend.search.core.fetch import _curl_get
from backend.search.core.parse import _domain
from backend.search.core.rank import multi_engine_search

logger = logging.getLogger(__name__)

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
