"""
Yahoo Shopping scan — searches Yahoo PLAs for each master product
and stores results as competitor matches / price history.
"""
import asyncio
import json
import logging
import types as _types
from datetime import datetime
from typing import Callable, List, Optional

from sqlalchemy.orm import Session, joinedload

from backend.competitor.matcher import MatchCriteria, match_competitor_product
from backend.database.db import session_scope
from backend.database.models import (
    Competitor,
    CompetitorProductMatch,
    PriceHistory,
    Product,
)
from backend.scrapers.yahoo_shopping_scraper import YahooPLAResult, scrape_yahoo_shopping

logger = logging.getLogger(__name__)


def _excluded_domains() -> set[str]:
    """Build exclusion set from configured source sites."""
    from backend.config import config
    sites = config.get('source_sites', default=[]) or []
    return {s.get('domain', '') for s in sites if s.get('domain')}


def _build_query(product: _types.SimpleNamespace) -> str:
    if product.model_number:
        q = product.model_number
        if product.manufacturer:
            q = f'{product.manufacturer} {q}'
        return q
    return product.canonical_title


def _snap_master(p: Product) -> _types.SimpleNamespace:
    return _types.SimpleNamespace(
        id=p.id,
        model_number=p.model_number,
        sku=p.sku,
        manufacturer=p.manufacturer,
        canonical_title=p.canonical_title,
        price_canonical=p.price_canonical,
        images=[_types.SimpleNamespace(image_hash=img.image_hash) for img in (p.images or [])],
    )


def _get_or_create_competitor(db: Session, domain: str, merchant_name: str) -> int:
    comp = db.query(Competitor).filter(Competitor.domain == domain).first()
    if not comp:
        comp = Competitor(
            domain=domain,
            name=merchant_name,
            base_url=f'https://{domain}',
            scan_session_name='yahoo_shopping',
            first_scanned_at=datetime.utcnow(),
        )
        db.add(comp)
        db.flush()
        logger.info('New competitor via Yahoo PLAs: %s', domain)
    else:
        comp.last_scanned_at = datetime.utcnow()
    return comp.id


def _upsert_match(
    db: Session,
    master_product_id: int,
    competitor_id: int,
    pla: YahooPLAResult,
    confidence: float,
    match_types: List[str],
    match_reasons: dict,
) -> bool:
    """Upsert a CompetitorProductMatch; returns True if a new record was created."""
    existing = (
        db.query(CompetitorProductMatch)
        .filter(
            CompetitorProductMatch.master_product_id == master_product_id,
            CompetitorProductMatch.competitor_id == competitor_id,
            CompetitorProductMatch.competitor_url == pla.url,
        )
        .first()
    )

    if existing:
        if pla.price and existing.competitor_price != pla.price:
            existing.competitor_price = pla.price
            existing.scanned_at = datetime.utcnow()
            db.add(PriceHistory(match_id=existing.id, price=pla.price, in_stock=pla.in_stock))
        return False

    match = CompetitorProductMatch(
        master_product_id=master_product_id,
        competitor_id=competitor_id,
        competitor_url=pla.url,
        competitor_title=pla.title,
        competitor_price=pla.price,
        competitor_image_url=pla.image_url,
        match_type='|'.join(match_types),
        match_confidence=confidence,
        match_reasons_json=json.dumps(match_reasons),
        in_stock=pla.in_stock,
        scanned_at=datetime.utcnow(),
    )
    db.add(match)
    db.flush()
    if pla.price:
        db.add(PriceHistory(match_id=match.id, price=pla.price, in_stock=pla.in_stock))
    return True


async def run_yahoo_shopping_scan(
    product_id: Optional[int] = None,
    query: Optional[str] = None,
    criteria_dict: Optional[dict] = None,
    delay_between_queries: float = 3.0,
    max_pla_results: int = 30,
    progress_callbacks: Optional[List[Callable]] = None,
) -> dict:
    """
    Search Yahoo PLAs for master products and store results as competitor matches.

    product_id: scan only one product; omit to scan all active products.
    query: override the auto-built search query (useful with product_id).
    """
    callbacks = progress_callbacks or []

    async def emit(event: str, data: dict) -> None:
        for cb in callbacks:
            try:
                await cb(event, data)
            except Exception:
                pass

    criteria = MatchCriteria.from_dict(criteria_dict) if criteria_dict else MatchCriteria()
    excluded = _excluded_domains()

    with session_scope() as db:
        q = (
            db.query(Product)
            .options(joinedload(Product.images))
            .filter(Product.is_active == True)
        )
        if product_id:
            q = q.filter(Product.id == product_id)
        products = [_snap_master(p) for p in q.all()]

    if not products:
        logger.warning('No products found for Yahoo Shopping scan')
        return {'products_searched': 0, 'pla_results': 0, 'matches_found': 0}

    total_pla = 0
    total_matches = 0
    products_searched = 0

    for i, product in enumerate(products):
        search_query = query or _build_query(product)
        await emit('yahoo_scan_product', {'product_id': product.id, 'query': search_query})

        try:
            pla_results = await scrape_yahoo_shopping(search_query, max_results=max_pla_results)
        except Exception as exc:
            logger.warning('Yahoo search failed for %r: %s', search_query, exc)
            continue

        total_pla += len(pla_results)
        products_searched += 1

        with session_scope() as db:
            for pla in pla_results:
                if pla.merchant_domain in excluded:
                    continue

                comp_dict = {
                    'title': pla.title,
                    'price': pla.price,
                    'model_number': None,
                    'manufacturer': None,
                    'sku': None,
                    'description': None,
                    'image_hash': None,
                }

                match_result = match_competitor_product(comp_dict, [product], criteria)
                if match_result is None:
                    logger.debug(
                        'No match: %r → %r (product_id=%d)',
                        pla.title[:50], product.canonical_title[:50], product.id,
                    )
                    continue

                competitor_id = _get_or_create_competitor(db, pla.merchant_domain, pla.merchant)
                created = _upsert_match(
                    db=db,
                    master_product_id=match_result.master_product_id,
                    competitor_id=competitor_id,
                    pla=pla,
                    confidence=match_result.confidence,
                    match_types=match_result.match_types,
                    match_reasons=match_result.reasons,
                )
                if created:
                    total_matches += 1
                    price_str = f'${pla.price:.2f}' if pla.price else 'no price'
                    logger.info(
                        'Yahoo PLA match: domain=%s  product=%r  price=%s  confidence=%d%%',
                        pla.merchant_domain, pla.title[:60], price_str, int(match_result.confidence),
                    )

        await emit('yahoo_scan_product_done', {
            'product_id': product.id,
            'query': search_query,
            'pla_count': len(pla_results),
        })

        if delay_between_queries > 0 and i < len(products) - 1:
            await asyncio.sleep(delay_between_queries)

    logger.info(
        'Yahoo scan complete: %d searched, %d PLAs, %d new matches',
        products_searched, total_pla, total_matches,
    )
    return {
        'products_searched': products_searched,
        'pla_results': total_pla,
        'matches_found': total_matches,
    }
