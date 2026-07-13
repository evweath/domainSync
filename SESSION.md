# Session Notes

## 2026-07-13 — Edit Products: column-width bugs, real Category taxonomy, Tags/Collections editing UX

Branch: `feature/edit-products`, **pushed** through commit `2704ef5` (Category
taxonomy). The last 3 commits this session — `28ee7d0`, `3e6f14d`, `26f4dbd`
(Tags/Collections filter/edit iterations, landing on the column pop-up) — are
committed locally but **not yet pushed** — push them first thing tomorrow if
still wanted.
Full test suite green (62). `.claude/investigations/edit-products.md` has the
detailed blow-by-blow (six dated entries added today) — read it before
touching this page again, especially the Category taxonomy section.

### Done this session
- **Removed Wt Unit/Qty columns**, fixed a real CSS bug (purged Tailwind ships
  no `.z-10`/`.z-20`/`.z-30`, so the Columns dropdown was rendering under the
  grid header — added real rules), capped every column's default width to
  ~30 chars.
- **Found and fixed a real width-cap bug** (survived one bad fix, escalated
  per CLAUDE.md protocol): the cap-lift-on-resize was scoped to the whole
  table instead of per-column, AND saved widths were keyed by array position
  instead of column identity — either bug alone could make every column
  ignore the 30-char default. Now keyed by header label text; verified with
  stale/adversarial localStorage states.
- **Category taxonomy is now real, not guessed.** User's hard requirement:
  "must be correct... this will sync with Shopify." Downloaded Shopify's
  actual published taxonomy and grepped it directly (not from model memory).
  Finding: Shopify's real taxonomy has **no branch for commercial/wholesale
  food-service equipment** — confirmed and surfaced to the user before writing
  code. Built `backend/shopify/category_taxonomy.py`: 9 real Shopify parent
  groups + ~68 real child leaves relevant to this catalog, every gid verified.
  Unmatched equipment falls back to the closest real parent (user's explicit
  choice). Category is its own picker type now, distinct from Product Type.
- **Tags/Collections editing**, iterated three times based on feedback, landed
  on: a "▤" icon in the Tags/Collections column headers opens a pop-up
  listing every value with a checkbox, pre-checked to whatever the
  currently-selected row(s) already have; toggling Adds/Removes across
  selected rows immediately. (Earlier attempts — inline per-cell picker,
  then top-of-page Filter/Edit mode checkboxes — were superseded, not kept
  alongside this.)
- **Top-of-page Save button** — same Review & Push confirmation modal as
  before, just a second, more prominent entry point. Confirmed with the user
  first since it triggers a live Shopify write.

### Open / next-time TODOs
- **Push the last commit** (`26f4dbd`) if not already done.
- **Live push still UNVERIFIED against a real store** (unchanged from last
  session — see below). This session added more editing surface (tags/
  collections pop-up, category picker) but did not touch the push path itself.
- **Category still can't push** — picker now stores real values/gids, but no
  GraphQL client exists in this codebase yet (everything is REST) and the
  scanner doesn't capture each product's real taxonomy gid. Follow-up.
- **`editFilters.tags`/`.collections` + backend tag/collection filtering
  exist but have no UI** — removed the UI this session (replaced by the
  editing pop-up), left the backend/state as-is since it's tested and
  harmless. If a filter UI is wanted again, the backend is already there.

## 2026-07-10 — Edit Products page (new feature)

Branch: `feature/edit-products` (off `main`). **Pushed** to remote `domainsync`
(`git@github.com:evweath/domainSync.git`); tracking set. 2 commits: `49c604f`
(page + phases 1–4), `6a7e81e` (v3.0, taxonomy editing, column chooser, layout).
Full test suite green (58). See `.claude/investigations/edit-products.md` for the
detailed design + gotchas — read it first tomorrow.

### Done this session
- **New "Edit Products" page** — pulls every product from the most recent store
  scan, one row per variant (~5,500 across the 2 scanned stores). Snapshot-
  preferred, DB fallback. `backend/shopify/edit_products.py` (projection, query,
  facets, taxonomy_pools, build_edit_transactions) + routes in `routes.py`
  (`/api/edit-products`, `/stores`, `/taxonomy`, `/review`, `/execute` [backgrounded]
  + `/execute-status`). Frontend: nav entry + view in `index.html` + `app.js`.
- **Search/filter/sort** across all attributes; store multi-select; horizontal
  resizable/sortable grid with always-visible scrollbars (fixed-height viewport).
- **Inline + bulk editing**, product vs variant edit-scope, dirty highlighting,
  revert; bulk Add/Remove/Set for list fields; free-form OR select-from-existing
  picker; column show/hide chooser (persisted); Description capped ~30 chars.
- **Stage → Review → Push** to live Shopify via the existing executor. Pushes:
  title/vendor/product_type/status (product_field), price/sku/etc (variant_field),
  tags, and collections (new executor `collections` handler: add=create/attach,
  remove=detach custom collections).
- Also: Platform label → v3.0; removed Country of Origin column; added Category +
  relabeled Type→Product Type.

### Open / next-time TODOs
- **Live push is UNVERIFIED against a real store** — deliberately never clicked
  "Push to Shopify" (all 5 stores have real creds; a successful push mutates the
  live store, no undo). Per `.claude/investigations/shopify-sync.md`, write scopes
  may still block it. Test with ONE low-risk change first.
- **Category can't push** — Shopify taxonomy Category isn't in the scans and has
  no REST write field; it's staged and marked "not pushed" in the review. To make
  it real: scanner change to capture the taxonomy node + GraphQL
  `productUpdate(category:)` + a taxonomy picker.
- **Scans are stale (7–9 days, past the 5-day TTL)** — the page intentionally
  loads the latest scan regardless of age (shows a ⚠ age badge). A fresh rescan
  would refresh data and could capture the taxonomy Category.
- **Repo has large files in history** (`data/donut_intel.db.bak-*`, ~59 MB each) —
  GitHub warned on push. Consider gitignoring backups + Git LFS / history purge.
- Git commits use an auto-derived author (`evw@evws-MacBook-Pro.local`); set
  `git config user.name/user.email` + amend if a proper author is wanted.
- Uncommitted, unrelated pre-existing changes left in tree on purpose:
  `.gitignore`, `backend/shopify/client.py`, `start.bat`.
- Server run: `.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1
  --port 8801 --ssl-certfile certs/cert.pem --ssl-keyfile certs/key.pem` (8743/8744
  are used by another project). `logs/server-8801.out` is untracked scratch.

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
