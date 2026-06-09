"""
FastAPI route handlers for domainSync.
Covers: scraping, dedup, products, store comparison, shopify sync,
        scheduler, export, reports, AI categorization, webhooks.
"""
import asyncio
import csv
import html
import io
import json
import logging
import re
import time
import zipfile
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


# Scraped product descriptions arrive with raw HTML (paragraphs, lists,
# entities, even inline styles). The dashboard renders these via x-text, so
# any tags display literally to the user. Strip tags + decode entities +
# collapse whitespace so the modal shows readable English sentences.
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(text_value: Optional[str]) -> Optional[str]:
    if not text_value:
        return text_value
    no_tags = _TAG_RE.sub(" ", text_value)
    decoded = html.unescape(no_tags)
    collapsed = _WHITESPACE_RE.sub(" ", decoded).strip()
    return collapsed or None

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session, joinedload

from backend.config import config
from backend.database.db import get_db_session, db_health_check, session_scope
from backend.database.models import (
    AppSetting,
    Competitor,
    CompetitorProductMatch,
    DuplicateCandidate,
    ExportRecord,
    Product,
    ProductImage,
    ProductNote,
    ProductOption,
    ProductSource,
    ProductTag,
    ScheduledJob,
    ScanSession,
    ShopifyProductMapping,
    ShopifyStoreProductId,
    ShopifySavedWebhook,
)
from backend.dedup.engine import DeduplicationEngine
from backend.scrapers.source_scraper import run_source_scan

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()
_active_scans: Dict[int, Any] = {}

from backend.tasks.manager import task_manager as _task_manager
_task_manager.set_broadcast(manager.broadcast)


@router.websocket("/ws/scan-progress")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        from backend.log_tail import get_recent_lines
        await websocket.send_json({"event": "log_tail", "lines": get_recent_lines(50)})
    except Exception:
        pass
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# Dashboard Stats
# ---------------------------------------------------------------------------

@router.get("/api/stats")
def get_stats(db: Session = Depends(get_db_session)):
    total_products = db.query(func.count(Product.id)).filter(Product.is_active == True).scalar() or 0
    total_sources = db.query(func.count(ProductSource.id)).filter(ProductSource.is_active == True).scalar() or 0
    pending_dupes = (
        db.query(func.count(DuplicateCandidate.id))
        .filter(DuplicateCandidate.status == "pending").scalar() or 0
    )
    total_competitors = db.query(func.count(Competitor.id)).filter(Competitor.is_active == True).scalar() or 0
    total_comp_matches = (
        db.query(func.count(CompetitorProductMatch.id))
        .filter(CompetitorProductMatch.is_active == True).scalar() or 0
    )
    last_scan = (
        db.query(ScanSession)
        .filter(ScanSession.session_type == "source")
        .order_by(ScanSession.started_at.desc()).first()
    )
    site_status_raw = (
        db.query(
            ProductSource.source_site,
            ProductSource.source_status,
            func.count(ProductSource.id),
        )
        .group_by(ProductSource.source_site, ProductSource.source_status)
        .all()
    )
    site_counts_map: Dict[str, Any] = {}
    for site, status, count in site_status_raw:
        if site not in site_counts_map:
            site_counts_map[site] = {"active": 0, "draft": 0, "archived": 0, "total": 0}
        s = status or "active"
        site_counts_map[site][s] = site_counts_map[site].get(s, 0) + count
        site_counts_map[site]["total"] += count
    for s in config.get("source_sites", default=[]):
        site_counts_map.setdefault(s["domain"], {"active": 0, "draft": 0, "archived": 0, "total": 0})
    categories = (
        db.query(Product.category, func.count(Product.id))
        .filter(Product.is_active == True, Product.category != None)
        .group_by(Product.category)
        .order_by(func.count(Product.id).desc()).limit(10).all()
    )
    return {
        "total_products": total_products,
        "total_sources": total_sources,
        "pending_duplicates": pending_dupes,
        "total_competitors": total_competitors,
        "total_competitor_matches": total_comp_matches,
        "last_scan": {
            "id": last_scan.id,
            "status": last_scan.status,
            "started_at": last_scan.started_at.isoformat() if last_scan else None,
            "completed_at": last_scan.completed_at.isoformat() if last_scan and last_scan.completed_at else None,
            "new_products": last_scan.new_products,
        } if last_scan else None,
        "products_by_site": site_counts_map,
        "categories": [{"category": cat or "Uncategorized", "count": cnt} for cat, cnt in categories],
        "db": db_health_check(),
    }


# ---------------------------------------------------------------------------
# Competitor managed lists (used by Settings page to show/manage domain lists)
# ---------------------------------------------------------------------------

@router.get("/api/competitors/managed-lists")
def get_managed_lists(db: Session = Depends(get_db_session)):
    """Return manufacturer, excluded, and active competitor domain lists for Settings."""
    manufacturers = [
        {"domain": c.domain, "name": c.name}
        for c in db.query(Competitor).filter(Competitor.is_manufacturer == True).order_by(Competitor.domain).all()
    ]
    excluded = [
        {"domain": c.domain, "name": c.name}
        for c in db.query(Competitor)
        .filter(Competitor.excluded_from_search == True, Competitor.is_manufacturer == False)
        .order_by(Competitor.domain).all()
    ]
    competitors = [
        {"domain": c.domain, "name": c.name}
        for c in db.query(Competitor)
        .filter(Competitor.is_active == True, Competitor.excluded_from_search == False)
        .order_by(Competitor.domain).all()
    ]
    return {"manufacturers": manufacturers, "excluded": excluded, "competitors": competitors}


class ManagedDomainRequest(BaseModel):
    domain: str
    domain_type: str = "competitor"  # "manufacturer" | "excluded" | "competitor"


@router.post("/api/competitors/managed-domain")
def add_managed_domain(req: ManagedDomainRequest, db: Session = Depends(get_db_session)):
    """Add or reclassify a domain in the managed lists."""
    from urllib.parse import urlparse as _urlparse
    raw = req.domain.strip()
    domain = _urlparse(raw).netloc or raw
    domain = domain.lstrip("www.").lower() if domain else raw.lower()
    existing = db.query(Competitor).filter(Competitor.domain == domain).first()
    is_mfr = req.domain_type == "manufacturer"
    is_excl = req.domain_type in ("manufacturer", "excluded")
    if not existing:
        db.add(Competitor(
            domain=domain, name=domain,
            base_url=f"https://{domain}",
            is_manufacturer=is_mfr,
            excluded_from_search=is_excl,
            is_active=not is_excl,
        ))
    else:
        existing.is_manufacturer = is_mfr
        existing.excluded_from_search = is_excl
        existing.is_active = not is_excl
    db.commit()
    return {"status": "ok", "domain": domain}


@router.delete("/api/competitors/managed-domain")
def remove_managed_domain(domain: str, db: Session = Depends(get_db_session)):
    """Remove a domain from managed lists (hard delete)."""
    comp = db.query(Competitor).filter(Competitor.domain == domain).first()
    if comp:
        db.delete(comp)
        db.commit()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

_PRODUCT_SORT_COLS = {
    "title":        lambda: Product.canonical_title,
    "price":        lambda: Product.price_canonical,
    "manufacturer": lambda: Product.manufacturer,
    "model_number": lambda: Product.model_number,
}


@router.get("/api/products")
def list_products(
    search: Optional[str] = None,
    manufacturer: Optional[str] = None,
    category: Optional[str] = None,
    source_site: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    unique_by_title: bool = True,
    page: int = 1,
    per_page: int = 50,
    sort_by: str = "title",
    sort_order: str = "asc",
    db: Session = Depends(get_db_session),
):
    per_page = min(per_page, 200)
    query = db.query(Product).filter(Product.is_active == True)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(
            Product.canonical_title.ilike(like),
            Product.manufacturer.ilike(like),
            Product.model_number.ilike(like),
            Product.sku.ilike(like),
        ))
    if manufacturer:
        query = query.filter(Product.manufacturer.ilike(f"%{manufacturer}%"))
    if category:
        query = query.filter(Product.category.ilike(f"%{category}%"))
    if source_site:
        query = query.join(Product.sources).filter(ProductSource.source_site == source_site)
    if min_price is not None:
        query = query.filter(Product.price_canonical >= min_price)
    if max_price is not None:
        query = query.filter(Product.price_canonical <= max_price)
    if unique_by_title:
        min_ids = [row[0] for row in query.with_entities(func.min(Product.id)).group_by(Product.canonical_title).all()]
        query = db.query(Product).filter(Product.id.in_(min_ids))
    total = query.count()
    sort_col_fn = _PRODUCT_SORT_COLS.get(sort_by, _PRODUCT_SORT_COLS["title"])
    sort_col = sort_col_fn()
    order_expr = sort_col.desc().nullslast() if sort_order == "desc" else sort_col.asc().nullsfirst()
    products = query.order_by(order_expr).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "total": total, "page": page, "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "products": [_serialize_product(p) for p in products],
    }


@router.get("/api/products/filters/options")
def get_filter_options(db: Session = Depends(get_db_session)):
    manufacturers = (
        db.query(Product.manufacturer)
        .filter(Product.is_active == True, Product.manufacturer != None)
        .distinct().order_by(Product.manufacturer).all()
    )
    categories = (
        db.query(Product.category)
        .filter(Product.is_active == True, Product.category != None)
        .distinct().order_by(Product.category).all()
    )
    db_sites = {s[0] for s in db.query(ProductSource.source_site).filter(ProductSource.is_active == True).distinct().all() if s[0]}
    configured_sites = {s["domain"] for s in config.get("source_sites", default=[])}
    all_sites = sorted(db_sites | configured_sites)
    return {
        "manufacturers": [m[0] for m in manufacturers if m[0]],
        "categories": [c[0] for c in categories if c[0]],
        "source_sites": all_sites,
    }


@router.get("/api/products/ids")
def list_product_ids(
    source_site: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db_session),
):
    query = db.query(Product.id).filter(Product.is_active == True)
    if source_site:
        query = query.join(Product.sources).filter(ProductSource.source_site == source_site)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(
            Product.canonical_title.ilike(like),
            Product.manufacturer.ilike(like),
            Product.model_number.ilike(like),
        ))
    return {"ids": [row[0] for row in query.all()]}


# ---------------------------------------------------------------------------
# Store Comparison – compare canonical product across all source stores
# ---------------------------------------------------------------------------

_COMP_FIELDS = [
    ("title",        "canonical_title",  "title"),
    ("manufacturer", "manufacturer",     "manufacturer"),
    ("model_number", "model_number",     "model_number"),
    ("sku",          "sku",              "sku"),
    ("category",     "category",        "category"),
]

_EMPTY_FIELD_MAP: Dict[str, Any] = {
    "title":             Product.canonical_title,
    "manufacturer":      Product.manufacturer,
    "model_number":      Product.model_number,
    "sku":               Product.sku,
    "category":          Product.category,
    "subcategory":       Product.subcategory,
    "ai_category":       Product.ai_category,
    "description":       Product.canonical_description,
    "price":             Product.price_canonical,
    "weight":            Product.weight,
    "dimensions":        Product.dimensions_json,
    "country_of_origin": Product.country_of_origin,
}

_SC_SORT_COLS: Dict[str, Any] = {
    "title":        Product.canonical_title,
    "manufacturer": Product.manufacturer,
    "model_number": Product.model_number,
    "sku":          Product.sku,
    "price":        Product.price_canonical,
    "category":     Product.category,
}


@router.get("/api/products/store-comparison")
def get_store_comparison(
    page: int = 1,
    per_page: int = 25,
    search: Optional[str] = None,
    manufacturer: Optional[str] = None,
    category: Optional[str] = None,
    source_site: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    in_stock: Optional[bool] = None,
    has_diffs: bool = False,
    missing_from: Optional[int] = None,
    has_empty: Optional[str] = None,
    sort_by: str = "title",
    sort_order: str = "asc",
    db: Session = Depends(get_db_session),
):
    per_page = min(per_page, 100)
    source_sites = [s["domain"] for s in config.get("source_sites", default=[]) if s.get("enabled", True)]

    base_q = db.query(Product).filter(Product.is_active == True)
    if search:
        like = f"%{search}%"
        base_q = base_q.filter(or_(
            Product.canonical_title.ilike(like),
            Product.manufacturer.ilike(like),
            Product.model_number.ilike(like),
            Product.sku.ilike(like),
        ))
    if manufacturer:
        base_q = base_q.filter(Product.manufacturer.ilike(f"%{manufacturer}%"))
    if category:
        base_q = base_q.filter(Product.category.ilike(f"%{category}%"))
    if source_site:
        base_q = (base_q.join(Product.sources)
                  .filter(ProductSource.source_site == source_site, ProductSource.is_active == True)
                  .distinct())
    if min_price is not None:
        base_q = base_q.filter(Product.price_canonical >= min_price)
    if max_price is not None:
        base_q = base_q.filter(Product.price_canonical <= max_price)
    if in_stock is not None:
        base_q = base_q.filter(Product.in_stock == in_stock)
    if has_empty:
        for fname in [f.strip() for f in has_empty.split(",") if f.strip()]:
            col = _EMPTY_FIELD_MAP.get(fname)
            if col is not None:
                base_q = base_q.filter(or_(col == None, col == ""))

    sort_col = _SC_SORT_COLS.get(sort_by, Product.canonical_title)
    sort_expr = sort_col.desc().nullslast() if sort_order == "desc" else sort_col.asc().nullsfirst()

    if has_diffs or missing_from is not None:
        # Light pass: evaluate diff/missing predicates before paginating
        light = (
            base_q.options(joinedload(Product.sources))
            .order_by(sort_expr)
            .all()
        )
        filtered_ids: List[int] = []
        for p in light:
            site_srcs: Dict[str, Any] = {}
            for src in sorted(p.sources, key=lambda s: s.scraped_at or datetime.min, reverse=True):
                if src.is_active and src.source_site not in site_srcs:
                    site_srcs[src.source_site] = src

            missing_n = len([site for site in source_sites if site not in site_srcs])
            if missing_from is not None and missing_n < missing_from:
                continue

            if has_diffs:
                srcs_light = {
                    site: {
                        "title": src.source_title, "manufacturer": src.source_manufacturer,
                        "model_number": src.source_model_number, "sku": src.source_sku,
                        "category": src.source_category, "price": src.source_price,
                    }
                    for site in source_sites
                    if (src := site_srcs.get(site))
                }
                present = [site for site in source_sites if srcs_light.get(site)]
                diffs: List[str] = []
                for label, _, src_attr in _COMP_FIELDS:
                    src_vals = [
                        (srcs_light[site].get(src_attr) or "").strip().lower()
                        for site in present if (srcs_light[site].get(src_attr) or "").strip()
                    ]
                    if len(src_vals) >= 2 and len(set(src_vals)) > 1:
                        diffs.append(label)
                    elif len(src_vals) >= 1 and len(src_vals) < len(present):
                        diffs.append(label)
                prices = [srcs_light[s]["price"] for s in present if srcs_light[s].get("price")]
                if len(set(prices)) > 1:
                    diffs.append("price")
                if not diffs:
                    continue

            filtered_ids.append(p.id)

        total = len(filtered_ids)
        page_ids = filtered_ids[(page - 1) * per_page: page * per_page]
        products = (
            db.query(Product)
            .filter(Product.id.in_(page_ids))
            .options(
                joinedload(Product.sources), joinedload(Product.tags),
                joinedload(Product.options), joinedload(Product.images),
            )
            .order_by(sort_expr)
            .all()
        ) if page_ids else []
    else:
        q = base_q.options(
            joinedload(Product.sources), joinedload(Product.tags),
            joinedload(Product.options), joinedload(Product.images),
        )
        total = q.count()
        products = q.order_by(sort_expr).offset((page - 1) * per_page).limit(per_page).all()

    results = []
    for product in products:
        # latest active source per site
        site_sources: Dict[str, Any] = {}
        for src in sorted(product.sources, key=lambda s: s.scraped_at or datetime.min, reverse=True):
            if src.is_active and src.source_site not in site_sources:
                site_sources[src.source_site] = src

        canonical = {
            "title": product.canonical_title,
            "description": _strip_html(product.canonical_description),
            "sku": product.sku,
            "manufacturer": product.manufacturer,
            "model_number": product.model_number,
            "price_canonical": product.price_canonical,
            "price_min": product.price_min,
            "price_max": product.price_max,
            "category": product.category,
            "subcategory": product.subcategory,
            "ai_category": product.ai_category,
            "country_of_origin": product.country_of_origin,
            "weight": product.weight,
            "dimensions": json.loads(product.dimensions_json) if product.dimensions_json else None,
            "specs": json.loads(product.specs_json) if product.specs_json else None,
            "in_stock": product.in_stock,
            "tags": sorted(t.tag for t in product.tags),
            "images": [
                {"url": img.source_url, "is_primary": img.is_primary, "source_site": img.source_site}
                for img in product.images
            ],
            "options": [
                {
                    "group": o.option_group, "value": o.option_value,
                    "price_modifier": o.price_modifier, "sku_suffix": o.sku_suffix,
                    "source_site": o.source_site,
                }
                for o in product.options
            ],
        }

        sources: Dict[str, Any] = {}
        for site in source_sites:
            src = site_sources.get(site)
            if src:
                sources[site] = {
                    "source_id": src.id,
                    "title": src.source_title,
                    "description": _strip_html(src.source_description),
                    "sku": src.source_sku,
                    "manufacturer": src.source_manufacturer,
                    "model_number": src.source_model_number,
                    "price": src.source_price,
                    "price_raw": src.source_price_raw,
                    "category": src.source_category,
                    "url": src.source_url,
                    "scraped_at": src.scraped_at.isoformat() if src.scraped_at else None,
                    "options": [
                        {"group": o.option_group, "value": o.option_value, "price_modifier": o.price_modifier}
                        for o in product.options if o.source_site == site
                    ],
                    "images": [
                        {"url": img.source_url, "is_primary": img.is_primary}
                        for img in product.images if img.source_site == site
                    ],
                }
            else:
                sources[site] = None

        # Compare sources to each other (not to canonical — canonical is seeded from first scrape)
        present_sites = [site for site in source_sites if sources.get(site)]
        missing_sites_list = [site for site in source_sites if site not in site_sources]
        diff_fields: List[str] = []
        for label, _, src_attr in _COMP_FIELDS:
            # Values from sites that carry this field (non-null/non-empty)
            src_vals = [
                (sources[site][src_attr] or "").strip().lower()
                for site in present_sites
                if (sources[site].get(src_attr) or "").strip()
            ]
            if len(src_vals) >= 2 and len(set(src_vals)) > 1:
                diff_fields.append(label)
            elif len(src_vals) >= 1 and len(src_vals) < len(present_sites):
                # Some stores have this field, others don't
                diff_fields.append(label)

        src_prices = [sources[s]["price"] for s in present_sites if sources[s].get("price")]
        if len(set(src_prices)) > 1:
            diff_fields.append("price")

        if has_diffs and not diff_fields:
            continue

        results.append({
            "product_id": product.id,
            "canonical_title": product.canonical_title,
            "canonical": canonical,
            "sources": sources,
            "diff_fields": diff_fields,
            "missing_sites": missing_sites_list,
            "source_count": len(site_sources),
        })

    return {
        "total": total,
        "page": page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "source_sites": source_sites,
        "products": results,
    }


class UpdateCanonicalRequest(BaseModel):
    canonical_title: Optional[str] = None
    canonical_description: Optional[str] = None
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    sku: Optional[str] = None
    price_canonical: Optional[float] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    ai_category: Optional[str] = None
    country_of_origin: Optional[str] = None
    weight: Optional[float] = None
    in_stock: Optional[bool] = None
    tags: Optional[List[str]] = None


@router.put("/api/products/{product_id}/canonical")
def update_canonical(product_id: int, req: UpdateCanonicalRequest, db: Session = Depends(get_db_session)):
    product = db.query(Product).filter(Product.id == product_id, Product.is_active == True).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    update_data = req.model_dump(exclude_unset=True)
    tags = update_data.pop("tags", None)

    for field, value in update_data.items():
        setattr(product, field, value)

    if tags is not None:
        for t in list(product.tags):
            db.delete(t)
        db.flush()
        for tag in tags:
            tag = tag.strip()
            if tag:
                db.add(ProductTag(product_id=product.id, tag=tag))

    product.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(product)
    return _serialize_product(product, full=True)


class BulkDeactivateRequest(BaseModel):
    product_ids: List[int]


@router.post("/api/products/bulk-deactivate")
def bulk_deactivate_products(req: BulkDeactivateRequest, db: Session = Depends(get_db_session)):
    if not req.product_ids:
        return {"deactivated": 0}
    updated = (
        db.query(Product)
        .filter(Product.id.in_(req.product_ids))
        .update({"is_active": False}, synchronize_session=False)
    )
    db.commit()
    return {"deactivated": updated}


@router.post("/api/products/{product_id}/deactivate")
def deactivate_product(product_id: int, db: Session = Depends(get_db_session)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.is_active = False
    db.commit()
    return {"status": "deactivated"}


@router.get("/api/products/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db_session)):
    product = db.query(Product).filter(Product.id == product_id, Product.is_active == True).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return _serialize_product(product, full=True)



def _serialize_product(p: Product, full: bool = False) -> dict:
    sources = [
        {"id": s.id, "site": s.source_site, "url": s.source_url, "title": s.source_title,
         "price": s.source_price, "scraped_at": s.scraped_at.isoformat() if s.scraped_at else None}
        for s in p.sources if s.is_active
    ]
    images = [
        {"url": img.source_url, "local_path": img.local_path, "is_primary": img.is_primary}
        for img in p.images
    ]
    comp_count = len([m for m in p.competitor_matches if m.is_active])
    result = {
        "id": p.id, "title": p.canonical_title, "manufacturer": p.manufacturer,
        "model_number": p.model_number, "sku": p.sku, "price": p.price_canonical,
        "price_min": p.price_min, "price_max": p.price_max, "category": p.category,
        "subcategory": p.subcategory, "ai_category": p.ai_category,
        "in_stock": p.in_stock, "is_active": p.is_active,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "sources": sources, "competitor_matches": comp_count,
        "primary_image": next((img["url"] for img in images if img["is_primary"]), images[0]["url"] if images else None),
    }
    if full:
        result.update({
            "description": _strip_html(p.canonical_description),
            "dimensions": json.loads(p.dimensions_json) if p.dimensions_json else None,
            "specs": json.loads(p.specs_json) if p.specs_json else None,
            "weight": p.weight, "country_of_origin": p.country_of_origin,
            "images": images,
            "options": [{"group": o.option_group, "value": o.option_value, "price_modifier": o.price_modifier} for o in p.options],
            "tags": [t.tag for t in p.tags],
            "notes": [{"text": _strip_html(n.note_text), "created_at": n.created_at.isoformat(), "by": n.created_by} for n in p.notes_list],
            "version": p.version,
        })
    return result


# ---------------------------------------------------------------------------
# Source Scan Control (F01-F05)
# ---------------------------------------------------------------------------

class StartScanRequest(BaseModel):
    site_filter: Optional[str] = None
    name: Optional[str] = None


@router.post("/api/scan/sources")
async def start_source_scan(req: StartScanRequest, db: Session = Depends(get_db_session)):
    scan_session = ScanSession(
        name=req.name or f"Source Scan {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
        session_type="source", target=req.site_filter or "all_sources", status="pending",
    )
    db.add(scan_session)
    db.flush()
    session_id = scan_session.id
    db.commit()

    async def do_scan():
        from backend.app import capture_error
        async def ws_progress(event: str, data: dict):
            await manager.broadcast({"event": event, "session_id": session_id, **data})
        try:
            await run_source_scan(scan_session_id=session_id, site_filter=req.site_filter, progress_callbacks=[ws_progress])
            await manager.broadcast({"event": "scan_complete", "session_id": session_id})
        except Exception as exc:
            capture_error(exc, context=f"source_scan session={session_id}")
            await manager.broadcast({"event": "scan_error", "session_id": session_id, "error": str(exc)})
        finally:
            _active_scans.pop(session_id, None)

    task = asyncio.create_task(do_scan())
    _active_scans[session_id] = task
    return {"scan_session_id": session_id, "status": "started"}


@router.delete("/api/scan/{session_id}/cancel")
def cancel_scan(session_id: int, db: Session = Depends(get_db_session)):
    task = _active_scans.get(session_id)
    if task:
        task.cancel()
        _active_scans.pop(session_id, None)
    sess = db.get(ScanSession, session_id)
    if sess and sess.status == "running":
        sess.status = "cancelled"
        sess.completed_at = datetime.utcnow()
    return {"status": "cancellation_requested"}


@router.get("/api/scan/sessions")
def list_scan_sessions(page: int = 1, per_page: int = 20, db: Session = Depends(get_db_session)):
    total = db.query(func.count(ScanSession.id)).scalar() or 0
    sessions = (
        db.query(ScanSession).order_by(ScanSession.started_at.desc())
        .offset((page - 1) * per_page).limit(per_page).all()
    )
    return {
        "total": total,
        "sessions": [
            {"id": s.id, "name": s.name, "type": s.session_type, "target": s.target,
             "status": s.status,
             "started_at": s.started_at.isoformat() if s.started_at else None,
             "completed_at": s.completed_at.isoformat() if s.completed_at else None,
             "total_scraped": s.total_scraped, "new_products": s.new_products,
             "updated_products": s.updated_products, "errors": s.errors}
            for s in sessions
        ],
    }


@router.get("/api/scan/{session_id}/status")
def get_scan_status(session_id: int, db: Session = Depends(get_db_session)):
    sess = db.get(ScanSession, session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Scan session not found")
    return {
        "id": sess.id, "status": sess.status, "total_scraped": sess.total_scraped,
        "new_products": sess.new_products, "updated_products": sess.updated_products,
        "errors": sess.errors, "is_active": sess.id in _active_scans,
    }


# ---------------------------------------------------------------------------
# Deduplication (F06-F11)
# ---------------------------------------------------------------------------

class DeduplicateRequest(BaseModel):
    product_ids: Optional[List[int]] = None
    domain_filters: Optional[List[str]] = None


@router.post("/api/dedup/run")
async def run_deduplication(req: DeduplicateRequest):
    """Kick off a dedup pass off the event loop.

    DeduplicationEngine.run is sync and does an O(n²) pass over the active
    product table with DB queries inside the loop — calling it directly
    from an asyncio task blocks the event loop for minutes (no WS
    broadcasts, no API responses, can't shut down cleanly). We hand it
    to the default thread pool so the loop stays free to serve other
    requests and stream the live log.
    """
    def _sync_run():
        with session_scope() as s:
            engine = DeduplicationEngine()
            return engine.run(s, req.product_ids, req.domain_filters)

    async def do_dedup():
        await manager.broadcast({"event": "dedup_started"})
        try:
            stats = await asyncio.get_event_loop().run_in_executor(None, _sync_run)
            await manager.broadcast({"event": "dedup_complete", "stats": stats})
        except Exception as exc:
            logger.exception("Dedup run failed: %s", exc)
            await manager.broadcast({"event": "dedup_error", "error": str(exc)})

    asyncio.create_task(do_dedup())
    return {"status": "dedup_started"}


@router.get("/api/dedup/candidates")
def list_duplicate_candidates(status: str = "pending", page: int = 1, per_page: int = 20, db: Session = Depends(get_db_session)):
    query = db.query(DuplicateCandidate)
    if status != "all":
        query = query.filter(DuplicateCandidate.status == status)
    total = query.count()
    candidates = query.order_by(DuplicateCandidate.confidence_score.desc()).offset((page - 1) * per_page).limit(per_page).all()
    results = []
    for c in candidates:
        primary = db.get(Product, c.primary_product_id)
        secondary = db.get(Product, c.secondary_product_id)
        if not primary or not secondary:
            continue
        results.append({
            "id": c.id, "confidence_score": c.confidence_score, "status": c.status,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "match_reasons": json.loads(c.match_reasons_json) if c.match_reasons_json else {},
            "primary": {"id": primary.id, "title": primary.canonical_title, "price": primary.price_canonical,
                        "manufacturer": primary.manufacturer, "model_number": primary.model_number,
                        "sku": primary.sku,
                        "sources": [s.source_site for s in primary.sources if s.is_active],
                        "image": next((img.source_url for img in primary.images if img.is_primary), None)},
            "secondary": {"id": secondary.id, "title": secondary.canonical_title, "price": secondary.price_canonical,
                          "manufacturer": secondary.manufacturer, "model_number": secondary.model_number,
                          "sku": secondary.sku,
                          "sources": [s.source_site for s in secondary.sources if s.is_active],
                          "image": next((img.source_url for img in secondary.images if img.is_primary), None)},
        })
    return {"total": total, "candidates": results}


@router.get("/api/dedup/candidates/ids")
def list_duplicate_candidate_ids(status: str = "pending", db: Session = Depends(get_db_session)):
    query = db.query(DuplicateCandidate.id)
    if status != "all":
        query = query.filter(DuplicateCandidate.status == status)
    return {"ids": [row[0] for row in query.all()]}


class ResolveRequest(BaseModel):
    action: str
    notes: Optional[str] = None


@router.post("/api/dedup/candidates/{candidate_id}/resolve")
def resolve_duplicate(candidate_id: int, req: ResolveRequest, db: Session = Depends(get_db_session)):
    engine = DeduplicationEngine()
    if req.action == "merge":
        ok = engine.manual_merge(db, candidate_id, notes=req.notes or "", resolved_by="user")
    elif req.action == "reject":
        ok = engine.reject_duplicate(db, candidate_id, notes=req.notes or "", resolved_by="user")
    else:
        raise HTTPException(status_code=400, detail="action must be 'merge' or 'reject'")
    if not ok:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return {"status": "resolved", "action": req.action}


class BulkDeleteRequest(BaseModel):
    candidate_ids: List[int]


@router.post("/api/dedup/candidates/bulk-delete")
def bulk_delete_duplicate_candidates(req: BulkDeleteRequest, db: Session = Depends(get_db_session)):
    if not req.candidate_ids:
        return {"deleted": 0}
    deleted = (
        db.query(DuplicateCandidate)
        .filter(DuplicateCandidate.id.in_(req.candidate_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"deleted": deleted}


# ---------------------------------------------------------------------------
# Scheduler (F43-F47)
# ---------------------------------------------------------------------------

class CreateJobRequest(BaseModel):
    name: str
    job_type: str   # source_scan|competitor_scan|price_check|export|dedup
    target: Optional[str] = None
    schedule_type: str  # cron|daily|weekly|monthly|one_time|interval_minutes
    schedule_value: str
    config_json: Optional[str] = None


@router.get("/api/scheduler/jobs")
def list_jobs():
    from backend.scheduler.scheduler import list_jobs as _list
    return {"jobs": _list()}


@router.post("/api/scheduler/jobs")
def create_job(req: CreateJobRequest):
    from backend.scheduler.scheduler import create_job as _create
    try:
        result = _create(
            name=req.name, job_type=req.job_type, target=req.target,
            schedule_type=req.schedule_type, schedule_value=req.schedule_value,
            config_json=req.config_json,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/api/scheduler/jobs/{job_id}")
def delete_job(job_id: int):
    from backend.scheduler.scheduler import delete_job as _delete
    _delete(job_id)
    return {"status": "deleted"}


@router.post("/api/scheduler/jobs/{job_id}/run-now")
def run_job_now(job_id: int):
    from backend.scheduler.scheduler import run_job_now as _run
    _run(job_id)
    return {"status": "queued"}


@router.put("/api/scheduler/jobs/{job_id}/toggle")
def toggle_job(job_id: int, active: bool = True):
    from backend.scheduler.scheduler import toggle_job as _toggle
    _toggle(job_id, active)
    return {"status": "updated", "active": active}


# ---------------------------------------------------------------------------
# Export (F39-F42)
# ---------------------------------------------------------------------------

@router.get("/api/export/products")
def export_products(
    fmt: str = "csv",
    include_competitors: bool = True,
    include_price_history: bool = False,
    db: Session = Depends(get_db_session),
):
    from backend.export.exporter import export_products_csv, export_products_xlsx, export_products_txt

    if fmt == "csv":
        data, filename = export_products_csv(triggered_by="user")
        return Response(content=data, media_type="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={filename}"})
    elif fmt == "xlsx":
        data, filename = export_products_xlsx(
            include_competitors=include_competitors,
            include_price_history=include_price_history,
            triggered_by="user",
        )
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    elif fmt == "txt":
        data, filename = export_products_txt(triggered_by="user")
        return Response(content=data, media_type="text/plain",
                        headers={"Content-Disposition": f"attachment; filename={filename}"})
    raise HTTPException(status_code=400, detail=f"Unsupported format: {fmt}. Use csv, xlsx, or txt")


@router.get("/api/export/history")
def export_history(page: int = 1, per_page: int = 20, db: Session = Depends(get_db_session)):
    """F42: Export history log."""
    total = db.query(func.count(ExportRecord.id)).scalar() or 0
    records = (
        db.query(ExportRecord).order_by(ExportRecord.created_at.desc())
        .offset((page - 1) * per_page).limit(per_page).all()
    )
    return {
        "total": total,
        "records": [
            {"id": r.id, "export_type": r.export_type, "filename": r.filename,
             "scope": r.scope, "row_count": r.row_count, "triggered_by": r.triggered_by,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in records
        ],
    }


# ---------------------------------------------------------------------------
# Reports (F61-F63)
# ---------------------------------------------------------------------------

@router.get("/api/reports/price-disparity", response_class=HTMLResponse)
def report_price_disparity(threshold: float = 5.0):
    from backend.reports.reporter import price_disparity_report
    return HTMLResponse(content=price_disparity_report(threshold))


@router.get("/api/reports/competitor/{competitor_id}", response_class=HTMLResponse)
def report_competitor(competitor_id: int):
    from backend.reports.reporter import competitor_report
    return HTMLResponse(content=competitor_report(competitor_id))


@router.get("/api/reports/summary", response_class=HTMLResponse)
def report_summary(days: int = 7):
    from backend.reports.reporter import summary_report
    return HTMLResponse(content=summary_report(days))


@router.get("/api/reports/price-comparison/{product_id}", response_class=HTMLResponse)
def report_price_comparison(product_id: int):
    from backend.reports.reporter import price_comparison_report
    return HTMLResponse(content=price_comparison_report(product_id))


# ---------------------------------------------------------------------------
# AI Categorization (F64)
# ---------------------------------------------------------------------------

class CategorizeRequest(BaseModel):
    product_ids: List[int]


@router.post("/api/ai/categorize")
async def ai_categorize(req: CategorizeRequest):
    async def do_categorize():
        from backend.ai.categorizer import bulk_categorize
        results = bulk_categorize(req.product_ids)
        count = sum(1 for r in results.values() if r)
        await manager.broadcast({"event": "ai_categorize_complete", "categorized": count, "total": len(req.product_ids)})

    asyncio.create_task(do_categorize())
    return {"status": "categorization_started", "product_count": len(req.product_ids)}


# ---------------------------------------------------------------------------
# Tags & Notes (F71)
# ---------------------------------------------------------------------------

class AddTagRequest(BaseModel):
    tag: str


@router.post("/api/products/{product_id}/tags")
def add_tag(product_id: int, req: AddTagRequest, db: Session = Depends(get_db_session)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    existing = next((t for t in product.tags if t.tag == req.tag.strip()), None)
    if not existing:
        db.add(ProductTag(product_id=product_id, tag=req.tag.strip()))
    return {"status": "ok"}


@router.delete("/api/products/{product_id}/tags/{tag}")
def remove_tag(product_id: int, tag: str, db: Session = Depends(get_db_session)):
    tag_obj = db.query(ProductTag).filter(ProductTag.product_id == product_id, ProductTag.tag == tag).first()
    if tag_obj:
        db.delete(tag_obj)
    return {"status": "ok"}


class AddNoteRequest(BaseModel):
    note: str


@router.post("/api/products/{product_id}/notes")
def add_note(product_id: int, req: AddNoteRequest, db: Session = Depends(get_db_session)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    db.add(ProductNote(product_id=product_id, note_text=req.note.strip(), created_by="user"))
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Webhooks (F72)
# ---------------------------------------------------------------------------

class WebhookConfig(BaseModel):
    url: str
    events: List[str]   # price_alert|scan_complete|competitor_scan_complete
    secret: Optional[str] = None


@router.put("/api/settings/webhook")
def configure_webhook(req: WebhookConfig):
    config.set("webhook", "url", req.url)
    config.set("webhook", "events", req.events)
    if req.secret:
        config.set("webhook", "secret", req.secret)
    return {"status": "webhook configured"}


@router.get("/api/settings/webhook")
def get_webhook():
    return {
        "url": config.get("webhook", "url", default=""),
        "events": config.get("webhook", "events", default=[]),
    }


# ---------------------------------------------------------------------------
# Settings (F56)
# ---------------------------------------------------------------------------

@router.get("/api/settings")
def get_settings():
    return config.all()


class UpdateSettingRequest(BaseModel):
    keys: List[str]
    value: Any


@router.put("/api/settings")
def update_setting(req: UpdateSettingRequest):
    config.set(*req.keys, req.value)
    return {"status": "saved"}


@router.get("/api/settings/db-health")
def db_health():
    return db_health_check()


# ---------------------------------------------------------------------------
# Source-site Shopify credentials
# ---------------------------------------------------------------------------

class ShopifyCredentialsRequest(BaseModel):
    shopify_store_url: str = ""
    shopify_client_id: str = ""       # formerly api_key; Client ID from Shopify app
    shopify_client_secret: str = ""   # shpss_… prefix; used for webhook signature verification
    shopify_access_token: str = ""    # shpat_… (custom app) or atkn_… (newer app automation token)
    sync_draft: bool = False
    sync_archived: bool = False


@router.put("/api/source-sites/{domain}/credentials")
def save_source_site_credentials(domain: str, req: ShopifyCredentialsRequest):
    """Persist Shopify API credentials for a source site (matched by domain)."""
    sites = config.get("source_sites", default=[])
    matched = False
    for site in sites:
        if site.get("domain") == domain:
            site["shopify_store_url"] = req.shopify_store_url.strip()
            site["shopify_client_id"] = req.shopify_client_id.strip()
            site["shopify_client_secret"] = req.shopify_client_secret.strip()
            site["shopify_access_token"] = req.shopify_access_token.strip()
            site["sync_draft"] = req.sync_draft
            site["sync_archived"] = req.sync_archived
            matched = True
            break
    if not matched:
        raise HTTPException(status_code=404, detail=f"Source site not found: {domain}")
    # Patch the list back into config and save
    config._settings["source_sites"] = sites
    config._save()
    return {"status": "saved", "domain": domain}


@router.post("/api/source-sites/{domain}/test-connection")
async def test_source_site_connection(domain: str):
    """Verify Shopify API credentials by fetching the shop info endpoint."""
    sites = config.get("source_sites", default=[])
    site = next((s for s in sites if s.get("domain") == domain), None)
    if site is None:
        raise HTTPException(status_code=404, detail=f"Source site not found: {domain}")

    store_url = (site.get("shopify_store_url") or "").strip().rstrip("/")
    client_id = (site.get("shopify_client_id") or "").strip()
    client_secret = (site.get("shopify_client_secret") or "").strip()

    if not store_url or not client_id or not client_secret:
        return {"ok": False, "error": "Store URL, Client ID, and Client Secret are required"}

    if not store_url.startswith("http"):
        store_url = "https://" + store_url

    from backend.shopify.client import fetch_access_token, ShopifyError
    import httpx
    try:
        access_token = await fetch_access_token(store_url, client_id, client_secret)
        _shopify_token_cache[domain] = {"token": access_token, "expires_at": time.time() + 86399}
    except ShopifyError as exc:
        return {"ok": False, "error": f"Token exchange failed — {exc}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    try:
        url = f"{store_url}/admin/api/2024-01/shop.json"
        headers = {"X-Shopify-Access-Token": access_token, "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            shop = resp.json().get("shop", {})
            return {"ok": True, "shop_name": shop.get("name", ""), "plan": shop.get("plan_name", "")}
        return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Task Manager — active/recent task list
# ---------------------------------------------------------------------------

@router.get("/api/tasks")
def list_tasks():
    return {"tasks": _task_manager.get_all()}


# ---------------------------------------------------------------------------
# Scan Cycle Status — prevents re-scanning before a full cycle is approved
# ---------------------------------------------------------------------------

_CYCLE_KEY = "scan_cycle_status"

def _read_cycle(db: Session) -> dict:
    row = db.query(AppSetting).filter(AppSetting.key == _CYCLE_KEY).first()
    if row and row.value:
        try:
            return json.loads(row.value)
        except Exception:
            pass
    return {"status": "idle", "domains_started": [], "domains_complete": [], "dedup_done": False, "last_complete_at": None}


def _write_cycle(db: Session, state: dict) -> None:
    row = db.query(AppSetting).filter(AppSetting.key == _CYCLE_KEY).first()
    if row:
        row.value = json.dumps(state)
    else:
        db.add(AppSetting(key=_CYCLE_KEY, value=json.dumps(state), description="Parallel scan cycle state"))


@router.get("/api/scan/cycle-status")
def get_cycle_status(db: Session = Depends(get_db_session)):
    return _read_cycle(db)


@router.post("/api/scan/cycle/approve")
def approve_cycle(db: Session = Depends(get_db_session)):
    state = _read_cycle(db)
    state["status"] = "complete"
    state["last_complete_at"] = datetime.utcnow().isoformat()
    _write_cycle(db, state)
    return {"status": "approved"}


# ---------------------------------------------------------------------------
# Parallel Source Scan — spawns one task per enabled domain + dedup after
# ---------------------------------------------------------------------------

@router.post("/api/scan/all-sources")
async def start_parallel_scan(db: Session = Depends(get_db_session)):
    state = _read_cycle(db)
    if state.get("status") in ("scanning", "dedup_running", "review_pending"):
        raise HTTPException(status_code=409, detail="A scan cycle is already in progress")

    sites = [s for s in config.get("source_sites", default=[]) if s.get("enabled")]
    if not sites:
        raise HTTPException(status_code=400, detail="No enabled source sites configured")

    # Reset cycle state
    state = {
        "status": "scanning",
        "domains_started": [s["domain"] for s in sites],
        "domains_complete": [],
        "dedup_done": False,
        "last_complete_at": state.get("last_complete_at"),
    }
    _write_cycle(db, state)
    db.commit()

    async def _broadcast_cycle(new_state: dict) -> None:
        await manager.broadcast({"event": "cycle_status", **new_state})

    domain_task_ids: List[str] = []

    for site in sites:
        domain = site["domain"]

        async def _scan_domain(s=site) -> None:
            scan_sess = ScanSession(
                name=f"Parallel scan — {s['name']} {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
                session_type="source", target=s["domain"], status="pending",
            )
            with session_scope() as sess_db:
                sess_db.add(scan_sess)
                sess_db.flush()
                scan_id = scan_sess.id

            async def ws_cb(event: str, data: dict) -> None:
                await manager.broadcast({"event": event, "session_id": scan_id, **data})

            await run_source_scan(scan_session_id=scan_id, site_filter=s["domain"], progress_callbacks=[ws_cb])

            with session_scope() as upd_db:
                cyc = _read_cycle(upd_db)
                if s["domain"] not in cyc["domains_complete"]:
                    cyc["domains_complete"].append(s["domain"])
                if set(cyc["domains_complete"]) >= set(cyc["domains_started"]):
                    cyc["status"] = "dedup_running"
                _write_cycle(upd_db, cyc)
            await _broadcast_cycle(cyc)

        tid = _task_manager.submit(f"Scan {domain}", _scan_domain)
        domain_task_ids.append(tid)

    async def _run_dedup() -> None:
        with session_scope() as dd_db:
            engine = DeduplicationEngine()
            stats = engine.run(dd_db, None)
            cyc = _read_cycle(dd_db)
            cyc["dedup_done"] = True
            cyc["status"] = "review_pending"
            _write_cycle(dd_db, cyc)
        await manager.broadcast({"event": "dedup_complete", "stats": stats})
        await _broadcast_cycle(cyc)

    _task_manager.submit("Deduplication", _run_dedup, depends_on=domain_task_ids)

    return {"status": "started", "domains": [s["domain"] for s in sites], "task_ids": domain_task_ids}


# ---------------------------------------------------------------------------
# Domain Comparison — products on 2+ source domains with field differences
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# System of Record — treat one source domain as the truth and compare the
# others against it. Returns two lists per pair:
#   - missing:   products on primary that the compare-to domain doesn't carry
#   - differing: products on both, with at least one mismatched field
# ---------------------------------------------------------------------------

_SOR_COMPARE_FIELDS = ("title", "price", "manufacturer", "model_number", "sku")


def _latest_active_source_for_site(product, site):
    """Pick the most recently scraped active ProductSource for a given site."""
    best = None
    for s in product.sources:
        if not s.is_active or s.source_site != site:
            continue
        if best is None or (s.scraped_at and (not best.scraped_at or s.scraped_at > best.scraped_at)):
            best = s
    return best


def _source_payload(src):
    """Flatten a ProductSource into the dict the SoR UI consumes."""
    if not src:
        return None
    return {
        "title": src.source_title,
        "price": src.source_price,
        "manufacturer": src.source_manufacturer,
        "model_number": src.source_model_number,
        "sku": src.source_sku,
        "url": src.source_url,
        "scraped_at": src.scraped_at.isoformat() if src.scraped_at else None,
    }


def _norm(value):
    """Loose equality helper. Returns a string suitable for == comparison.
    Prices are rounded to the cent so float jitter doesn't flag a difference;
    None/empty strings collapse to '' so both 'absent on this domain' cases
    compare equal."""
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value).strip().lower()


@router.get("/api/system-of-record")
def system_of_record(
    primary: str = "donut-equipment.com",
    compare_to: str = "donut-supplies.com",
    db: Session = Depends(get_db_session),
):
    """List products present on `primary` that are either missing from
    `compare_to` or present on both with differing data."""
    # All master products that have an active source on `primary`
    primary_pids = {
        pid for (pid,) in
        db.query(ProductSource.product_id)
        .filter(ProductSource.source_site == primary, ProductSource.is_active == True)
        .distinct()
        .all()
    }
    compare_pids = {
        pid for (pid,) in
        db.query(ProductSource.product_id)
        .filter(ProductSource.source_site == compare_to, ProductSource.is_active == True)
        .distinct()
        .all()
    }

    missing_ids = primary_pids - compare_pids
    extra_ids = compare_pids - primary_pids
    both_ids = primary_pids & compare_pids

    missing = []
    extra = []
    differing = []

    if missing_ids:
        for p in (
            db.query(Product)
            .filter(Product.id.in_(missing_ids), Product.is_active == True)
            .order_by(Product.canonical_title)
            .all()
        ):
            src = _latest_active_source_for_site(p, primary)
            missing.append({
                "product_id": p.id,
                "canonical_title": p.canonical_title,
                "manufacturer": p.manufacturer,
                "model_number": p.model_number,
                "category": p.category,
                "primary": _source_payload(src),
            })

    if extra_ids:
        for p in (
            db.query(Product)
            .filter(Product.id.in_(extra_ids), Product.is_active == True)
            .order_by(Product.canonical_title)
            .all()
        ):
            src = _latest_active_source_for_site(p, compare_to)
            extra.append({
                "product_id": p.id,
                "canonical_title": p.canonical_title,
                "manufacturer": p.manufacturer,
                "model_number": p.model_number,
                "category": p.category,
                "compare": _source_payload(src),
            })

    matching = []
    if both_ids:
        for p in (
            db.query(Product)
            .filter(Product.id.in_(both_ids), Product.is_active == True)
            .order_by(Product.canonical_title)
            .all()
        ):
            p_src = _latest_active_source_for_site(p, primary)
            c_src = _latest_active_source_for_site(p, compare_to)
            p_data = _source_payload(p_src) or {}
            c_data = _source_payload(c_src) or {}
            diff_fields = [
                f for f in _SOR_COMPARE_FIELDS
                if _norm(p_data.get(f)) != _norm(c_data.get(f))
            ]
            entry = {
                "product_id": p.id,
                "canonical_title": p.canonical_title,
                "manufacturer": p.manufacturer,
                "model_number": p.model_number,
                "primary": p_data,
                "compare": c_data,
                "diff_fields": diff_fields,
            }
            if diff_fields:
                differing.append(entry)
            else:
                matching.append(entry)

    return {
        "primary": primary,
        "compare_to": compare_to,
        "primary_count": len(primary_pids),
        "compare_to_count": len(compare_pids),
        "missing": missing,
        "extra": extra,
        "differing": differing,
        "matching": matching,
        "missing_count": len(missing),
        "extra_count": len(extra),
        "differing_count": len(differing),
        "matching_count": len(matching),
        "both_count": len(both_ids),
    }


_FUZZY_TOKEN_RE = re.compile(r"[a-z0-9]+")
_FUZZY_STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "with", "of", "to", "in", "on", "by",
    "pack", "case", "set", "ct", "count", "size", "model", "new", "used",
    "donut", "bakery", "commercial",  # site-wide noise on this catalog
}


def _fuzzy_tokens(text: str) -> set:
    if not text:
        return set()
    return {t for t in _FUZZY_TOKEN_RE.findall(text.lower())
            if t not in _FUZZY_STOPWORDS and len(t) > 2}


@router.get("/api/system-of-record/fuzzy")
def system_of_record_fuzzy(
    primary: str = "donut-equipment.com",
    compare_to: str = "donut-supplies.com",
    threshold: float = 60.0,
    limit: int = 200,
    db: Session = Depends(get_db_session),
):
    """Find next-closest cross-domain product pairs that aren't linked yet.

    For each product whose master only has a source on `primary`, score every
    candidate whose master only has a source on `compare_to`. Return the best
    match per primary product if it's >= threshold. Helps the user spot
    almost-duplicates the dedup engine missed.

    To stay tractable on ~2k×~2k catalogs we prefilter candidates by
    overlapping significant-word tokens before running compute_confidence.
    """
    from backend.dedup.matchers import compute_confidence

    primary_only_ids = {
        pid for (pid,) in
        db.query(ProductSource.product_id)
        .filter(ProductSource.source_site == primary, ProductSource.is_active == True)
        .distinct().all()
    } - {
        pid for (pid,) in
        db.query(ProductSource.product_id)
        .filter(ProductSource.source_site == compare_to, ProductSource.is_active == True)
        .distinct().all()
    }
    compare_only_ids = {
        pid for (pid,) in
        db.query(ProductSource.product_id)
        .filter(ProductSource.source_site == compare_to, ProductSource.is_active == True)
        .distinct().all()
    } - {
        pid for (pid,) in
        db.query(ProductSource.product_id)
        .filter(ProductSource.source_site == primary, ProductSource.is_active == True)
        .distinct().all()
    }

    if not primary_only_ids or not compare_only_ids:
        return {
            "primary": primary, "compare_to": compare_to,
            "threshold": threshold, "limit": limit,
            "pairs": [], "pairs_count": 0,
            "primary_only_count": len(primary_only_ids),
            "compare_only_count": len(compare_only_ids),
        }

    primary_products = (
        db.query(Product).filter(Product.id.in_(primary_only_ids), Product.is_active == True).all()
    )
    compare_products = (
        db.query(Product).filter(Product.id.in_(compare_only_ids), Product.is_active == True).all()
    )

    # Token index for compare-side candidates to keep the comparison tractable.
    compare_index: Dict[str, List[Product]] = {}
    compare_tokens: Dict[int, set] = {}
    for cp in compare_products:
        toks = _fuzzy_tokens(cp.canonical_title)
        compare_tokens[cp.id] = toks
        for t in toks:
            compare_index.setdefault(t, []).append(cp)

    pairs = []
    for pp in primary_products:
        p_toks = _fuzzy_tokens(pp.canonical_title)
        if not p_toks:
            continue
        # Candidates = compare-side products that share ≥2 tokens with this title
        # (or ≥1 if the title is very short)
        candidate_scores: Dict[int, int] = {}
        for t in p_toks:
            for cp in compare_index.get(t, []):
                candidate_scores[cp.id] = candidate_scores.get(cp.id, 0) + 1
        min_overlap = 2 if len(p_toks) >= 3 else 1
        candidate_ids = [cid for cid, n in candidate_scores.items() if n >= min_overlap]
        if not candidate_ids:
            continue

        best = None
        for cid in candidate_ids:
            cp = next(c for c in compare_products if c.id == cid)
            confidence, factors = compute_confidence(
                price_a=pp.price_canonical, price_b=cp.price_canonical,
                model_a=pp.model_number, model_b=cp.model_number,
                manufacturer_a=pp.manufacturer, manufacturer_b=cp.manufacturer,
                title_a=pp.canonical_title, title_b=cp.canonical_title,
                desc_a=pp.canonical_description, desc_b=cp.canonical_description,
                sku_a=pp.sku, sku_b=cp.sku,
            )
            if confidence < threshold:
                continue
            if best is None or confidence > best["confidence"]:
                p_src = _latest_active_source_for_site(pp, primary)
                c_src = _latest_active_source_for_site(cp, compare_to)
                p_data = _source_payload(p_src) or {}
                c_data = _source_payload(c_src) or {}
                diff_fields = [
                    f for f in _SOR_COMPARE_FIELDS
                    if _norm(p_data.get(f)) != _norm(c_data.get(f))
                ]
                best = {
                    "confidence": confidence,
                    "factor_scores": factors,
                    "primary_product_id": pp.id,
                    "compare_product_id": cp.id,
                    "primary_title": pp.canonical_title,
                    "compare_title": cp.canonical_title,
                    "primary": p_data,
                    "compare": c_data,
                    "diff_fields": diff_fields,
                }
        if best:
            pairs.append(best)

    pairs.sort(key=lambda p: -p["confidence"])
    pairs = pairs[:limit]

    return {
        "primary": primary, "compare_to": compare_to,
        "threshold": threshold, "limit": limit,
        "pairs": pairs,
        "pairs_count": len(pairs),
        "primary_only_count": len(primary_only_ids),
        "compare_only_count": len(compare_only_ids),
    }


@router.get("/api/domain-comparison")
def get_domain_comparison(
    page: int = 1,
    per_page: int = 50,
    show_all: bool = False,
    db: Session = Depends(get_db_session),
):
    # Product IDs present on 2+ distinct active source sites
    multi_domain_ids = (
        db.query(ProductSource.product_id)
        .filter(ProductSource.is_active == True)
        .group_by(ProductSource.product_id)
        .having(func.count(func.distinct(ProductSource.source_site)) >= 2)
        .subquery()
    )

    products = (
        db.query(Product)
        .filter(Product.id.in_(multi_domain_ids), Product.is_active == True)
        .order_by(Product.canonical_title)
        .all()
    )

    results = []
    for product in products:
        # Latest active source per site
        site_sources: Dict[str, Any] = {}
        for src in sorted(product.sources, key=lambda s: s.scraped_at or datetime.min):
            if src.is_active:
                site_sources[src.source_site] = src

        if len(site_sources) < 2:
            continue

        sites_data = {
            site: {
                "title": src.source_title,
                "price": src.source_price,
                "manufacturer": src.source_manufacturer,
                "model_number": src.source_model_number,
                "sku": src.source_sku,
                "url": src.source_url,
                "scraped_at": src.scraped_at.isoformat() if src.scraped_at else None,
            }
            for site, src in site_sources.items()
        }

        diff_fields: List[str] = []
        for field in ("title", "price", "manufacturer", "model_number", "sku"):
            vals = [str(sites_data[s][field]) for s in site_sources if sites_data[s][field] is not None]
            if len(set(vals)) > 1:
                diff_fields.append(field)

        if not show_all and not diff_fields:
            continue

        results.append({
            "product_id": product.id,
            "canonical_title": product.canonical_title,
            "manufacturer": product.manufacturer,
            "model_number": product.model_number,
            "category": product.category,
            "domains": sites_data,
            "diff_fields": diff_fields,
        })

    total = len(results)
    start = (page - 1) * per_page
    page_data = results[start: start + per_page]

    all_domains = sorted({site for r in results for site in r["domains"]})

    return {
        "products": page_data,
        "total": total,
        "page": page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "all_domains": all_domains,
    }


# ---------------------------------------------------------------------------
# Log tail (dashboard live log viewer)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@router.get("/api/logs/tail")
def tail_log(lines: int = 8):
    log_path = _PROJECT_ROOT / "logs" / "donut_intel.log"
    if not log_path.exists():
        return {"lines": []}
    with open(log_path, "r", errors="replace") as f:
        tail = list(deque(f, maxlen=lines))
    return {"lines": [ln.rstrip("\n") for ln in tail]}


# ---------------------------------------------------------------------------
# Shopify Sync
# ---------------------------------------------------------------------------

_SHOPIFY_ATTR_GROUPS = [
    {
        "id": "core_identity",
        "label": "Core Identity",
        "icon": "🏷️",
        "description": "Title, handle, vendor, product type, tags, status",
        "fields": ["Title", "URL Handle", "Vendor", "Product Type", "Tags", "Published"],
        "commands": ["MERGE", "REPLACE"],
        "default_command": "MERGE",
    },
    {
        "id": "description",
        "label": "Description / Body HTML",
        "icon": "📝",
        "description": "Full product description (HTML body)",
        "fields": ["Body HTML"],
        "commands": ["MERGE", "REPLACE"],
        "default_command": "MERGE",
    },
    {
        "id": "seo",
        "label": "SEO",
        "icon": "🔍",
        "description": "SEO title and description",
        "fields": ["SEO Title", "SEO Description"],
        "commands": ["MERGE", "REPLACE"],
        "default_command": "MERGE",
    },
    {
        "id": "pricing",
        "label": "Pricing",
        "icon": "💲",
        "description": "Price, compare-at price, cost per item",
        "fields": ["Variant Price", "Variant Compare At Price", "Cost per item"],
        "commands": ["MERGE", "REPLACE"],
        "default_command": "MERGE",
    },
    {
        "id": "inventory",
        "label": "Inventory & Fulfillment",
        "icon": "📦",
        "description": "SKU, barcode, inventory policy, fulfillment service, quantity",
        "fields": [
            "Variant SKU", "Variant Barcode", "Variant Inventory Policy",
            "Variant Fulfillment Service", "Variant Inventory Qty",
            "Variant Inventory Tracker",
        ],
        "commands": ["MERGE", "REPLACE"],
        "default_command": "MERGE",
    },
    {
        "id": "shipping",
        "label": "Shipping",
        "icon": "🚚",
        "description": "Weight, weight unit, requires shipping, taxable",
        "fields": [
            "Variant Grams", "Variant Weight Unit",
            "Variant Requires Shipping", "Variant Taxable",
        ],
        "commands": ["MERGE", "REPLACE"],
        "default_command": "MERGE",
    },
    {
        "id": "options",
        "label": "Options / Variants",
        "icon": "🎨",
        "description": "Option names and values (size, color, etc.)",
        "fields": [
            "Option1 Name", "Option1 Value",
            "Option2 Name", "Option2 Value",
            "Option3 Name", "Option3 Value",
        ],
        "commands": ["MERGE", "REPLACE"],
        "default_command": "REPLACE",
    },
    {
        "id": "images",
        "label": "Images",
        "icon": "🖼️",
        "description": "Product and variant image URLs and alt text",
        "fields": [
            "Image Src", "Image Position", "Image Alt Text",
            "Variant Image",
        ],
        "commands": ["MERGE", "REPLACE"],
        "default_command": "MERGE",
    },
    {
        "id": "gift_card",
        "label": "Gift Card",
        "icon": "🎁",
        "description": "Gift card flag",
        "fields": ["Gift Card"],
        "commands": ["MERGE", "REPLACE"],
        "default_command": "MERGE",
    },
    {
        "id": "collections",
        "label": "Collections",
        "icon": "📁",
        "description": "Collection membership (Smart collection rules not exported)",
        "fields": ["Custom Collections"],
        "commands": ["MERGE", "REPLACE"],
        "default_command": "MERGE",
    },
    {
        "id": "metafields",
        "label": "Metafields",
        "icon": "🔧",
        "description": "Google Shopping and custom metafield columns",
        "fields": [
            "Google Shopping / Google Product Category",
            "Google Shopping / Gender",
            "Google Shopping / Age Group",
            "Google Shopping / MPN",
            "Google Shopping / Condition",
            "Google Shopping / Custom Product",
            "Google Shopping / Custom Label 0",
            "Google Shopping / Custom Label 1",
            "Google Shopping / Custom Label 2",
            "Google Shopping / Custom Label 3",
            "Google Shopping / Custom Label 4",
        ],
        "commands": ["MERGE", "REPLACE"],
        "default_command": "MERGE",
    },
    {
        "id": "variants_misc",
        "label": "Variant Misc",
        "icon": "⚙️",
        "description": "Tax code, HS code, country of origin",
        "fields": ["Variant Tax Code", "HS Code", "Country/Region of Origin"],
        "commands": ["MERGE", "REPLACE"],
        "default_command": "MERGE",
    },
    {
        "id": "status",
        "label": "Status / Visibility",
        "icon": "👁️",
        "description": "Published status and sales channel visibility",
        "fields": ["Published", "Status"],
        "commands": ["MERGE", "REPLACE"],
        "default_command": "MERGE",
    },
]

_SHOPIFY_CSV_HEADERS = [
    "Handle", "Title", "Body HTML", "Vendor", "Product Category", "Type",
    "Tags", "Published", "Option1 Name", "Option1 Value", "Option2 Name",
    "Option2 Value", "Option3 Name", "Option3 Value", "Variant SKU",
    "Variant Grams", "Variant Inventory Tracker", "Variant Inventory Qty",
    "Variant Inventory Policy", "Variant Fulfillment Service",
    "Variant Price", "Variant Compare At Price", "Variant Requires Shipping",
    "Variant Taxable", "Variant Barcode", "Image Src", "Image Position",
    "Image Alt Text", "Gift Card", "SEO Title", "SEO Description",
    "Google Shopping / Google Product Category", "Google Shopping / Gender",
    "Google Shopping / Age Group", "Google Shopping / MPN",
    "Google Shopping / Condition", "Google Shopping / Custom Product",
    "Google Shopping / Custom Label 0", "Google Shopping / Custom Label 1",
    "Google Shopping / Custom Label 2", "Google Shopping / Custom Label 3",
    "Google Shopping / Custom Label 4", "Variant Image",
    "Variant Weight Unit", "Variant Tax Code", "Cost per item",
    "Status",
]


def _shopify_handle(source_url: str) -> str:
    """Extract Shopify product handle from a source URL."""
    if not source_url:
        return ""
    try:
        path = urlparse(source_url).path.rstrip("/")
        return path.split("/")[-1]
    except Exception:
        return ""


def _build_shopify_rows(
    product,
    source,
    selected_groups: dict,
) -> list:
    """Build one or more Shopify CSV rows for a product/source pair."""
    rows = []
    handle = _shopify_handle(source.source_url) if source and source.source_url else ""
    if not handle:
        handle = re.sub(r"[^a-z0-9-]", "-", (product.canonical_title or "product").lower())[:200]

    active_fields: set = set()
    for group in _SHOPIFY_ATTR_GROUPS:
        if selected_groups.get(group["id"]):
            active_fields.update(group["fields"])

    def pick(field: str, src_val, prod_val=""):
        if field not in active_fields:
            return ""
        return str(src_val) if src_val not in (None, "") else (str(prod_val) if prod_val not in (None, "") else "")

    images = list(product.images) if product.images else []
    options = list(product.options) if hasattr(product, "options") and product.options else []
    first_image = images[0] if images else None

    base: dict = {h: "" for h in _SHOPIFY_CSV_HEADERS}
    base["Handle"] = handle
    base["Title"] = pick("Title", source.source_title if source else None, product.canonical_title)
    base["Body HTML"] = pick("Body HTML", source.source_description if source else None, product.canonical_description)
    base["Vendor"] = pick("Vendor", source.source_manufacturer if source else None, product.manufacturer)
    base["Type"] = pick("Product Type", source.source_category if source else None, product.category)
    base["Published"] = pick("Published", None, "TRUE") or "TRUE"

    # Tags: from product tags relationship
    if "Tags" in active_fields:
        tags = [t.tag for t in product.tags] if hasattr(product, "tags") and product.tags else []
        base["Tags"] = ", ".join(tags)

    base["Variant SKU"] = pick("Variant SKU", source.source_sku if source else None, product.sku)
    base["Variant Price"] = pick("Variant Price", source.source_price if source else None, product.price_canonical)
    base["Variant Requires Shipping"] = "TRUE" if "Variant Requires Shipping" in active_fields else ""
    base["Variant Taxable"] = "TRUE" if "Variant Taxable" in active_fields else ""
    base["Variant Inventory Policy"] = "deny" if "Variant Inventory Policy" in active_fields else ""
    base["Variant Fulfillment Service"] = "manual" if "Variant Fulfillment Service" in active_fields else ""
    base["Status"] = "active" if "Status" in active_fields else ""

    # Options (group option_group/option_value into up to 3 Option slots)
    if options and any(f.startswith("Option") for f in active_fields):
        seen_groups: dict = {}
        for opt in options:
            g = opt.option_group or "Option"
            if g not in seen_groups:
                seen_groups[g] = []
            seen_groups[g].append(opt.option_value or "")
        for i, (grp, vals) in enumerate(list(seen_groups.items())[:3], start=1):
            base[f"Option{i} Name"] = grp
            base[f"Option{i} Value"] = vals[0] if vals else ""

    # First image
    if first_image and "Image Src" in active_fields:
        base["Image Src"] = first_image.source_url or ""
        base["Image Position"] = "1"
        base["Image Alt Text"] = first_image.alt_text or ""

    rows.append(base)

    # Additional image rows
    if "Image Src" in active_fields:
        for pos, img in enumerate(images[1:], start=2):
            row = {h: "" for h in _SHOPIFY_CSV_HEADERS}
            row["Handle"] = handle
            row["Image Src"] = img.source_url or ""
            row["Image Position"] = str(pos)
            row["Image Alt Text"] = img.alt_text or ""
            rows.append(row)

    return rows


def _make_csv_bytes(rows: list) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_SHOPIFY_CSV_HEADERS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return ("﻿" + buf.getvalue()).encode("utf-8")


@router.put("/api/source-sites/{domain}/destination")
def set_source_site_destination(domain: str, payload: Dict[str, bool] = Body(...)):
    is_dest = payload.get("is_destination", False)
    sites = config.get("source_sites", default=[])
    if is_dest:
        current = sum(1 for s in sites if s.get("is_destination") and s.get("domain") != domain)
        if current >= 2:
            raise HTTPException(status_code=400, detail="Maximum 2 destination stores allowed")
    matched = False
    for site in sites:
        if site.get("domain") == domain:
            site["is_destination"] = is_dest
            matched = True
            break
    if not matched:
        raise HTTPException(status_code=404, detail=f"Source site not found: {domain}")
    config._settings["source_sites"] = sites
    config._save()
    return {"status": "saved", "domain": domain, "is_destination": is_dest}


@router.get("/api/shopify/connection-log")
def shopify_connection_log(n: int = 150):
    """Recent Shopify store connection attempts (for the Settings troubleshooting panel)."""
    from backend.shopify import connlog
    return {"lines": connlog.get_lines(n)}


@router.post("/api/shopify/connection-log/clear")
def shopify_connection_log_clear():
    from backend.shopify import connlog
    connlog.clear()
    return {"status": "cleared"}


@router.get("/api/shopify-sync/config")
def shopify_sync_config():
    """Return attribute groups and available source sites."""
    source_sites = [
        {
            "domain": s["domain"],
            "name": s.get("name", s["domain"]),
            "is_destination": s.get("is_destination", False),
        }
        for s in config.get("source_sites", default=[])
        if s.get("enabled", True)
    ]
    return {"attribute_groups": _SHOPIFY_ATTR_GROUPS, "source_sites": source_sites}


class ShopifySyncRequest(BaseModel):
    source_site: str
    selected_groups: Dict[str, str] = {}  # group_id -> "MERGE"|"REPLACE"|"SKIP"
    product_scope: str = "all"  # "all" | "source_only" | "diffs_only"
    search: Optional[str] = None
    product_ids: Optional[List[int]] = None


def _get_sync_products(req: ShopifySyncRequest, db):
    """Fetch products + their source listings for a sync request."""
    known_domains = {s["domain"] for s in config.get("source_sites", default=[]) if s.get("enabled", True)}
    if req.source_site not in known_domains:
        raise HTTPException(status_code=400, detail=f"Unknown source site: {req.source_site}")

    q = db.query(Product).options(
        joinedload(Product.sources),
        joinedload(Product.images),
    )

    if req.product_ids:
        q = q.filter(Product.id.in_(req.product_ids))

    if req.search:
        term = f"%{req.search}%"
        q = q.filter(
            (Product.canonical_title.ilike(term))
            | (Product.sku.ilike(term))
            | (Product.model_number.ilike(term))
        )

    products = q.all()
    pairs = []
    for product in products:
        source = next(
            (src for src in product.sources if src.source_site == req.source_site),
            None,
        )
        if req.product_scope == "source_only" and source is None:
            continue
        if req.product_scope == "diffs_only":
            if source is None:
                continue
            has_diff = (
                (source.source_title or '') != (product.canonical_title or '')
                or (source.source_sku or '') != (product.sku or '')
                or source.source_price != product.price_canonical
            )
            if not has_diff:
                continue
        pairs.append((product, source))
    return pairs


@router.post("/api/shopify-sync/preview")
def shopify_sync_preview(req: ShopifySyncRequest, db: Session = Depends(get_db_session)):
    pairs = _get_sync_products(req, db)
    active_groups = {
        gid: cmd for gid, cmd in req.selected_groups.items() if cmd != "SKIP"
    }
    all_rows = []
    sample_rows = []
    for product, source in pairs:
        rows = _build_shopify_rows(product, source, active_groups)
        all_rows.extend(rows)
        if len(sample_rows) < 10:
            sample_rows.extend(rows[:3])

    return {
        "product_count": len(pairs),
        "row_count": len(all_rows),
        "sample": sample_rows[:10],
    }


@router.post("/api/shopify-sync/export")
def shopify_sync_export(req: ShopifySyncRequest, db: Session = Depends(get_db_session)):
    pairs = _get_sync_products(req, db)
    active_groups = {
        gid: cmd for gid, cmd in req.selected_groups.items() if cmd != "SKIP"
    }
    all_rows = []
    for product, source in pairs:
        rows = _build_shopify_rows(product, source, active_groups)
        all_rows.extend(rows)

    csv_bytes = _make_csv_bytes(all_rows)
    from fastapi.responses import Response
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=shopify_sync_export.csv"},
    )


# ---------------------------------------------------------------------------
# Shopify Live Sync  (scan → diff → execute via Admin API)
# ---------------------------------------------------------------------------

# domain -> {"token": str, "expires_at": float}
_shopify_token_cache: Dict[str, Dict] = {}


async def _get_site_credentials(domain: str):
    """Return (store_url, access_token) for a domain, fetching a fresh token via client credentials if needed."""
    sites = config.get("source_sites", default=[])
    site = next((s for s in sites if s.get("domain") == domain), None)
    if site is None:
        raise HTTPException(status_code=404, detail=f"Unknown source site: {domain}")

    store_url = (site.get("shopify_store_url") or "").strip()
    client_id = (site.get("shopify_client_id") or "").strip()
    client_secret = (site.get("shopify_client_secret") or "").strip()

    if not store_url or not client_id or not client_secret:
        raise HTTPException(
            status_code=422,
            detail=f"Shopify credentials not configured for {domain}. "
                   "Add Store URL, Client ID, and Client Secret in Settings.",
        )

    cached = _shopify_token_cache.get(domain, {})
    # Refresh 5 minutes before expiry
    if cached and cached.get("expires_at", 0) - time.time() > 300:
        return store_url, cached["token"]

    from backend.shopify.client import fetch_access_token, ShopifyError
    try:
        token = await fetch_access_token(store_url, client_id, client_secret)
    except ShopifyError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to obtain Shopify token for {domain}: {exc}")

    _shopify_token_cache[domain] = {"token": token, "expires_at": time.time() + 86399}
    return store_url, token


# In-memory scan cache: domain -> snapshot dict
# (cleared on server restart; use for single-session diff workflows)
_scan_cache: Dict[str, Any] = {}


class LiveScanRequest(BaseModel):
    domain: str


class LiveDiffRequest(BaseModel):
    source_domain: str
    dest_domain: str
    selected_fields: Optional[List[str]] = None
    include_deletes: bool = False
    include_new: bool = True


class LiveExecuteRequest(BaseModel):
    dest_domain: str
    transactions: List[Dict]   # full transaction dicts with approved field set


@router.post("/api/shopify-live/scan")
async def shopify_live_scan(req: LiveScanRequest):
    """Fetch full product/collection/metafield snapshot from a Shopify store."""
    store_url, token = await _get_site_credentials(req.domain)
    from backend.shopify.scanner import scan_store

    progress_log: List[str] = []

    def _cb(stage: str, done: int, total: int):
        msg = f"{stage}: {done}/{total}" if total else stage
        progress_log.append(msg)

    try:
        snapshot = await scan_store(store_url, token, progress_cb=_cb)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Scan failed: {exc}")

    # Cache snapshot (strip large HTML bodies to save memory)
    _scan_cache[req.domain] = snapshot

    return {
        "domain": req.domain,
        "shop_name": snapshot["shop"].get("name", ""),
        "product_count": len(snapshot["products"]),
        "collection_count": len(snapshot["collections"]),
        "metafield_product_count": len(snapshot["metafields"]),
        "progress": progress_log,
    }


@router.get("/api/shopify-live/scan-status")
def shopify_scan_status():
    """Return which domains have a cached scan snapshot."""
    return {
        domain: {
            "product_count": len(snap["products"]),
            "shop_name": snap["shop"].get("name", ""),
        }
        for domain, snap in _scan_cache.items()
    }


@router.post("/api/shopify-live/diff")
async def shopify_live_diff(req: LiveDiffRequest):
    """
    Diff source domain snapshot against destination domain snapshot.
    Both must have been scanned first (or will be scanned on demand).
    """
    # Ensure both snapshots exist — scan on demand if missing
    for domain in (req.source_domain, req.dest_domain):
        if domain not in _scan_cache:
            store_url, token = await _get_site_credentials(domain)
            from backend.shopify.scanner import scan_store
            try:
                _scan_cache[domain] = await scan_store(store_url, token)
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Scan of {domain} failed: {exc}")

    from backend.shopify.differ import diff_stores
    transactions = diff_stores(
        source=_scan_cache[req.source_domain],
        dest=_scan_cache[req.dest_domain],
        selected_fields=req.selected_fields,
        include_deletes=req.include_deletes,
        include_new=req.include_new,
    )

    # Strip large HTML from transactions before sending to browser
    for t in transactions:
        if t.get("field") == "Description (HTML)":
            for k in ("old_value", "new_value"):
                if isinstance(t.get(k), str) and len(t[k]) > 300:
                    t[k] = t[k][:300] + "…"
        # Don't send full source_product in meta to keep payload small
        if "source_product" in t.get("meta", {}):
            sp = t["meta"]["source_product"]
            t["meta"]["source_product"] = {
                k: sp[k] for k in ("id", "handle", "title", "status")
                if k in sp
            }

    risk_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    for t in transactions:
        risk_counts[t["risk_level"]] = risk_counts.get(t["risk_level"], 0) + 1

    return {
        "source_domain": req.source_domain,
        "dest_domain": req.dest_domain,
        "total": len(transactions),
        "risk_counts": risk_counts,
        "transactions": transactions,
    }


@router.post("/api/shopify-live/execute")
async def shopify_live_execute(req: LiveExecuteRequest):
    """Execute approved transactions against the destination store."""
    store_url, token = await _get_site_credentials(req.dest_domain)
    from backend.shopify.executor import execute_transactions

    approved_count = sum(1 for t in req.transactions if t.get("approved") is True)
    if approved_count == 0:
        return {"status": "nothing_to_do", "results": []}

    results = await execute_transactions(store_url, token, req.transactions)

    ok = sum(1 for r in results if r["status"] == "ok")
    errors = [r for r in results if r["status"] == "error"]

    return {
        "status": "complete",
        "approved": approved_count,
        "ok": ok,
        "errors": len(errors),
        "error_details": errors[:20],
        "results": results,
    }


# ---------------------------------------------------------------------------
# Shopify Webhook Management
# ---------------------------------------------------------------------------

@router.get("/api/shopify-webhooks/{domain}/live")
async def list_live_webhooks(domain: str):
    """Fetch the current webhook list directly from Shopify."""
    store_url, token = await _get_site_credentials(domain)
    from backend.shopify.client import ShopifyClient, ShopifyError
    try:
        async with ShopifyClient(store_url, token) as client:
            webhooks = await client.list_webhooks()
    except ShopifyError as e:
        raise HTTPException(status_code=e.status,
                            detail=f"Shopify error {e.status}: {e.body[:300]}")
    except Exception as e:
        raise HTTPException(status_code=502,
                            detail=f"Could not reach Shopify store: {e}")
    return {"domain": domain, "webhooks": webhooks, "count": len(webhooks)}


@router.get("/api/shopify-webhooks/{domain}/saved")
def list_saved_webhooks(domain: str, db: Session = Depends(get_db_session)):
    """Return webhook definitions saved to the local DB for this store."""
    rows = (
        db.query(ShopifySavedWebhook)
        .filter(ShopifySavedWebhook.store_domain == domain)
        .order_by(ShopifySavedWebhook.saved_at.desc())
        .all()
    )
    return {
        "domain": domain,
        "webhooks": [
            {
                "id": r.id,
                "shopify_webhook_id": r.shopify_webhook_id,
                "topic": r.topic,
                "address": r.address,
                "format": r.format,
                "api_version": r.api_version,
                "is_active_in_shopify": r.is_active_in_shopify,
                "saved_at": r.saved_at.isoformat() if r.saved_at else None,
                "deleted_from_shopify_at": r.deleted_from_shopify_at.isoformat()
                    if r.deleted_from_shopify_at else None,
                "restored_at": r.restored_at.isoformat() if r.restored_at else None,
            }
            for r in rows
        ],
        "active_count": sum(1 for r in rows if r.is_active_in_shopify),
        "disabled_count": sum(1 for r in rows if not r.is_active_in_shopify),
    }


@router.post("/api/shopify-webhooks/{domain}/save-and-disable")
async def save_and_disable_webhooks(domain: str, db: Session = Depends(get_db_session)):
    """
    Fetch all live webhooks, save them to DB, then delete them from Shopify.
    Use this before a bulk import to prevent webhooks from firing.
    """
    store_url, token = await _get_site_credentials(domain)
    from backend.shopify.client import ShopifyClient

    async with ShopifyClient(store_url, token) as client:
        live_webhooks = await client.list_webhooks()
        deleted_ids = []
        errors = []
        for wh in live_webhooks:
            # Upsert into saved table
            existing = (
                db.query(ShopifySavedWebhook)
                .filter(
                    ShopifySavedWebhook.store_domain == domain,
                    ShopifySavedWebhook.shopify_webhook_id == str(wh["id"]),
                )
                .first()
            )
            if existing:
                existing.topic = wh.get("topic", "")
                existing.address = wh.get("address", "")
                existing.format = wh.get("format", "json")
                existing.api_version = wh.get("api_version")
                existing.is_active_in_shopify = True
                existing.saved_at = datetime.utcnow()
            else:
                db.add(ShopifySavedWebhook(
                    store_domain=domain,
                    shopify_webhook_id=str(wh["id"]),
                    topic=wh.get("topic", ""),
                    address=wh.get("address", ""),
                    format=wh.get("format", "json"),
                    api_version=wh.get("api_version"),
                    is_active_in_shopify=True,
                ))
        db.flush()

        # Now delete each one from Shopify
        for wh in live_webhooks:
            try:
                await client.delete_webhook(wh["id"])
                deleted_ids.append(wh["id"])
                # Mark as deleted in DB
                saved = (
                    db.query(ShopifySavedWebhook)
                    .filter(
                        ShopifySavedWebhook.store_domain == domain,
                        ShopifySavedWebhook.shopify_webhook_id == str(wh["id"]),
                    )
                    .first()
                )
                if saved:
                    saved.is_active_in_shopify = False
                    saved.deleted_from_shopify_at = datetime.utcnow()
            except Exception as e:
                errors.append({"id": wh["id"], "error": str(e)})

    db.commit()
    return {
        "status": "complete",
        "saved": len(live_webhooks),
        "deleted": len(deleted_ids),
        "errors": errors,
    }


@router.post("/api/shopify-webhooks/{domain}/restore")
async def restore_webhooks(domain: str, db: Session = Depends(get_db_session)):
    """
    Re-create all saved-but-deleted webhooks in Shopify.
    Use this after a bulk import completes.
    """
    store_url, token = await _get_site_credentials(domain)
    from backend.shopify.client import ShopifyClient

    disabled = (
        db.query(ShopifySavedWebhook)
        .filter(
            ShopifySavedWebhook.store_domain == domain,
            ShopifySavedWebhook.is_active_in_shopify == False,  # noqa: E712
        )
        .all()
    )
    if not disabled:
        return {"status": "nothing_to_restore", "restored": 0}

    restored = []
    errors = []
    async with ShopifyClient(store_url, token) as client:
        for saved in disabled:
            try:
                new_wh = await client.create_webhook(saved.topic, saved.address, saved.format or "json")
                saved.shopify_webhook_id = str(new_wh.get("id", ""))
                saved.is_active_in_shopify = True
                saved.restored_at = datetime.utcnow()
                restored.append(saved.topic)
            except Exception as e:
                errors.append({"topic": saved.topic, "address": saved.address, "error": str(e)})

    db.commit()
    return {
        "status": "complete",
        "restored": len(restored),
        "restored_topics": restored,
        "errors": errors,
    }


@router.delete("/api/shopify-webhooks/{domain}/live/{webhook_id}")
async def delete_single_webhook(domain: str, webhook_id: int,
                                db: Session = Depends(get_db_session)):
    """Delete a single live webhook from Shopify (and mark it in the local DB if saved)."""
    store_url, token = await _get_site_credentials(domain)
    from backend.shopify.client import ShopifyClient

    async with ShopifyClient(store_url, token) as client:
        await client.delete_webhook(webhook_id)

    # Mark as inactive if we have it saved
    saved = (
        db.query(ShopifySavedWebhook)
        .filter(
            ShopifySavedWebhook.store_domain == domain,
            ShopifySavedWebhook.shopify_webhook_id == str(webhook_id),
        )
        .first()
    )
    if saved:
        saved.is_active_in_shopify = False
        saved.deleted_from_shopify_at = datetime.utcnow()
        db.commit()

    return {"status": "deleted", "webhook_id": webhook_id}


# ---------------------------------------------------------------------------
# Shopify Product ID Mapping
# ---------------------------------------------------------------------------

class UpsertProductMappingRequest(BaseModel):
    handle: str
    title: Optional[str] = None
    sku: Optional[str] = None
    local_product_id: Optional[int] = None
    store_domain: str
    shopify_product_id: str
    variant_id_map: Optional[Dict[str, str]] = None


@router.post("/api/shopify-product-mappings")
def upsert_product_mapping(req: UpsertProductMappingRequest,
                           db: Session = Depends(get_db_session)):
    """Create or update the mapping between a Shopify product ID and a local product."""
    mapping = (
        db.query(ShopifyProductMapping)
        .filter(ShopifyProductMapping.handle == req.handle)
        .first()
    )
    if not mapping:
        mapping = ShopifyProductMapping(
            handle=req.handle,
            title=req.title,
            sku=req.sku,
            local_product_id=req.local_product_id,
        )
        db.add(mapping)
        db.flush()
    else:
        if req.title:
            mapping.title = req.title
        if req.sku:
            mapping.sku = req.sku
        if req.local_product_id:
            mapping.local_product_id = req.local_product_id

    store_entry = (
        db.query(ShopifyStoreProductId)
        .filter(
            ShopifyStoreProductId.mapping_id == mapping.id,
            ShopifyStoreProductId.store_domain == req.store_domain,
        )
        .first()
    )
    if store_entry:
        store_entry.shopify_product_id = req.shopify_product_id
        store_entry.variant_id_map_json = json.dumps(req.variant_id_map) if req.variant_id_map else None
        store_entry.synced_at = datetime.utcnow()
    else:
        db.add(ShopifyStoreProductId(
            mapping_id=mapping.id,
            store_domain=req.store_domain,
            shopify_product_id=req.shopify_product_id,
            variant_id_map_json=json.dumps(req.variant_id_map) if req.variant_id_map else None,
        ))

    db.commit()
    return {"status": "ok", "mapping_id": mapping.id}


@router.get("/api/shopify-product-mappings")
def get_product_mappings(
    handle: Optional[str] = None,
    sku: Optional[str] = None,
    local_product_id: Optional[int] = None,
    store_domain: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
    db: Session = Depends(get_db_session),
):
    """Query product ID mappings across stores."""
    q = db.query(ShopifyProductMapping)
    if handle:
        q = q.filter(ShopifyProductMapping.handle.ilike(f"%{handle}%"))
    if sku:
        q = q.filter(ShopifyProductMapping.sku.ilike(f"%{sku}%"))
    if local_product_id:
        q = q.filter(ShopifyProductMapping.local_product_id == local_product_id)
    if store_domain:
        q = q.join(ShopifyStoreProductId).filter(
            ShopifyStoreProductId.store_domain == store_domain
        )

    total = q.count()
    mappings = q.offset((page - 1) * per_page).limit(per_page).all()

    results = []
    for m in mappings:
        store_ids = {
            s.store_domain: {
                "shopify_product_id": s.shopify_product_id,
                "variant_id_map": json.loads(s.variant_id_map_json) if s.variant_id_map_json else None,
                "synced_at": s.synced_at.isoformat() if s.synced_at else None,
            }
            for s in m.store_ids
        }
        results.append({
            "id": m.id,
            "local_product_id": m.local_product_id,
            "handle": m.handle,
            "title": m.title,
            "sku": m.sku,
            "store_ids": store_ids,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })

    return {"total": total, "page": page, "pages": max(1, (total + per_page - 1) // per_page),
            "mappings": results}
