"""
Yahoo Shopping scraper — extracts Product Listing Ads (PLAs)
from Yahoo Search results pages using httpx + lxml.
"""
import base64
import logging
import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from lxml import html as lxml_html

from backend.config import config

logger = logging.getLogger(__name__)

YAHOO_SEARCH_URL = 'https://search.yahoo.com/search'
_DEFAULT_UA = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
)


@dataclass
class YahooPLAResult:
    title: str
    merchant: str
    merchant_domain: str
    url: str
    price: Optional[float]
    price_raw: Optional[str]
    image_url: Optional[str]
    in_stock: bool = True


def _resolve_url(href: str) -> str:
    """
    Extract the actual retailer URL from Yahoo/Bing tracking redirect chains.

    Yahoo PLAs use: r.search.yahoo.com/rdclks/.../RU=<url-encoded-bing-url>/...
    The Bing URL contains: u=<base64( url-encoded-actual-url )>
    Older ads use rd.bizrate.com with b=<url-encoded-actual-url>.
    """
    if not href or href.startswith('javascript'):
        return ''

    # Yahoo rdclks redirect: extract RU= path segment
    ru_match = re.search(r'/RU=([^/]+)/', href)
    if ru_match:
        intermediate = unquote(ru_match.group(1))
        # Bing aclick: u= parameter holds base64-encoded URL-encoded actual URL
        if 'bing.com/aclick' in intermediate or 'u=' in intermediate:
            qs = parse_qs(urlparse(intermediate).query)
            u_vals = qs.get('u', [])
            if u_vals:
                try:
                    b64 = u_vals[0]
                    padding = '=' * (4 - len(b64) % 4)
                    decoded = base64.b64decode(b64 + padding, validate=False).decode('utf-8', errors='ignore')
                    actual = unquote(decoded)
                    if actual.startswith('http'):
                        return actual
                except Exception:
                    pass
        # Fallback: return the intermediate URL if it looks real
        if intermediate.startswith('http'):
            return intermediate

    # Bizrate redirect: b= parameter holds URL-encoded actual URL
    parsed = urlparse(href)
    if 'bizrate.com' in parsed.netloc:
        qs = parse_qs(parsed.query)
        b_vals = qs.get('b', [])
        if b_vals:
            return unquote(b_vals[0])

    return href


def _extract_domain(url: str) -> str:
    if not url:
        return ''
    try:
        return urlparse(url).netloc.removeprefix('www.')
    except Exception:
        return ''


def _parse_price(text: str) -> tuple[Optional[float], Optional[str]]:
    if not text:
        return None, None
    raw = text.strip()
    m = re.search(r'[\d]+\.?\d*', raw.replace(',', ''))
    if m:
        try:
            return float(m.group()), raw
        except ValueError:
            pass
    return None, raw


def _user_agent() -> str:
    active = config.get('browser', 'default_profile', default='chrome_mac')
    profiles = config.get('browser', 'profiles', default={})
    return profiles.get(active, {}).get('user_agent', _DEFAULT_UA)


async def scrape_yahoo_shopping(
    query: str,
    max_results: int = 30,
) -> List[YahooPLAResult]:
    """Fetch Yahoo search for *query* and return all PLA product cards found."""
    results: List[YahooPLAResult] = []
    search_url = f'{YAHOO_SEARCH_URL}?p={query.replace(" ", "+")}&fr=yfp-t'
    logger.info('Yahoo Shopping: %s', search_url)

    headers = {
        'User-Agent': _user_agent(),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }

    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=20) as client:
        try:
            resp = await client.get(search_url)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning('Yahoo Shopping fetch failed for %r: %s', query, exc)
            return results

    doc = lxml_html.fromstring(resp.text)
    items = doc.xpath('//li[contains(@class,"plaItem")]')
    logger.info('Yahoo PLAs: %d items for %r', len(items), query)

    for item in items[:max_results]:
        try:
            anchors = item.xpath('.//a[contains(@class,"td-hn")]')
            if not anchors:
                continue
            href = anchors[0].get('href', '')
            url = _resolve_url(href)
            if not url:
                continue

            domain = _extract_domain(url)
            if not domain:
                continue

            title_spans = item.xpath('.//div[contains(@class,"fc-refblack")]//span')
            title = title_spans[0].text_content().strip() if title_spans else ''
            if not title:
                continue

            price_divs = item.xpath('.//div[contains(@class,"current-price")]')
            price_text = price_divs[0].text_content().strip() if price_divs else ''
            price, price_raw = _parse_price(price_text)

            seller_divs = item.xpath('.//div[contains(@class,"seller")]')
            merchant = seller_divs[0].text_content().strip() if seller_divs else domain

            imgs = item.xpath('.//img[contains(@class,"s-img")]')
            image_url = imgs[0].get('src') if imgs else None

            results.append(YahooPLAResult(
                title=title,
                merchant=merchant,
                merchant_domain=domain,
                url=url,
                price=price,
                price_raw=price_raw,
                image_url=image_url,
            ))

        except Exception as exc:
            logger.debug('Failed to parse PLA item: %s', exc)
            continue

    logger.info('Yahoo PLAs: extracted %d results for %r', len(results), query)
    return results
