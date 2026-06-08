# Competitor Search — Investigation File

## Architecture

```
Competitor scan trigger (scheduler or manual)
  → competitor/web_search_scan.py: scan competitors
  → competitor/product_search.py: match products per competitor URL
    → search/engine.py: multi_engine_search(query, engines=[...])
    → competitor/matcher.py: fuzzy match results to catalog
  → database: CompetitorProduct rows

Competitor search query building:
  → pulls manufacturer + product_type + model from catalog
  → constructs query string for multi_engine_search
```

## Confirmed Root Causes (do not re-investigate)

### DB lock during scan (RESOLVED — 2026-05-26)
- **Root cause:** Competitor scraper held a write lock while async search tasks were also writing, causing `sqlite3.OperationalError: database is locked`.
- **Fix:** Moved dedup off the event loop + added WAL mode. See commit `6f551b606`.

### Empty/homepage results from internet search (RESOLVED — 2026-05-23)
- **Root cause:** Search queries were too generic (missing manufacturer/product_type), causing search engines to return homepage URLs instead of product pages.
- **Fix:** Rewrote query builder to include manufacturer + product type. See `backend/competitor/product_search.py`.

### DDG returning no results (RESOLVED — 2026-05-23)
- **Root cause:** DDG rate-limited; fallback to curl subprocess was broken.
- **Fix:** Added curl fallback with proper headers in `engine.py`. Later replaced all curl subprocesses with `primp AsyncClient` (2026-06-01).

### False positive competitors in results (RESOLVED — 2026-05-27)
- **Root cause:** Some domains in results were not actual competitors (directories, aggregators, etc.).
- **Fix:** Expanded blocklist in engine + Yahoo scraper blocklist.

### Search query voltage orphan / manufacturer dedup (RESOLVED — 2026-05-26)
- **Root cause:** Query builder included voltage specs as orphan tokens, and duplicated manufacturer words when product title already contained them.
- **Fix:** Deduplicate manufacturer words; skip generic manufacturer names; fix voltage orphan. See `engine.py` query builder.

## Known Failure Modes

- **Rate limiting:** After heavy scanning, all engines (DDG, Bing, Google) rate-limit. Symptoms: results empty or returning irrelevant results. Wait before re-scanning; use SerpAPI (`shopping` engine) as it has quota-based rate limiting rather than IP blocking.
- **Empty scan cooldown bug:** Was incorrectly triggering cooldown even when scan wasn't empty. Fixed in `6f551b606`.

## Failed Attempts (do not repeat)

| Session | What was tried | Why it failed |
|---|---|---|
| Early sessions | Tweaking max_results parameter | Didn't address query quality — results were wrong, not just few |
| Pre-2026-05-23 | Single-engine search with DDG only | DDG rate-limits quickly; no fallback |

## Open Questions

- Does the 4-async-worker parallel competitor search (added 2026-05-19) interact with DB locking under heavy load? Not seen since WAL mode fix, but worth monitoring.
- Yahoo Shopping PLA scraper (`yahoo_shopping_scraper.py`) — how often does Yahoo update PLAs? Are cached results stale after 24h?
