"""Regression tests for the 2026-08-07 Windows log findings:

1. Shopify 429s must be retried with backoff, not silently truncate the catalog.
2. A rate-limited (partial) fetch must NOT archive unseen products — the
   products not seen are still live on the store.
"""
import pytest

from backend.scrapers import shopify_scraper
from backend.scrapers.shopify_scraper import scrape_shopify_store


def _mk_item(pid: int) -> dict:
    return {
        "id": pid,
        "handle": f"p-{pid}",
        "title": f"Product {pid}",
        "variants": [{"id": pid * 10, "price": "9.99", "sku": f"SKU-{pid}", "available": True}],
        "images": [],
        "options": [],
    }


class _Resp:
    def __init__(self, status_code=200, products=None, retry_after=None):
        self.status_code = status_code
        self._products = products or []
        self.headers = {}
        if retry_after is not None:
            self.headers["Retry-After"] = str(retry_after)

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("err", request=None, response=None)

    def json(self):
        return {"products": self._products}


class _FakeClient:
    """Async context manager mimicking httpx.AsyncClient with scripted responses."""

    def __init__(self, responses):
        self._responses = list(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        assert self._responses, f"unexpected extra request: {url}"
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.mark.asyncio
async def test_429_is_retried_and_recovers(monkeypatch):
    """429 → waits → retries same page → catalog completes, not truncated."""
    monkeypatch.setattr(shopify_scraper.httpx, "AsyncClient",
                        lambda **kw: _FakeClient([
                            _Resp(429, retry_after=0),            # page 1, attempt 1
                            _Resp(products=[_mk_item(1)]),        # page 1 retry OK (<250 → done)
                        ]))
    monkeypatch.setattr(shopify_scraper.asyncio, "sleep", _no_sleep)

    products, rate_limited = await scrape_shopify_store("https://x.myshopify.com", "x")
    assert rate_limited is False
    assert len(products) == 1


@pytest.mark.asyncio
async def test_429_persistent_marks_partial(monkeypatch):
    """Exhausted retries → rate_limited=True so caller knows it's truncated."""
    responses = [_Resp(429, retry_after=0)] * 6  # 1 try + 5 retries, all 429
    monkeypatch.setattr(shopify_scraper.httpx, "AsyncClient",
                        lambda **kw: _FakeClient(responses))
    monkeypatch.setattr(shopify_scraper.asyncio, "sleep", _no_sleep)

    products, rate_limited = await scrape_shopify_store("https://x.myshopify.com", "x")
    assert rate_limited is True
    assert products == []


async def _no_sleep(_seconds):
    return None


def test_partial_scan_skips_archiving():
    """run_site must not call _archive_unseen_for_site when rate_limited."""
    import inspect
    from backend.scrapers.source_scraper import SourceScraper
    src = inspect.getsource(SourceScraper.run_site)
    # The archive call must be inside the else-branch of the rate_limited check
    assert "if rate_limited:" in src
    rate_idx = src.index("if rate_limited:")
    arch_idx = src.index("_archive_unseen_for_site(domain)")
    assert rate_idx < arch_idx, "archive guard must come before the archive call"
    assert "else:" in src[rate_idx:arch_idx]
