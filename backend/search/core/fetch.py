"""
HTTP fetch plumbing for the search core.

`_curl_get` uses primp browser impersonation (curl-equivalent TLS fingerprinting)
but keeps the URL in-process so it is not visible in the process table. This is
the single fetch primitive every engine adapter and page module should use.
"""
import asyncio
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


async def _run_sync(fn):
    return await asyncio.get_event_loop().run_in_executor(None, fn)


# Transient fetch failures are retried with short backoff. On this deployment the
# outbound network (VPN/egress) flaps intermittently, and without retries a single
# blip makes every search engine return [] — surfacing as a misleading "0 found".
_FETCH_RETRIES = 3
_FETCH_BACKOFF_BASE = 0.4  # seconds: 0.4, 0.8


async def _curl_get(url: str, extra_headers: Optional[List[str]] = None, timeout: int = 15) -> str:
    """Fetch a URL via primp browser impersonation — same TLS fingerprinting as curl, but URL stays
    in-process memory and is not visible in the process table (ps/top).

    Retries transient connection failures a few times before giving up (returns '').
    HTTP error *statuses* return their body normally — only thrown exceptions retry.
    """
    import primp
    headers = {
        'Accept': 'text/html,application/xhtml+xml,*/*;q=0.9',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    for h in (extra_headers or []):
        if ': ' in h:
            k, v = h.split(': ', 1)
            headers[k] = v
    last_exc: Optional[BaseException] = None
    for attempt in range(_FETCH_RETRIES):
        try:
            async with primp.AsyncClient(impersonate='random', timeout=timeout) as client:
                r = await asyncio.wait_for(client.get(url, headers=headers), timeout + 2)
                return r.text
        except Exception as exc:
            last_exc = exc
            if attempt + 1 < _FETCH_RETRIES:
                await asyncio.sleep(_FETCH_BACKOFF_BASE * (2 ** attempt))
    logger.debug("primp_get failed for %s after %d attempts: %s", url, _FETCH_RETRIES, last_exc)
    return ''
