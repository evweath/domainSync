# Edit Products page

Bulk product editor: shows every product from the **most recent store scan**,
one row per variant, searchable by any attribute, with a horizontal
resizable/sortable grid. Designed for mass/bulk edits across one or many stores.

## Decisions (confirmed with user, 2026-07-10)

1. **Write-back = stage → review → execute.** Edits accumulate as pending
   changes, reviewed with risk levels, then pushed via the existing
   `executor.execute_transactions` pipeline. Nothing hits Shopify without
   explicit approval. (Phase 4 — not yet built.)
2. **Store scope = all stores, snapshot-preferred.** Use the scan snapshot where
   available; fall back to the DB canonical records for stores without a fresh
   scan.
3. **Row model = one row per variant.** Product-level fields repeat across a
   product's variant rows.

## Data sources & the TTL gotcha

- **Scan snapshots** (`data/scan_cache/<domain>.json`, via `scan_cache`): raw
  Shopify Admin-API product objects. Richest source. Currently only 2 stores
  have snapshots: `DE3` (2283 products) and `donut-equipment.com` (2216).
- **DB fallback** (`ProductSource`/`Product`/`ProductOption`/`ProductImage`/
  `ProductTag`): the other 3 stores (`donut-supplies.com`,
  `bakerywholesalers.com`, `donut-equipment.myshopify.com`).
- **GOTCHA:** `scan_cache.load_snapshot()` enforces `MAX_AGE_DAYS = 5`. The
  existing snapshots are 7–9 days old, so the default call returns `None`. The
  Edit Products page must load "the most recent scan however old", so
  `edit_products` passes `max_age_days=_ANY_AGE_DAYS` (effectively infinite) and
  surfaces the age instead. `age_days > 5` shows a ⚠ badge in the store selector.
- Snapshot structure: file is `{domain, scanned_at, snapshot}`. `snapshot`
  has `products` (keyed by handle), `collections` (keyed by str id),
  `product_collections` (`{str(product_id): [int collection_id]}`). Tags are a
  comma-separated string. `country_of_origin` is NOT a native Shopify field
  (`metafields` were empty) → always null from snapshots.

## Architecture

- **`backend/shopify/edit_products.py`** — projection + query layer.
  - `list_stores(db)` → union of config `source_sites`, on-disk snapshots, and
    DB sites; each tagged `data_source` scan|db with product_count + scan age.
  - `_project_snapshot` / `_project_db` → flatten to the unified `COLUMNS` row
    schema (one row per variant). Pure-ish; snapshot path is cached per store,
    invalidated by file mtime (`_ROWS_CACHE`).
  - `query(db, stores, search, filters, sort_by, sort_order, page, per_page)` →
    in-Python search across all attributes, per-field filters, sort, paginate,
    plus facet options (vendors/types/statuses/collections/tags) computed over
    the *pre-filter* row set so dropdowns stay complete.
- **Routes** (`backend/api/routes.py`): `GET /api/edit-products/stores`,
  `GET /api/edit-products`.
- **Frontend** (`frontend/index.html` + `frontend/js/app.js`): `edit-products`
  nav view. Store checkboxes, global search + attribute filters, horizontal grid
  in an `overflow-auto` container (`max-height: calc(100vh - 340px)` gives the
  bottom horizontal scrollbar + sticky header). Columns are sortable (click
  header → `editSort`) and resizable (reuses the existing `_initColumnResize`
  MutationObserver, which auto-wires any `<table>`).

## Phases

- **Phase 1 (DONE):** read-only grid + search/filter/sort/store-select. Backend
  projection + routes + tests (`tests/test_edit_products.py`, 10 tests). Non-
  destructive.
- **Phase 2 (DONE):** inline cell editing. Click an editable cell → input/select
  (Enter or blur commits, Esc cancels). Dirty cells highlighted amber. Row
  objects are never mutated; edits are overlays applied for display:
  `editEdits` (variant-level, keyed by `row_id`) and `editProductEdits`
  (product-level, keyed by `store|product_id` so title/vendor/type/status/tags
  propagate to all sibling variant rows). `editColScope` decides which map a
  field uses; `editColType` decides render/parse (text/number/select/tags).
  Reverting a cell to its original value clears the override. "N unsaved edits"
  + "Revert all" in the summary bar. Nothing sent to Shopify.
- **Phase 3 (TODO):** bulk edit across selected rows (`editRowSel` already wired).
- **Phase 4 (DONE):** stage → review → execute. `edit_products.build_edit_transactions`
  converts the staged change list into reviewable items + executor transactions
  (`product_field` for title/vendor/product_type/status, `tags` with add/remove
  diff, `variant_field` for sku/barcode/price/compare_at_price/weight/weight_unit).
  Routes: `POST /api/edit-products/review` (risk + pushable counts, no Shopify
  calls) and `POST /api/edit-products/execute` — **backgrounded** via
  `asyncio.create_task` (a bulk push is hundreds of GET+PUTs under Shopify's
  2 req/s limit = minutes; mirrors the Live Sync execute pattern). Client starts
  it, then polls `GET /api/edit-products/execute-status` (state in
  `_edit_execute_state`). Groups by store, calls `_get_site_credentials` +
  `execute_transactions` per store; per-store credential failure fails only that
  store; results keyed by `change_id`. Frontend: green
  "Review & push" button → modal listing every change (Was → Now, risk badge),
  "Push N changes to Shopify"; on success each pushed change is cleared from the
  overlay maps, failures stay staged. **Push writes to the LIVE store** — all 5
  stores have store_url + client creds in config, so a successful push mutates
  Shopify (subject to write scopes). Risk model: status=HIGH,
  price/compare_at_price/title=MEDIUM, everything else=LOW.
  Only scan-sourced rows are pushable (real Shopify ids); DB-sourced changes are
  marked blocked ("rescan to push").

## Gotchas / notes

- ~5,500 variant rows across the 2 scan stores; filtering/sorting is done in
  Python per request (snapshots cached in-process), which is fine at this size.
  If catalogs grow much larger, move to a real query/index.
- DB fallback has no collection membership (not tracked in the DB) → empty
  `collections` for db-sourced rows.
- `row_id` = `"{store}|{product_id}|{variant_id}"` — stable key for the frontend
  and for mapping staged edits back to Shopify resources in Phase 4.
- **Purged Tailwind build gotcha:** `frontend/vendor/tailwind.min.css` is a small
  PURGED build (~42KB). Many utilities are absent — confirmed missing:
  `bg-amber-100`, `ring-1`, `ring-amber-*`. Do NOT assume a Tailwind class exists;
  grep the vendor CSS first, and if missing, add a real rule to
  `frontend/css/style.css` (as the existing indigo/edit-cell blocks do). The
  dirty-cell highlight uses `.edit-cell-dirty` / `.edit-cell-editable` there.
- Editable columns (Phase 2): title, vendor, product_type, status, tags
  (product-scope) and sku, barcode, price, compare_at_price, weight, weight_unit
  (variant-scope). NOT editable in-grid: description (truncated to 400 chars for
  display — needs a modal), collections (membership model), country_of_origin,
  dimensions, inventory_quantity (Shopify inventory-item API, not a variant
  field), options/variant_title (define the variant).
- Verified via CDP-driven headless Chromium (`chrome-headless-shell` in the
  ms-playwright cache) — no node/playwright package needed; drive it over the
  DevTools websocket with the `websockets` lib. Reload with
  `Network.setCacheDisabled` because assets are versioned (`?v=...`) and cached.
