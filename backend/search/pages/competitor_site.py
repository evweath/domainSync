"""
Competitors page — search each known competitor's own website for a target product.

Page-specific orchestration: per-competitor query ordering, fuzzy scoring against
the target, and flattening results across competitors. The site-search mechanics
live in core/engines.py.
"""
import asyncio
from typing import Any, Dict, List, Optional

from backend.search.core.engines import _search_competitor_site
from backend.search.core.rank import fuzzy_score


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
