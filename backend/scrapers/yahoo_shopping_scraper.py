"""
Yahoo Shopping scraper — extracts Product Listing Ads (PLAs)
from Yahoo Search results pages.
"""
import base64
import logging
import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from playwright.async_api import async_playwright

from backend.config import config

logger = logging.getLogger(__name__)

YAHOO_SEARCH_URL = 'https://search.yahoo.com/search'


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
    """Extract the actual retailer URL from Yahoo/bizrate tracking links."""
    if not href or href.startswith('javascript'):
        return ''
    parsed = urlparse(href)
    qs = parse_qs(parsed.query)

    # bizrate redirect: b= holds the actual URL (URL-encoded)
    if 'bizrate.com' in parsed.netloc:
        b_vals = qs.get('b', [])
        if b_vals:
            return unquote(b_vals[0])

    # Yahoo tracking with base64-encoded url= param
    url_vals = qs.get('url', [])
    if url_vals:
        raw = url_vals[0]
        try:
            decoded = base64.b64decode(raw + '==').decode('utf-8', errors='ignore')
            if decoded.startswith('http'):
                return decoded
        except Exception:
            pass
        decoded = unquote(raw)
        if decoded.startswith('http'):
            return decoded

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


async def scrape_yahoo_shopping(
    query: str,
    max_results: int = 30,
) -> List[YahooPLAResult]:
    """Load Yahoo search for *query* and return all PLA product cards found."""
    results: List[YahooPLAResult] = []

    active = config.get('browser', 'default_profile', default='chrome_mac')
    profiles = config.get('browser', 'profiles', default={})
    profile = profiles.get(active, {})
    engine_name = profile.get('engine', 'chromium')
    user_agent = profile.get(
        'user_agent',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    )
    headless: bool = config.get('scraping', 'headless', default=True)

    search_url = f'{YAHOO_SEARCH_URL}?p={query.replace(" ", "+")}&fr=yfp-t'
    logger.info('Yahoo Shopping: %s', search_url)

    async with async_playwright() as pw:
        engine = {'chromium': pw.chromium, 'firefox': pw.firefox, 'webkit': pw.webkit}.get(
            engine_name, pw.chromium
        )
        browser = await engine.launch(headless=headless)
        ctx = await browser.new_context(
            user_agent=user_agent,
            viewport={'width': 1280, 'height': 800},
        )
        page = await ctx.new_page()

        try:
            await page.goto(search_url, wait_until='domcontentloaded', timeout=30_000)
            await page.wait_for_selector('li.plaItem', timeout=10_000)
        except Exception:
            logger.warning('No Yahoo PLAs found for query: %r', query)
            await browser.close()
            return results

        items = await page.query_selector_all('li.plaItem')
        logger.info('Yahoo PLAs: %d items for %r', len(items), query)

        for item in items[:max_results]:
            try:
                link_el = await item.query_selector('a.td-hn')
                href = await link_el.get_attribute('href') if link_el else ''
                url = _resolve_url(href or '')
                if not url:
                    continue

                domain = _extract_domain(url)
                if not domain:
                    continue

                title_el = await item.query_selector('.fc-refblack span, .mh-48 span')
                title = (await title_el.inner_text()).strip() if title_el else ''
                if not title:
                    continue

                price_el = await item.query_selector('.current-price')
                price_raw_text = (await price_el.inner_text()).strip() if price_el else ''
                price, price_raw = _parse_price(price_raw_text)

                seller_el = await item.query_selector('.seller')
                merchant = (await seller_el.inner_text()).strip() if seller_el else domain

                img_el = await item.query_selector('img.s-img')
                image_url = await img_el.get_attribute('src') if img_el else None

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

        await browser.close()

    logger.info('Yahoo PLAs: extracted %d results for %r', len(results), query)
    return results
