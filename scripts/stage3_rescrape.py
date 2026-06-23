"""
SoR variant consolidation — Stage 3 runner.

Re-scrapes one source site (or all) so the new per-variant capture regenerates
ProductSource/Product rows. Destructive in effect: old single-listing rows for a
re-scraped site get archived by the scan's _archive_unseen_for_site step and new
per-variant rows are created.

Usage:
    .venv/bin/python scripts/stage3_rescrape.py <domain>     # one site
    .venv/bin/python scripts/stage3_rescrape.py --all        # every enabled site
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import config
from backend.database.db import init_db, session_scope
from backend.database.models import ScanSession
from backend.scrapers.source_scraper import SourceScraper


async def _scan(site_filter):
    """Scan one site (or all). Unlike run_source_scan(site_filter=…), this scrapes
    via shopify_store_url when present (matching run_all_sources) — the custom
    domain can rate-limit (503) mid-pagination and silently truncate the catalog.
    """
    sites = config.get("source_sites", default=[])
    if site_filter:
        site = next((s for s in sites if s.get("domain") == site_filter), None)
        if not site:
            raise ValueError(f"Site not found: {site_filter}")
        targets = [site]
    else:
        targets = [s for s in sites if s.get("enabled", True)]

    with session_scope() as db:
        sess = ScanSession(
            name=f"Stage3 re-scrape {site_filter or 'all_sources'}",
            session_type="source",
            target=site_filter or "all_sources",
            status="running",
        )
        db.add(sess)
        db.flush()
        sid = sess.id
    print(f"[stage3] scan session {sid} → {site_filter or 'all_sources'}")

    scraper = SourceScraper(session_id=sid)
    all_stats = {}
    for s in targets:
        scrape_url = s.get("shopify_store_url") or s["base_url"]
        stats = await scraper.run_site(scrape_url, s["name"], s["domain"])
        all_stats[s["domain"]] = stats
        print(f"[stage3] {s['domain']} done: {stats}")
    print(f"[stage3] done: {all_stats}")
    return all_stats


def main():
    init_db()
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    arg = sys.argv[1]
    if arg == "--all":
        asyncio.run(_scan(None))
    else:
        domains = {s.get("domain") for s in config.get("source_sites", default=[])}
        if arg not in domains:
            print(f"Unknown domain {arg!r}. Known: {sorted(domains)}")
            sys.exit(1)
        asyncio.run(_scan(arg))


if __name__ == "__main__":
    main()
