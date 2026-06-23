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

### NEXT
- Stage 4: SoR-pinned cross-store auto-merge (`backend/dedup/force_merge.py`):
  SKU→model→title, donut-equipment.com always primary, all secondary stores,
  run automatically at end of every scan. This re-unifies the per-store variants
  into shared products (Store Compare then works natively).
- Stage 5: surface missing/extra products per store.
- Watch: downstream code assuming one Product per handle (Store Compare, Shopify
  sync/mapping) — now there are per-store, per-variant products until Stage 4 merges.
