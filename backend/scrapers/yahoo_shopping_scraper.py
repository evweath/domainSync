"""
Yahoo Shopping scraper — extracts Product Listing Ads (PLAs)
from Yahoo Search results pages using curl + lxml.
"""
import asyncio
import base64
import logging
import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from lxml import html as lxml_html

from backend.config import config

logger = logging.getLogger(__name__)

YAHOO_SEARCH_URL = 'https://search.yahoo.com/search'
_DEFAULT_UA = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
)

# Domains that are ad trackers, redirect services, or price aggregators —
# never actual competitors with their own inventory.
_BLOCKED_DOMAINS: frozenset[str] = frozenset({
    # Ad / click trackers
    'ad.doubleclick.net',
    'clickserve.dartsearch.net',
    'monitor.clickcease.com',
    'tracking.deepsearch.adlucent.com',
    'tracking.voltagesearch.com',
    'trk2.genieshopping.com',
    # Redirect / affiliate services
    'rd.bizrate.com',
    'r.search.yahoo.com',
    'go.twenga.co.uk',
    # Price-aggregator middlemen
    'lowest-price.com',
    'us.redbrain.shop',
    'preis.info',
    'co.buycheapr.com',
    'dealdoo.com',
    'brilliantsave.com',
    'isaveit.com',
    'digitalbuyer.com',
})

# Domain-prefix patterns to block programmatically (in addition to the list above)
_BLOCKED_PREFIXES: tuple[str, ...] = ('tracking.', 'trk.', 'trk2.', 'click.', 'ad.')


def _is_blocked_domain(domain: str) -> bool:
    if domain in _BLOCKED_DOMAINS:
        return True
    return any(domain.startswith(p) for p in _BLOCKED_PREFIXES)


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


async def _follow_redirect(url: str) -> str:
    """Follow HTTP redirects via curl and return the final URL."""
    try:
        proc = await asyncio.create_subprocess_exec(
            'curl', '-s', '-L', '-o', '/dev/null',
            '-w', '%{url_effective}',
            '--max-redirs', '5',
            '--max-time', '10',
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        final = stdout.decode('utf-8', errors='replace').strip()
        return final if final.startswith('http') else url
    except Exception:
        return url


async def _resolve_url(href: str) -> str:
    """
    Extract the actual retailer URL from Yahoo/Bing tracking redirect chains.

    Yahoo PLAs use: r.search.yahoo.com/rdclks/.../RU=<url-encoded-bing-url>/...
    The Bing URL contains: u=<base64( url-encoded-actual-url )>
    Some bizrate ads include b=<url-encoded-actual-url>.
    Others require following the redirect to discover the final URL.
    """
    if not href or href.startswith('javascript'):
        return ''

    # Yahoo rdclks redirect: extract RU= path segment
    ru_match = re.search(r'/RU=([^/]+)/', href)
    if ru_match:
        intermediate = unquote(ru_match.group(1))
        # Bing aclick: u= holds base64-encoded URL-encoded actual URL
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
        if intermediate.startswith('http'):
            return intermediate

    # Bizrate with b= param: extract directly
    parsed = urlparse(href)
    if 'bizrate.com' in parsed.netloc:
        qs = parse_qs(parsed.query)
        b_vals = qs.get('b', [])
        if b_vals:
            return unquote(b_vals[0])
        # Bizrate without b= param: follow redirect to get actual URL
        return await _follow_redirect(href)

    return href


_TRACKING_PARAMS: frozenset[str] = frozenset({
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'msclkid', 'gclid', 'fbclid', 'ref', 'tag',
    'ma_campaign_id', 'ma_adgroup_id', 'cnxclid', 'trng', 'rlid',
})


def _clean_url(url: str) -> str:
    """Strip click-tracking query parameters so the same product URL deduplicates."""
    if not url:
        return url
    try:
        p = urlparse(url)
        qs = parse_qs(p.query, keep_blank_values=True)
        clean = {k: v for k, v in qs.items() if k.lower() not in _TRACKING_PARAMS}
        return p._replace(query=urlencode(clean, doseq=True)).geturl()
    except Exception:
        return url


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
    # Yahoo only serves PLAs to Chrome-identified clients.
    profiles = config.get('browser', 'profiles', default={})
    return profiles.get('chrome_mac', {}).get('user_agent') or _DEFAULT_UA


async def scrape_yahoo_shopping(
    query: str,
    max_results: int = 30,
) -> List[YahooPLAResult]:
    """Fetch Yahoo search for *query* and return all PLA product cards found."""
    results: List[YahooPLAResult] = []
    search_url = f'{YAHOO_SEARCH_URL}?p={query.replace(" ", "+")}&fr=yfp-t'
    logger.info('Yahoo Shopping: %s', search_url)

    ua = _user_agent()
    try:
        proc = await asyncio.create_subprocess_exec(
            'curl', '-s', '-L',
            '-A', ua,
            '-H', 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            '-H', 'Accept-Language: en-US,en;q=0.9',
            '--max-time', '20',
            search_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0 or not stdout:
            logger.warning('Yahoo Shopping curl failed for %r (exit %s)', query, proc.returncode)
            return results
        html_text = stdout.decode('utf-8', errors='replace')
    except Exception as exc:
        logger.warning('Yahoo Shopping fetch failed for %r: %s', query, exc)
        return results

    doc = lxml_html.fromstring(html_text)
    items = doc.xpath('//li[contains(@class,"plaItem")]')
    logger.info('Yahoo PLAs: %d items for %r', len(items), query)

    for item in items[:max_results]:
        try:
            anchors = item.xpath('.//a[contains(@class,"td-hn")]')
            if not anchors:
                continue
            href = anchors[0].get('href', '')
            url = _clean_url(await _resolve_url(href))
            if not url:
                continue

            domain = _extract_domain(url)
            if not domain or _is_blocked_domain(domain):
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
