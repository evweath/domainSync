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

## Architecture note (2026-06-08 refactor)

`product_search.py` and `web_search_scan.py` no longer keep their own copies of
the product-page parsers. They import `_parse_jsonld`, `_parse_meta`, `_meta_val`,
`_extract_price_float`, `_domain`, and fetch from `backend/search/core/`. Query
building stays per-page (`_build_query`, `_clean_title_for_search`). See
[[project_search_layer_split]].

### Drift fixed: web-scan dropped image/description (RESOLVED — 2026-06-08)
- **Root cause:** `web_search_scan._parse_jsonld`/`_parse_meta` were copy-paste
  forks of the `product_search` versions that never got the image+description
  fields added. The full-catalog scan silently extracted less than the per-product
  scan from the same page.
- **Fix:** Unified both into `core/parse.py` (superset, with image+description).
  Locked by `tests/test_parse_shared.py::test_scan_modules_share_the_same_parsers`.
- **Lesson:** identical-by-intent helpers copied into sibling modules WILL drift.
  Keep them in `core/`; only genuinely page-specific logic stays local.

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
