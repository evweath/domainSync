#!/usr/bin/env python3
"""Check how recently competitor sites and source sites were scraped."""

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB = Path(__file__).parent.parent / 'data' / 'donut_intel.db'
STALE_DAYS = 7
SHOW_ALL = '--all' in sys.argv


def age(ts: str | None) -> str:
    if not ts:
        return 'never'
    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    d, s = delta.days, delta.seconds
    if d >= 1:
        return f'{d}d ago'
    if s >= 3600:
        return f'{s // 3600}h ago'
    return f'{s // 60}m ago'


def flag(ts: str | None) -> str:
    if not ts:
        return ' !'
    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    return ' !' if delta.days >= STALE_DAYS else '  '


def main() -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    print(f'\n=== Source Sites (own inventory) ===')
    rows = con.execute('''
        SELECT source_site,
               COUNT(*) AS products,
               MAX(scraped_at) AS last_scraped
        FROM product_sources
        GROUP BY source_site
        ORDER BY last_scraped DESC NULLS LAST
    ''').fetchall()
    if rows:
        print(f'  {"Site":<30} {"Products":>8}  {"Last scraped":<12}')
        for r in rows:
            print(f'{flag(r["last_scraped"])} {r["source_site"]:<30} {r["products"]:>8}  {age(r["last_scraped"])}')
    else:
        print('  (no source data)')

    print(f'\n=== Competitor Sites ===')
    rows = con.execute('''
        SELECT c.domain, c.name, c.is_active,
               c.last_scanned_at, c.total_matching_products,
               p.consecutive_failures, p.last_error_at
        FROM competitors c
        LEFT JOIN competitor_scraping_profiles p ON p.competitor_id = c.id
        ORDER BY c.total_matching_products DESC, c.last_scanned_at DESC NULLS LAST
    ''').fetchall()
    if rows:
        visible = [r for r in rows if SHOW_ALL or ((r['total_matching_products'] or 0) > 0 and r['is_active'])]
        hidden = len(rows) - len(visible)
        print(f'  {"Domain":<32} {"Matches":>7}  {"Last scan":<12}  {"Fails":>5}')
        for r in visible:
            status = '' if r['is_active'] else ' [inactive]'
            fails = r['consecutive_failures'] or 0
            fail_marker = f' (err: {age(r["last_error_at"])})' if fails else ''
            print(f'{flag(r["last_scanned_at"])} {r["domain"]:<32} {(r["total_matching_products"] or 0):>7}  {age(r["last_scanned_at"]):<12}  {fails:>5}{fail_marker}{status}')
        if hidden:
            print(f'  ... {hidden} more with 0 matches hidden (--all to show)')
    else:
        print('  (no competitors configured)')

    print(f'\n=== Recent Scan Sessions (last 10) ===')
    rows = con.execute('''
        SELECT name, session_type, target, status,
               started_at, completed_at,
               total_scraped, new_products, updated_products, errors
        FROM scan_sessions
        ORDER BY started_at DESC
        LIMIT 10
    ''').fetchall()
    if rows:
        for r in rows:
            marker = ' !' if r['status'] == 'failed' else '  '
            duration = ''
            if r['started_at'] and r['completed_at']:
                s = datetime.fromisoformat(r['started_at'])
                e = datetime.fromisoformat(r['completed_at'])
                secs = int((e - s).total_seconds())
                duration = f' ({secs}s)'
            print(f'{marker} [{r["status"]:<9}] {age(r["started_at"]):<10}  '
                  f'{r["session_type"]:<14} {r["target"] or "":<28}'
                  f'scraped={r["total_scraped"] or 0} new={r["new_products"] or 0} '
                  f'err={r["errors"] or 0}{duration}')
    else:
        print('  (no scan sessions)')

    print(f'\n  ! = not scraped in {STALE_DAYS}+ days or failed\n')
    con.close()


if __name__ == '__main__':
    main()
