"""
Find This Product page — search the web for buyable copies of a specific product.

Page-specific orchestration only: query construction, competitor/own-domain
exclusion, and result shaping. All engine work goes through core/.
"""
import asyncio
from typing import Any, Dict, List, Optional

from backend.search.core.engines import _google_shopping_search, _image_search
from backend.search.core.parse import _img_index
from backend.search.core.rank import _aggregate_and_rank, _enrich_prices, multi_engine_search


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
