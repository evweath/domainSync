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
