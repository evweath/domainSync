"""
Force-merge products from secondary source sites into their best-matching
system-of-record (donut-equipment.com) counterpart.

SoR variant consolidation (Stage 4): every store's per-variant listing is merged
INTO the SoR product so a SKU becomes one shared Product with sources from every
store. Match precedence is SKU → model_number → title (fuzzy). SKU is the stable
cross-store key (handles differ per store; variant titles are shared within a
product, so title-fuzzy is restricted to titles that are UNIQUE among SoR
products to avoid merging into an arbitrary sibling variant).
"""
import json
import logging
from collections import Counter
from datetime import datetime
from typing import Callable, Optional

from rapidfuzz import fuzz, process as fuzz_process
from sqlalchemy.orm import Session, joinedload

from backend.database.db import session_scope
from backend.database.models import DuplicateCandidate, Product, ProductSource, ProductVersion
from backend.dedup.engine import DeduplicationEngine

logger = logging.getLogger(__name__)

_engine = DeduplicationEngine()

# Every store other than the system of record. The SoR (donut-equipment.com) is
# always the primary that stays active; every other store merges into it.
DEFAULT_SECONDARY_SITES = [
    'donut-equipment.myshopify.com',
    'DE3',
    'bakerywholesalers.com',
    'donut-supplies.com',
]


def _site_product_ids(db: Session, site: str) -> set[int]:
    return {
        r[0] for r in db.query(ProductSource.product_id)
        .filter(ProductSource.source_site == site, ProductSource.is_active == True)
        .all()
    }


def _active_product_ids(db: Session) -> set[int]:
    return {r[0] for r in db.query(Product.id).filter(Product.is_active == True).all()}


def _best_primary_match(
    sku: Optional[str],
    model: Optional[str],
    title: Optional[str],
    sku_index: dict,
    model_index: dict,
    unique_titles: list,
    title_threshold: float,
) -> dict:
    """Decide the best SoR product for one secondary product.

    Precedence: SKU exact → model exact → title fuzzy (unique titles only).
    Returns {status, product_id, confidence, reason, best_match} where status is
    one of 'matched' | 'uncertain' | 'exception'.
    """
    if sku and sku.strip():
        key = sku.strip().lower()
        if key in sku_index:
            return {'status': 'matched', 'product_id': sku_index[key],
                    'confidence': 98.0, 'reason': f'sku exact: {sku}', 'best_match': None}

    if model and model.strip():
        mn = model.strip().lower()
        if mn in model_index:
            return {'status': 'matched', 'product_id': model_index[mn],
                    'confidence': 95.0, 'reason': f'model_number exact: {model}', 'best_match': None}

    if title and unique_titles:
        match = fuzz_process.extractOne(
            title, [t for _, t in unique_titles], scorer=fuzz.token_sort_ratio
        )
        if match:
            score = float(match[1])
            pid = next(pid for pid, t in unique_titles if t == match[0])
            if score >= title_threshold:
                return {'status': 'matched', 'product_id': pid,
                        'confidence': score, 'reason': f'title_fuzzy: {score:.0f}%',
                        'best_match': match[0]}
            if score >= 50:
                return {'status': 'uncertain', 'product_id': None,
                        'confidence': score, 'reason': None, 'best_match': match[0]}
            return {'status': 'exception', 'product_id': None,
                    'confidence': score, 'reason': None, 'best_match': match[0]}

    return {'status': 'exception', 'product_id': None,
            'confidence': 0.0, 'reason': None, 'best_match': None}


def force_merge_source_sites(
    primary_site: str = 'donut-equipment.com',
    secondary_sites: list[str] | None = None,
    title_threshold: float = 80.0,
    progress: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    For every active product sourced only from a secondary site (not from
    primary_site), find the best-matching SoR product and merge them. SoR is
    always the primary that stays active.

    Match precedence: SKU exact (98) → model exact (95) → title fuzzy
    (>= title_threshold, unique SoR titles only).

    Returns a summary dict with counts and exception details.
    """
    if secondary_sites is None:
        secondary_sites = DEFAULT_SECONDARY_SITES

    def _log(msg: str):
        logger.info(msg)
        if progress:
            progress(msg)

    summary = {
        'merged': 0,
        'uncertain': 0,
        'exceptions': [],   # {product_id, title, site, best_score, best_match}
        'already_linked': 0,
        'by_reason': {'sku': 0, 'model': 0, 'title': 0},
    }

    with session_scope() as db:
        active_ids = _active_product_ids(db)
        primary_ids = _site_product_ids(db, primary_site)

        primary_products = (
            db.query(Product)
            .filter(Product.id.in_(primary_ids), Product.is_active == True)
            .all()
        )
        primary_by_id = {p.id: p for p in primary_products}
        primary_titles = [(p.id, p.canonical_title or '') for p in primary_products]

        primary_sku_index: dict[str, int] = {}
        primary_model_index: dict[str, int] = {}
        for p in primary_products:
            if p.sku and p.sku.strip():
                primary_sku_index.setdefault(p.sku.strip().lower(), p.id)
            if p.model_number and p.model_number.strip():
                primary_model_index.setdefault(p.model_number.strip().lower(), p.id)

        # Title-fuzzy only against titles unique among SoR products — a title
        # shared by N variants can't disambiguate which variant to merge into.
        title_counts = Counter(t for _, t in primary_titles if t)
        unique_titles = [(pid, t) for pid, t in primary_titles if t and title_counts[t] == 1]

        _log(
            f'SoR ({primary_site}): {len(primary_products)} products '
            f'({len(primary_sku_index)} SKUs, {len(unique_titles)} unique titles)'
        )

        for site in secondary_sites:
            site_ids = _site_product_ids(db, site) & active_ids
            unlinked_ids = site_ids - primary_ids
            _log(f'{site}: {len(unlinked_ids)} products need matching')

            secondary_products = (
                db.query(Product)
                .options(joinedload(Product.sources), joinedload(Product.images),
                         joinedload(Product.options))
                .filter(Product.id.in_(unlinked_ids))
                .all()
            )

            for sec in secondary_products:
                m = _best_primary_match(
                    sec.sku, sec.model_number, sec.canonical_title,
                    primary_sku_index, primary_model_index, unique_titles, title_threshold,
                )

                if m['status'] == 'uncertain':
                    summary['uncertain'] += 1
                    logger.debug('Uncertain (%.0f%%): %r → %r',
                                 m['confidence'], (sec.canonical_title or '')[:60],
                                 (m['best_match'] or '')[:60])
                    continue
                if m['status'] == 'exception':
                    summary['exceptions'].append({
                        'product_id': sec.id,
                        'title': sec.canonical_title or '(no title)',
                        'site': site,
                        'best_score': m['confidence'],
                        'best_match': m['best_match'],
                    })
                    continue

                best_primary_id = m['product_id']
                confidence = m['confidence']
                match_reason = m['reason']

                # Guard against a stale index pointing at a now-merged/inactive id.
                primary = primary_by_id.get(best_primary_id) or db.get(Product, best_primary_id)
                if primary is None or not primary.is_active:
                    continue

                pair = (min(sec.id, best_primary_id), max(sec.id, best_primary_id))
                existing = (
                    db.query(DuplicateCandidate)
                    .filter(
                        DuplicateCandidate.primary_product_id == pair[0],
                        DuplicateCandidate.secondary_product_id == pair[1],
                    )
                    .first()
                )
                if existing and existing.status == 'merged':
                    summary['already_linked'] += 1
                    continue

                if not existing:
                    existing = DuplicateCandidate(
                        primary_product_id=pair[0],
                        secondary_product_id=pair[1],
                        confidence_score=confidence,
                        match_reasons_json=json.dumps({'reason': match_reason}),
                        status='pending',
                    )
                    db.add(existing)
                    db.flush()
                else:
                    existing.confidence_score = confidence
                    existing.match_reasons_json = json.dumps({'reason': match_reason})

                # SoR product is ALWAYS the primary that stays active;
                # _merge_products deactivates the secondary (this store's listing).
                _engine._merge_products(
                    db, primary, sec, existing,
                    auto=True,
                    notes=f'force-merge from {site}: {match_reason}',
                )
                db.commit()
                summary['merged'] += 1
                if match_reason.startswith('sku'):
                    summary['by_reason']['sku'] += 1
                elif match_reason.startswith('model'):
                    summary['by_reason']['model'] += 1
                else:
                    summary['by_reason']['title'] += 1

                if summary['merged'] % 200 == 0:
                    _log(f'  merged {summary["merged"]} so far…')

        _log(
            f'Force-merge complete: {summary["merged"]} merged '
            f'(sku={summary["by_reason"]["sku"]}, model={summary["by_reason"]["model"]}, '
            f'title={summary["by_reason"]["title"]}), '
            f'{summary["uncertain"]} uncertain, {len(summary["exceptions"])} exceptions'
        )

    return summary
