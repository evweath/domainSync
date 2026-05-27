"""
Force-merge products from secondary source sites into their best-matching
primary-site counterpart.  Used to link donut-supplies.com and
bakerywholesalers.com listings to donut-equipment.com products.
"""
import json
import logging
from datetime import datetime
from typing import Callable, Optional

from rapidfuzz import fuzz, process as fuzz_process
from sqlalchemy.orm import Session, joinedload

from backend.database.db import session_scope
from backend.database.models import DuplicateCandidate, Product, ProductSource, ProductVersion
from backend.dedup.engine import DeduplicationEngine

logger = logging.getLogger(__name__)

_engine = DeduplicationEngine()


def _site_product_ids(db: Session, site: str) -> set[int]:
    return {
        r[0] for r in db.query(ProductSource.product_id)
        .filter(ProductSource.source_site == site, ProductSource.is_active == True)
        .all()
    }


def _active_product_ids(db: Session) -> set[int]:
    return {r[0] for r in db.query(Product.id).filter(Product.is_active == True).all()}


def force_merge_source_sites(
    primary_site: str = 'donut-equipment.com',
    secondary_sites: list[str] | None = None,
    title_threshold: float = 65.0,
    progress: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    For every active product sourced only from a secondary site (not from
    primary_site), find the best-matching primary-site product and merge them.

    Merge criteria (highest priority first):
      1. Model number exact match → always merge (confidence 95)
      2. Title fuzzy similarity >= title_threshold → merge
      3. Title similarity 50–threshold → log as uncertain, skip
      4. Title similarity < 50 → log as exception (no match)

    Returns a summary dict with counts and exception details.
    """
    if secondary_sites is None:
        secondary_sites = ['donut-supplies.com', 'bakerywholesalers.com']

    def _log(msg: str):
        logger.info(msg)
        if progress:
            progress(msg)

    summary = {
        'merged': 0,
        'uncertain': 0,
        'exceptions': [],   # (product_id, title, best_score, best_match_title)
        'already_linked': 0,
    }

    with session_scope() as db:
        active_ids = _active_product_ids(db)
        primary_ids = _site_product_ids(db, primary_site)

        # Load primary products into memory (title index for fast lookup)
        primary_products = (
            db.query(Product)
            .filter(Product.id.in_(primary_ids), Product.is_active == True)
            .all()
        )
        # Build lookup structures
        primary_by_id = {p.id: p for p in primary_products}
        primary_titles = [(p.id, p.canonical_title or '') for p in primary_products]
        primary_model_index: dict[str, int] = {}  # model_number → product_id
        for p in primary_products:
            if p.model_number:
                primary_model_index[p.model_number.strip().lower()] = p.id

        _log(f'Primary site ({primary_site}): {len(primary_products)} products loaded')

        for site in secondary_sites:
            site_ids = _site_product_ids(db, site) & active_ids

            # Only process products not already linked to primary site
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
                # 1. Model number exact match
                best_primary_id = None
                confidence = 0.0
                match_reason = ''

                if sec.model_number:
                    mn = sec.model_number.strip().lower()
                    if mn in primary_model_index:
                        best_primary_id = primary_model_index[mn]
                        confidence = 95.0
                        match_reason = f'model_number exact: {sec.model_number}'

                # 2. Title fuzzy match (if no model match)
                if best_primary_id is None and sec.canonical_title:
                    match = fuzz_process.extractOne(
                        sec.canonical_title,
                        [t for _, t in primary_titles],
                        scorer=fuzz.token_sort_ratio,
                    )
                    if match:
                        best_score = match[1]
                        best_idx = next(
                            pid for pid, t in primary_titles if t == match[0]
                        )
                        if best_score >= title_threshold:
                            best_primary_id = best_idx
                            confidence = best_score
                            match_reason = f'title_fuzzy: {best_score:.0f}%'
                        elif best_score >= 50:
                            summary['uncertain'] += 1
                            logger.debug(
                                'Uncertain match (%.0f%%): %r → %r',
                                best_score, sec.canonical_title[:60], match[0][:60],
                            )
                            continue
                        else:
                            summary['exceptions'].append({
                                'product_id': sec.id,
                                'title': sec.canonical_title,
                                'site': site,
                                'best_score': best_score,
                                'best_match': match[0],
                            })
                            logger.warning(
                                'NO MATCH (%.0f%%): id=%d %r',
                                best_score, sec.id, sec.canonical_title[:70],
                            )
                            continue
                elif best_primary_id is None:
                    # No title and no model number — skip
                    summary['exceptions'].append({
                        'product_id': sec.id,
                        'title': sec.canonical_title or '(no title)',
                        'site': site,
                        'best_score': 0,
                        'best_match': None,
                    })
                    continue

                # Check if a merge record already exists
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

                primary = db.get(Product, best_primary_id)

                # Create or reuse DuplicateCandidate
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

                # Always merge: primary_id < secondary_id convention means
                # we need to ensure DE product is always the one that stays active.
                # _merge_products deactivates the second argument (secondary).
                # So: pass primary=DE product, secondary=DS/BW product always.
                pri = primary_by_id[best_primary_id]
                _engine._merge_products(
                    db, pri, sec, existing,
                    auto=True,
                    notes=f'force-merge from {site}: {match_reason}',
                )
                db.commit()
                summary['merged'] += 1

                if summary['merged'] % 100 == 0:
                    _log(f'  merged {summary["merged"]} so far…')

        _log(
            f'Force-merge complete: {summary["merged"]} merged, '
            f'{summary["uncertain"]} uncertain (skipped), '
            f'{len(summary["exceptions"])} exceptions'
        )

    return summary
