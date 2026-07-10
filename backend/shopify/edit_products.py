"""Projection + query layer for the Edit Products page.

The Edit Products page shows every product from the *most recent store scan*,
flattened to **one row per variant**, and lets the user search/filter/sort by
any attribute. This module turns two very different data shapes into a single
uniform row schema:

  * **scan snapshot** (preferred) — the raw Shopify Admin-API product objects
    persisted by ``scan_cache``. Richest source: title, body_html, vendor,
    product_type, status, tags, collections, variants (price/sku/weight/…),
    images.
  * **DB fallback** — the canonical ``Product`` / ``ProductSource`` records for
    stores that have not been scanned recently. Best-effort projection so the
    page still lists those stores' products.

Unlike the sync flow, this page always loads the *latest* snapshot regardless
of the ``scan_cache`` freshness TTL — the user is editing "the most recent
scan", however old. The age is surfaced so the UI can warn about staleness.

Nothing here writes to Shopify. Write-back (Phase 4) converts staged edits into
executor transactions elsewhere.
"""
from __future__ import annotations

import html
import json
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.config import config
from backend.shopify import scan_cache

logger = logging.getLogger(__name__)

# The page always shows the most recent scan, so the scan_cache TTL is bypassed
# with an effectively-infinite max age. Staleness is reported, not enforced.
_ANY_AGE_DAYS = 10_000_000

# The canonical, ordered column set. The frontend renders these in order; the
# projection guarantees every row carries every key (never KeyError in the UI).
COLUMNS: List[str] = [
    "store", "data_source", "status", "title", "vendor", "product_type", "category",
    "sku", "barcode", "price", "compare_at_price", "weight", "weight_unit",
    "inventory_quantity", "variant_title", "option1", "option2", "option3",
    "tags", "collections", "image_count",
    "description", "handle",
]

# Which columns sort numerically rather than lexically.
_NUMERIC_COLS = {"price", "compare_at_price", "weight", "inventory_quantity", "image_count"}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _plain(text_value: Optional[str], limit: int = 400) -> str:
    """Strip HTML, decode entities, collapse whitespace, truncate for display."""
    if not text_value:
        return ""
    no_tags = _TAG_RE.sub(" ", text_value)
    decoded = html.unescape(no_tags)
    collapsed = _WS_RE.sub(" ", decoded).strip()
    if len(collapsed) > limit:
        collapsed = collapsed[:limit].rstrip() + "…"
    return collapsed


def _f(value: Any) -> Optional[float]:
    """Coerce a Shopify price/weight string to float, or None."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Snapshot projection (preferred data source)
# ---------------------------------------------------------------------------
# Parsing a 20MB snapshot per request is wasteful, so projected rows are cached
# per store and invalidated by the cache file's mtime.
_ROWS_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
_INFO_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def _project_snapshot(domain: str, snap: Dict[str, Any]) -> List[Dict[str, Any]]:
    products = snap.get("products") or {}
    collections = snap.get("collections") or {}
    prod_cols = snap.get("product_collections") or {}
    rows: List[Dict[str, Any]] = []

    for handle, p in products.items():
        pid = p.get("id")
        # product_collections is keyed by str(product_id); collection ids in the
        # list are ints and collections is keyed by str(collection_id).
        col_ids = prod_cols.get(str(pid)) or prod_cols.get(pid) or []
        col_names = []
        for cid in col_ids:
            c = collections.get(str(cid)) or collections.get(cid)
            if c and c.get("title"):
                col_names.append(c["title"])
        tags = [t.strip() for t in (p.get("tags") or "").split(",") if t.strip()]
        images = p.get("images") or []
        if images:
            primary_image = images[0].get("src") or ""
        else:
            primary_image = ((p.get("image") or {}) or {}).get("src") or ""
        desc = _plain(p.get("body_html"))
        variants = p.get("variants") or [{}]
        for v in variants:
            vtitle = v.get("title") or ""
            if vtitle == "Default Title":
                vtitle = ""
            # Shopify's synthetic single-variant carries option1 == "Default
            # Title" too; blank it so the grid isn't full of noise.
            opt = lambda k: "" if v.get(k) in (None, "Default Title") else v.get(k)
            rows.append({
                "row_id": f"{domain}|{pid}|{v.get('id') or ''}",
                "store": domain,
                "data_source": "scan",
                "product_id": str(pid) if pid is not None else "",
                "variant_id": str(v.get("id") or ""),
                "handle": handle or "",
                "title": p.get("title") or "",
                "vendor": p.get("vendor") or "",
                "product_type": p.get("product_type") or "",
                # Shopify's taxonomy Category isn't captured in these snapshots;
                # blank until a rescan fetches it. Editable but not pushed yet.
                "category": "",
                "status": p.get("status") or "",
                "tags": tags,
                "collections": col_names,
                "description": desc,
                "image_count": len(images),
                "primary_image": primary_image,
                "variant_title": vtitle,
                "sku": v.get("sku") or "",
                "barcode": v.get("barcode") or "",
                "price": _f(v.get("price")),
                "compare_at_price": _f(v.get("compare_at_price")),
                "weight": _f(v.get("weight")),
                "weight_unit": v.get("weight_unit") or "",
                "inventory_quantity": v.get("inventory_quantity"),
                "option1": opt("option1"),
                "option2": opt("option2"),
                "option3": opt("option3"),
                "url": f"https://{domain}/products/{handle}" if handle else "",
            })
    return rows


def _snapshot_rows(domain: str) -> Optional[List[Dict[str, Any]]]:
    """Projected variant rows from ``domain``'s latest snapshot, or None."""
    path = scan_cache._path(domain)
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    cached = _ROWS_CACHE.get(domain)
    if cached and cached[0] == mtime:
        return cached[1]
    snap = scan_cache.load_snapshot(domain, max_age_days=_ANY_AGE_DAYS)
    if not snap:
        _ROWS_CACHE.pop(domain, None)
        return None
    rows = _project_snapshot(domain, snap)
    _ROWS_CACHE[domain] = (mtime, rows)
    return rows


# ---------------------------------------------------------------------------
# DB projection (fallback for stores without a recent scan)
# ---------------------------------------------------------------------------
def _chunks(seq: List[Any], size: int = 900) -> Iterable[List[Any]]:
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _project_db(db, domain: str) -> List[Dict[str, Any]]:
    from backend.database.models import (
        Product, ProductImage, ProductOption, ProductSource, ProductTag,
    )

    srcs = (
        db.query(ProductSource)
        .filter(ProductSource.source_site == domain, ProductSource.is_active == True)  # noqa: E712
        .all()
    )
    if not srcs:
        return []

    pids = list({s.product_id for s in srcs if s.product_id is not None})
    products: Dict[int, Product] = {}
    tags_by: Dict[int, List[str]] = {}
    opts_by: Dict[int, List[ProductOption]] = {}
    imgs_by: Dict[int, List[ProductImage]] = {}
    for chunk in _chunks(pids):
        for p in db.query(Product).filter(Product.id.in_(chunk)).all():
            products[p.id] = p
        for t in db.query(ProductTag).filter(ProductTag.product_id.in_(chunk)).all():
            tags_by.setdefault(t.product_id, []).append(t.tag)
        for o in db.query(ProductOption).filter(ProductOption.product_id.in_(chunk)).all():
            if o.source_site in (domain, None):
                opts_by.setdefault(o.product_id, []).append(o)
        for im in db.query(ProductImage).filter(ProductImage.product_id.in_(chunk)).all():
            if im.source_site in (domain, None):
                imgs_by.setdefault(im.product_id, []).append(im)

    rows: List[Dict[str, Any]] = []
    for s in srcs:
        p = products.get(s.product_id)
        imgs = imgs_by.get(s.product_id, [])
        primary_image = ""
        for im in imgs:
            if im.is_primary:
                primary_image = im.source_url or ""
                break
        if not primary_image and imgs:
            primary_image = imgs[0].source_url or ""
        base = {
            "store": domain,
            "data_source": "db",
            "product_id": str(s.product_id) if s.product_id is not None else "",
            "handle": (p.parent_handle if p else "") or "",
            "title": s.source_title or (p.canonical_title if p else "") or "",
            "vendor": s.source_manufacturer or (p.manufacturer if p else "") or "",
            "product_type": s.source_category or (p.category if p else "") or "",
            "category": (p.category if p else "") or "",
            "status": s.source_status or "",
            "tags": tags_by.get(s.product_id, []),
            "collections": [],  # collection membership isn't tracked in the DB
            "description": _plain(s.source_description or (p.canonical_description if p else "")),
            "image_count": len(imgs),
            "primary_image": primary_image,
            "barcode": "",
            "weight": (p.weight if p else None),
            "weight_unit": "",
            "inventory_quantity": None,
            "url": s.source_url or "",
        }
        opts = opts_by.get(s.product_id, [])
        if opts:
            for o in opts:
                price = s.source_price
                if price is not None and o.price_modifier:
                    price = price + o.price_modifier
                sku = s.source_sku or ""
                if o.sku_suffix:
                    sku = f"{sku}{o.sku_suffix}"
                rows.append({
                    **base,
                    "row_id": f"{domain}|{s.product_id}|{o.id}",
                    "variant_id": str(o.id),
                    "variant_title": " / ".join(x for x in [o.option_group, o.option_value] if x),
                    "sku": sku,
                    "price": _f(price),
                    "compare_at_price": None,
                    "option1": o.option_value or "",
                    "option2": "",
                    "option3": "",
                })
        else:
            rows.append({
                **base,
                "row_id": f"{domain}|{s.product_id}|{s.id}",
                "variant_id": str(s.id),
                "variant_title": "",
                "sku": s.source_sku or "",
                "price": _f(s.source_price),
                "compare_at_price": None,
                "option1": "",
                "option2": "",
                "option3": "",
            })
    return rows


def _store_rows(db, domain: str) -> Tuple[List[Dict[str, Any]], str]:
    """Rows for one store + which source they came from ('scan' or 'db')."""
    rows = _snapshot_rows(domain)
    if rows is not None:
        return rows, "scan"
    return _project_db(db, domain), "db"


# ---------------------------------------------------------------------------
# Store catalogue
# ---------------------------------------------------------------------------
def _scan_info(domain: str) -> Optional[Dict[str, Any]]:
    """Freshness + count for a store's snapshot (TTL ignored), or None."""
    path = scan_cache._path(domain)
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    cached = _INFO_CACHE.get(domain)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with path.open() as fh:
            payload = json.load(fh)
    except Exception:
        logger.exception("edit_products: could not read snapshot for %s", domain)
        return None
    snap = payload.get("snapshot") or {}
    scanned_at = payload.get("scanned_at")
    age = scan_cache._age_seconds(scanned_at or "")
    info = {
        "scanned_at": scanned_at,
        "age_days": round(age / 86400, 1) if age is not None else None,
        "product_count": len(snap.get("products") or {}),
        "shop_name": (snap.get("shop") or {}).get("name", ""),
    }
    _INFO_CACHE[domain] = (mtime, info)
    return info


def list_stores(db) -> List[Dict[str, Any]]:
    """Every known store with its data source, scan freshness, and row count.

    Union of config ``source_sites``, on-disk scan snapshots, and DB source
    sites — so the selector shows all five stores even though only two have a
    recent scan.
    """
    from backend.database.models import ProductSource

    domains: Dict[str, None] = {}
    for s in (config.get("source_sites", default=[]) or []):
        d = s.get("domain")
        if d:
            domains[d] = None
    if scan_cache._CACHE_DIR.exists():
        for p in scan_cache._CACHE_DIR.glob("*.json"):
            try:
                with p.open() as fh:
                    d = json.load(fh).get("domain")
            except Exception:
                continue
            if d:
                domains[d] = None
    for (site,) in db.query(ProductSource.source_site).distinct().all():
        if site:
            domains[site] = None

    out: List[Dict[str, Any]] = []
    for domain in domains:
        info = _scan_info(domain)
        if info and info["product_count"]:
            out.append({
                "domain": domain,
                "data_source": "scan",
                "product_count": info["product_count"],
                "scanned_at": info["scanned_at"],
                "age_days": info["age_days"],
                "shop_name": info["shop_name"],
            })
        else:
            count = (
                db.query(ProductSource)
                .filter(ProductSource.source_site == domain, ProductSource.is_active == True)  # noqa: E712
                .count()
            )
            out.append({
                "domain": domain,
                "data_source": "db",
                "product_count": count,
                "scanned_at": None,
                "age_days": None,
                "shop_name": "",
            })
    out.sort(key=lambda s: (-s["product_count"], s["domain"]))
    return out


# ---------------------------------------------------------------------------
# Query: search / filter / sort / paginate / facets
# ---------------------------------------------------------------------------
def _row_haystack(r: Dict[str, Any]) -> str:
    parts = [
        r.get("title"), r.get("sku"), r.get("vendor"), r.get("product_type"),
        r.get("barcode"), r.get("handle"), r.get("description"),
        r.get("variant_title"), r.get("option1"), r.get("option2"), r.get("option3"),
        " ".join(r.get("tags") or []), " ".join(r.get("collections") or []),
    ]
    return " ".join(p for p in parts if p).lower()


def _matches(r: Dict[str, Any], search: str, f: Dict[str, Any]) -> bool:
    if search and search.lower() not in _row_haystack(r):
        return False
    if f.get("title") and f["title"].lower() not in (r.get("title") or "").lower():
        return False
    if f.get("sku") and f["sku"].lower() not in (r.get("sku") or "").lower():
        return False
    if f.get("vendor") and (r.get("vendor") or "") != f["vendor"]:
        return False
    if f.get("product_type") and (r.get("product_type") or "") != f["product_type"]:
        return False
    if f.get("status") and (r.get("status") or "") != f["status"]:
        return False
    if f.get("tag"):
        want = f["tag"].lower()
        if not any(want in t.lower() for t in (r.get("tags") or [])):
            return False
    if f.get("collection"):
        want = f["collection"].lower()
        if not any(want in c.lower() for c in (r.get("collections") or [])):
            return False
    price = r.get("price")
    if f.get("min_price") is not None and (price is None or price < f["min_price"]):
        return False
    if f.get("max_price") is not None and (price is None or price > f["max_price"]):
        return False
    weight = r.get("weight")
    if f.get("min_weight") is not None and (weight is None or weight < f["min_weight"]):
        return False
    if f.get("max_weight") is not None and (weight is None or weight > f["max_weight"]):
        return False
    if f.get("has_image") is True and not r.get("image_count"):
        return False
    if f.get("has_image") is False and r.get("image_count"):
        return False
    return True


def _sort_key(col: str):
    numeric = col in _NUMERIC_COLS

    def key(r: Dict[str, Any]):
        v = r.get(col)
        if numeric:
            # None sorts last regardless of direction feels wrong under desc;
            # keep it simple: missing numbers sort as -inf.
            return (v is None, v if v is not None else 0)
        if isinstance(v, list):
            v = ", ".join(v)
        return (False, (v or "").lower() if isinstance(v, str) else str(v or ""))

    return key


def _facets(rows: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    vendors, types, cats, statuses, collections, tags = set(), set(), set(), set(), set(), set()
    for r in rows:
        if r.get("vendor"):
            vendors.add(r["vendor"])
        if r.get("product_type"):
            types.add(r["product_type"])
        if r.get("category"):
            cats.add(r["category"])
        if r.get("status"):
            statuses.add(r["status"])
        for c in r.get("collections") or []:
            collections.add(c)
        for t in r.get("tags") or []:
            tags.add(t)
    return {
        "vendors": sorted(vendors),
        "product_types": sorted(types),
        "categories": sorted(cats),
        "statuses": sorted(statuses),
        "collections": sorted(collections),
        "tags": sorted(tags),
    }


_POOL_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def _snapshot_pools(domain: str) -> Dict[str, Any]:
    """Distinct product_types + collection titles from one snapshot (mtime-cached)."""
    path = scan_cache._path(domain)
    if not path.exists():
        return {"product_types": set(), "collections": set()}
    mtime = path.stat().st_mtime
    cached = _POOL_CACHE.get(domain)
    if cached and cached[0] == mtime:
        return cached[1]
    snap = scan_cache.load_snapshot(domain, max_age_days=_ANY_AGE_DAYS)
    if not snap:
        return {"product_types": set(), "collections": set()}
    types = {p.get("product_type") for p in (snap.get("products") or {}).values() if p.get("product_type")}
    colls = {c.get("title") for c in (snap.get("collections") or {}).values() if c.get("title")}
    pools = {"product_types": types, "collections": colls}
    _POOL_CACHE[domain] = (mtime, pools)
    return pools


def taxonomy_pools(db) -> Dict[str, List[str]]:
    """Comprehensive suggestion pools for the editor's datalists.

    Pulls every existing product type, category, and collection from the DB and
    from all on-disk scan snapshots so the user can pick an existing value or
    type a brand-new one.
    """
    from backend.database.models import Product, ProductSource

    product_types: set = set()
    categories: set = set()
    collections: set = set()

    # DB: product types (scraped source_category) + canonical categories.
    for (v,) in db.query(ProductSource.source_category).distinct().all():
        if v:
            product_types.add(v)
    for (v,) in db.query(Product.category).distinct().all():
        if v:
            categories.add(v)

    # Snapshots: real Shopify product types + collection titles across all scans.
    if scan_cache._CACHE_DIR.exists():
        for p in scan_cache._CACHE_DIR.glob("*.json"):
            try:
                with p.open() as fh:
                    domain = json.load(fh).get("domain")
            except Exception:
                continue
            if not domain:
                continue
            pools = _snapshot_pools(domain)
            product_types |= pools["product_types"]
            collections |= pools["collections"]

    return {
        "product_types": sorted(product_types),
        "categories": sorted(categories),
        "collections": sorted(collections),
    }


def query(
    db,
    *,
    stores: List[str],
    search: str = "",
    filters: Optional[Dict[str, Any]] = None,
    sort_by: str = "title",
    sort_order: str = "asc",
    page: int = 1,
    per_page: int = 50,
) -> Dict[str, Any]:
    """Search/filter/sort/paginate variant rows across the selected stores."""
    filters = filters or {}
    per_page = max(1, min(per_page, 500))
    page = max(1, page)
    if sort_by not in COLUMNS:
        sort_by = "title"

    all_rows: List[Dict[str, Any]] = []
    stores_meta: List[Dict[str, Any]] = []
    for st in stores:
        rows, src = _store_rows(db, st)
        all_rows.extend(rows)
        stores_meta.append({"domain": st, "data_source": src, "row_count": len(rows)})

    facets = _facets(all_rows)
    filtered = [r for r in all_rows if _matches(r, search, filters)]
    filtered.sort(key=_sort_key(sort_by), reverse=(sort_order == "desc"))

    total = len(filtered)
    start = (page - 1) * per_page
    page_rows = filtered[start:start + per_page]
    pages = max(1, (total + per_page - 1) // per_page)

    return {
        "rows": page_rows,
        "columns": COLUMNS,
        "total": total,
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "facets": facets,
        "stores_meta": stores_meta,
    }


# ---------------------------------------------------------------------------
# Write-back (Phase 4): staged edits → executor transactions.
# ---------------------------------------------------------------------------
# A field's risk drives the review's colour coding + the user's caution.
_RISK = {"status": "HIGH", "price": "MEDIUM", "compare_at_price": "MEDIUM",
         "title": "MEDIUM", "collections": "MEDIUM"}
# Our column names → Shopify product-level field keys (executor product_field).
_PRODUCT_FIELD_KEYS = {
    "title": "title", "vendor": "vendor", "product_type": "product_type", "status": "status",
}
# Our column names → Shopify variant-level field keys (executor variant_field).
_VARIANT_FIELD_KEYS = {
    "sku": "sku", "barcode": "barcode", "price": "price",
    "compare_at_price": "compare_at_price", "weight": "weight", "weight_unit": "weight_unit",
}


def _change_id(ch: Dict[str, Any]) -> str:
    return ch.get("change_id") or "|".join(
        str(ch.get(k, "")) for k in ("store", "product_id", "variant_id", "scope", "field")
    )


def build_edit_transactions(changes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Turn staged field changes into reviewable items + executor transactions.

    Each returned item carries a display view (store/field/old/new/risk) plus a
    ``pushable`` flag and, when pushable, an executor-ready ``txn`` dict. Only
    scan-sourced rows are pushable — their product/variant ids are real Shopify
    ids; DB-fallback rows carry local ids that can't be written back.
    """
    items: List[Dict[str, Any]] = []
    for ch in changes:
        cid = _change_id(ch)
        field = ch.get("field")
        item: Dict[str, Any] = {
            "change_id": cid,
            "store": ch.get("store"),
            "field": field,
            "scope": ch.get("scope"),
            "old": ch.get("old"),
            "new": ch.get("new"),
            "risk": _RISK.get(field, "LOW"),
            "pushable": True,
            "reason": "",
            "txn": None,
        }

        if ch.get("data_source") != "scan":
            item.update(pushable=False, reason="Store has no recent scan — rescan it to push edits.")
            items.append(item)
            continue

        try:
            pid = int(ch.get("product_id"))
        except (TypeError, ValueError):
            item.update(pushable=False, reason="Missing or non-numeric Shopify product id.")
            items.append(item)
            continue

        if field == "category":
            # Shopify's taxonomy Category has no REST write field and isn't in
            # the scans — editable + staged, but not pushed to Shopify here.
            item.update(pushable=False,
                        reason="Shopify Category needs a rescan + GraphQL write — staged, not pushed.")
        elif field == "tags":
            old = ch.get("old") or []
            new = ch.get("new") or []
            adds = [t for t in new if t not in old]
            removes = [t for t in old if t not in new]
            item["txn"] = {
                "id": cid, "action": "UPDATE", "resource_type": "tags", "product_id": pid,
                "meta": {"tags_to_add": adds, "tags_to_remove": removes}, "approved": True,
            }
        elif field == "collections":
            old = ch.get("old") or []
            new = ch.get("new") or []
            adds = [c for c in new if c not in old]
            removes = [c for c in old if c not in new]
            item["txn"] = {
                "id": cid, "action": "UPDATE", "resource_type": "collections", "product_id": pid,
                "meta": {"add": adds, "remove": removes}, "approved": True,
            }
        elif field in _PRODUCT_FIELD_KEYS:
            item["txn"] = {
                "id": cid, "action": "UPDATE", "resource_type": "product_field", "product_id": pid,
                "new_value": ch.get("new"), "meta": {"field_key": _PRODUCT_FIELD_KEYS[field]},
                "approved": True,
            }
        elif field in _VARIANT_FIELD_KEYS:
            try:
                vid = int(ch.get("variant_id"))
            except (TypeError, ValueError):
                item.update(pushable=False, reason="Missing or non-numeric Shopify variant id.")
                items.append(item)
                continue
            item["txn"] = {
                "id": cid, "action": "UPDATE", "resource_type": "variant_field", "product_id": pid,
                "new_value": ch.get("new"), "meta": {"variant_id": vid, "field_key": _VARIANT_FIELD_KEYS[field]},
                "approved": True,
            }
        else:
            item.update(pushable=False, reason=f"Field '{field}' can't be pushed to Shopify.")

        items.append(item)
    return items
