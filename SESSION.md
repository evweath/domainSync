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

### NEXT (paused for confirmation)
- **Stage 3 — destructive full re-scrape** to regenerate per-variant rows.
  DB backup exists at `data/donut_intel.db.bak-20260623-145008`. Do NOT run
  without explicit go-ahead.
- Stage 4: SoR-pinned auto-merge (`backend/dedup/force_merge.py`).
- Stage 5: surface missing/extra products per store.
- Watch for downstream code assuming one Product per handle (Store Compare,
  Shopify sync/mapping). Current data unaffected until the Stage 3 re-scrape.

### Not committed
Working tree changes on the branch are not yet committed (awaiting user request).
