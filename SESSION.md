# Session Notes

## 2026-06-23 — SoR variant consolidation, Stages 1 & 2

Branch: `sor-variant-consolidation` (off `dedup-price-store-compare-2026-06-23`).

Goal of the larger effort: one shared Product record per SKU, with
`equipmentplus`/`donut-equipment.com` as the permanent system of record; every
variant becomes a first-class record so the whole catalog (incl. all Shopify
variants) is captured and kept identical across stores.

### Done this session
- **Stage 1 — capture ALL variants.** New pure helper
  `backend/scrapers/shopify_scraper.py::_expand_variants(item, base, domain)`
  emits one `ScrapedProduct` per Shopify variant (own SKU/price/availability,
  variant options as `ProductOption` rows, distinct `source_url`
  `…/products/<handle>?variant=<id>`, parent reference). Replaces the old
  `variants[0]`-only logic in `scrape_shopify_store`, and is now also used by the
  Admin draft/archived path in `source_scraper._fetch_admin_status_products`.
- **Variant-aware handle fallback.** `_persist_product`'s legacy handle-match
  fallback now also requires the same `variant` id (new helper
  `source_scraper._variant_id`) so variants of one handle don't collapse into one
  ProductSource row.
- **Stage 2 — schema.** Added `parent_handle` (VARCHAR 500) + `shopify_product_id`
  (VARCHAR 50) to `Product` (`models.py`, indexed), with idempotent ALTERs in
  `db.py::_MIGRATIONS`. Persisted on new products and backfilled on existing rows
  in `_persist_product`. `ScrapedProduct` gained matching fields
  (`base_scraper.py`). Migration verified against the live DB (10,848 product
  rows intact, columns present).
- **Tests:** `tests/test_variant_capture.py` (7 tests). Full suite: 33 passed.

### Stage 3 — DONE (destructive regen, user-approved)
- Re-scraped all 5 stores to per-variant records via `scripts/stage3_rescrape.py`.
  Active variant rows: DE 2756, DE2 2568, DE3 2757, BW 2694, DS 2702 = **13,477**,
  every one with a `variant=` id + `parent_handle`/`shopify_product_id`.
- **Gotcha found:** `run_source_scan(site_filter=…)` scrapes via `base_url` (custom
  domain), not `shopify_store_url`. donut-supplies.com's custom domain 503'd
  mid-pagination and truncated. Fixed the runner to prefer `shopify_store_url`
  (like `run_all_sources`) and re-ran DS → recovered 155 missing products.
- **Orphan cleanup (user chose "migrate matches, then retire"):** the regen left
  6,836 old cross-store-merged Products orphaned (sources all archived) holding
  9,628 competitor matches. `scripts/migrate_competitor_matches.py` re-pointed
  matches by SKU (stable cross-store key; handles differ per store) to the new
  SoR (donut-equipment.com) variant product → **9,602 preserved**, 26 stranded
  (genuinely SKU-less). Then retired the 6,836 orphans (is_active=0).
- Final: **13,477 active products, 0 orphans.** Tags/notes on orphans were 0.
- Backups: `data/donut_intel.db.bak-presor-20260623-170324` (pre-regen),
  `data/donut_intel.db.bak-prematchmig-20260623-172013` (post-regen, pre-match-migration).

### Stage 4 — DONE (SoR-pinned cross-store auto-merge)
- Rewrote `backend/dedup/force_merge.py`: precedence now **SKU → model → title**
  (was model → title). SKU is the stable cross-store key; title-fuzzy is gated to
  titles UNIQUE among SoR products (threshold 80) so it can't merge into an
  arbitrary sibling variant. donut-equipment.com is always the primary that stays
  active; default secondary sites = all 4 other stores. Testable helper
  `_best_primary_match()` (tests: `tests/test_force_merge_match.py`, 6).
- Hooked into `run_source_scan`: after every scan it runs `force_merge_source_sites`
  off the event loop (never fails the scan). Also fixed the production single-site
  scan path to prefer `shopify_store_url` (same custom-domain 503 bug as Stage 3).
- Ran once against the live DB (`scripts/stage4_force_merge.py`):
  **10,663 merged** (sku=10,328, title=335, model=0), 42 uncertain, 16 unmatched.
  Catalog: 13,477 → **2,814 active products**; store-count distribution:
  5-store=2406, 4=216, 3=69, 2=36, 1-store=87. Competitor matches: 9,601 on
  active, 27 stranded. Backup `data/donut_intel.db.bak-prestage4-20260623-172517`.

### Canonical price → SoR-pinned (DONE, user-confirmed)
- User: "canonical price must always come from donut-equipment.com / equipmentplus."
- `recompute_product_prices` (engine.py) now prefers the SoR source's price
  (`SOR_SITE="donut-equipment.com"`), falling back to latest-scraped only when a
  product has no SoR source. price_min/max still span all stores.
- Backfilled live DB via `recompute_all_product_prices`: 146 products corrected,
  0 mismatches remain. Backup `data/donut_intel.db.bak-precanon-20260623-173304`.
- Tests: `tests/test_canonical_price_sor.py` (2).

### Stage 5 — DONE (surface missing/extra per store, in Store Compare)
- New endpoint `GET /api/products/store-comparison/summary` returns per-store
  `present` / `missing` / `only_here` counts over the merged catalog, plus
  `missing_from_sor`. Aggregate SQL, catalog-wide.
- Store Compare page: gap-summary strip of clickable chips (one per store, SoR
  highlighted) showing each store's missing count; clicking sets the existing
  `missing_from` filter to drill into the list. `app.js`: `loadStoreCompSummary`,
  `storeCompShowMissingFrom`, `storeCompShortSite`, `storeCompSummary` state.
- The pre-existing per-store `missing_from` filter already surfaces both
  directions (missing-from-store and missing-from-SoR = missing_from=DE) now that
  products are merged — Stage 5 makes it discoverable + quantified.
- Verified end-to-end via running server: summary 200 (2814 total, SoR missing 58),
  drill-down `missing_from=donut-equipment.com` total=58 (consistent).
- Tests: `tests/test_store_compare_summary.py` (1). Full suite green (42).

## SoR variant consolidation: COMPLETE (Stages 1–5 + canonical-price)
All five stages done on branch `sor-variant-consolidation`. Catalog is unified
(2,814 shared products, 2,406 in all 5 stores), canonical price = SoR, auto-merge
runs at end of every scan, gaps surfaced per store.
