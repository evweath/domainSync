"""Persistent, time-boxed cache of store scan snapshots.

After a store is scanned (source or destination), its full snapshot is saved to
disk with a timestamp. A later scan request for the same domain can reuse the
saved snapshot as long as it is fresher than ``MAX_AGE_DAYS`` — so the user is
offered the choice to skip a redundant re-scan.

Snapshots live under ``data/scan_cache/<domain>.json`` and survive restarts.
Anything older than ``MAX_AGE_DAYS`` is treated as absent (and pruned on read).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# How long a saved scan may be reused before it is considered stale.
MAX_AGE_DAYS = 5

_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "scan_cache"


def _safe_name(domain: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", (domain or "").strip().lower())


def _path(domain: str) -> Path:
    return _CACHE_DIR / f"{_safe_name(domain)}.json"


def save_scan(domain: str, snapshot: Dict[str, Any]) -> None:
    """Persist a scan snapshot for ``domain`` stamped with the current time."""
    if not domain:
        return
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "domain": domain,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "snapshot": snapshot,
    }
    dest = _path(domain)
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        with tmp.open("w") as f:
            json.dump(payload, f)
        tmp.replace(dest)  # atomic swap so a crash mid-write can't corrupt it
    except Exception:
        logger.exception("scan_cache.save_scan: failed to persist %s", domain)
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _load_payload(domain: str) -> Optional[Dict[str, Any]]:
    p = _path(domain)
    if not p.exists():
        return None
    try:
        with p.open() as f:
            return json.load(f)
    except Exception:
        logger.exception("scan_cache: could not read cache for %s", domain)
        return None


def _age_seconds(scanned_at: str) -> Optional[float]:
    try:
        ts = datetime.fromisoformat(scanned_at)
    except Exception:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds()


def _fresh(payload: Dict[str, Any], max_age_days: int) -> Optional[float]:
    """Return the age in seconds if the payload is fresh, else None."""
    age = _age_seconds(payload.get("scanned_at", ""))
    if age is None or age > max_age_days * 86400:
        return None
    return age


def scan_info(domain: str, max_age_days: int = MAX_AGE_DAYS) -> Optional[Dict[str, Any]]:
    """Freshness metadata for a cached scan, or ``None`` if absent/stale."""
    payload = _load_payload(domain)
    if not payload:
        return None
    age = _fresh(payload, max_age_days)
    if age is None:
        return None
    snap = payload.get("snapshot") or {}
    return {
        "domain": domain,
        "scanned_at": payload.get("scanned_at"),
        "age_seconds": age,
        "age_days": round(age / 86400, 2),
        "product_count": len(snap.get("products") or {}),
        "shop_name": (snap.get("shop") or {}).get("name", ""),
        "max_age_days": max_age_days,
    }


def load_snapshot(domain: str, max_age_days: int = MAX_AGE_DAYS) -> Optional[Dict[str, Any]]:
    """Return the cached snapshot if present and fresher than ``max_age_days``."""
    payload = _load_payload(domain)
    if not payload:
        return None
    if _fresh(payload, max_age_days) is None:
        return None
    return payload.get("snapshot")


def all_info(max_age_days: int = MAX_AGE_DAYS) -> Dict[str, Dict[str, Any]]:
    """Freshness metadata for every fresh cached scan, keyed by domain."""
    out: Dict[str, Dict[str, Any]] = {}
    if not _CACHE_DIR.exists():
        return out
    for p in _CACHE_DIR.glob("*.json"):
        try:
            with p.open() as f:
                payload = json.load(f)
        except Exception:
            continue
        domain = payload.get("domain")
        if not domain:
            continue
        info = scan_info(domain, max_age_days)
        if info:
            out[domain] = info
    return out
