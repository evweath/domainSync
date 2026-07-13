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

## Taxonomy editing (Product Type / Category / Collections)

- **Columns:** `product_type` (labelled "Product Type") and `category` column.
  Category is blank on scan rows — Shopify's taxonomy Category is NOT in the
  snapshots (confirmed: product objects have no `category` key) and isn't a REST
  writable field. DB-fallback rows get category from `Product.category`.
- **product_type/collections are free text** — `edit_products.taxonomy_pools(db)`
  (route `GET /api/edit-products/taxonomy`) returns existing product types (DB
  `source_category` + all snapshot `product_type`s) and collections (all
  snapshot collection titles) as suggestion pools, wired to `<datalist>`s so
  edits autocomplete existing values OR accept a brand-new one.
- **category is NOT free text — a fixed pick from a curated, verified subset of
  Shopify's real taxonomy** (2026-07-13, see "Category taxonomy" below). It is
  its own `editColType` (`'category'`), distinct from `product_type`'s `'text'`
  — the two fields intentionally do NOT share the same options or UI.
- **Editable + scope:** product_type/category = product-scope, one value per
  product; collections = product-scope list (comma, like tags).
- **Bulk modes for list fields:** collections/tags support **Add / Remove / Set**
  (`editBulkMode`) — Add/Remove merge into each row's OWN current list; Set
  replaces. Other fields just set.
- **Push mapping (`build_edit_transactions`):**
  - product_type → `product_field` (pushes).
  - collections → ONE `collections` transaction per product with `meta.add` /
    `meta.remove` (title diff). Executor handler resolves/creates collections for
    adds and finds+deletes the collect for removes (custom collections only;
    smart collections are rule-based and skipped).
  - category → **pushable=false**, reason "Shopify Category needs a rescan +
    GraphQL write — staged, not pushed." (No REST field; would need a scanner
    change to capture the taxonomy node + a GraphQL `productUpdate(category:)`
    write. Follow-up — the picker now stores the exact gid needed for this, see
    below, but the write path itself is still not built.)

## Category taxonomy (2026-07-13)

User's ask evolved through three rounds: (1) "categories should come from
Shopify's real taxonomy, multi-tiered" → (2) "limit it to donut/bakery
equipment & supplies" → (3) **hard requirement:** "must be correct, can't be
guessed — this will sync with Shopify." That last constraint ruled out
inventing plausible-sounding category names.

- **Source of truth:** downloaded Shopify's actual published taxonomy
  (`github.com/Shopify/product-taxonomy`, `dist/en/categories.txt`, ~14,600
  real category lines) and grepped it directly — did NOT rely on model
  knowledge or a summarizing fetch tool for this, since correctness was the
  explicit requirement.
- **Critical finding, surfaced to the user before writing any code:** Shopify's
  real taxonomy has **no branch for commercial/wholesale bakery or food-service
  equipment** — zero matches for "proofer", "donut robot", "commercial mixer",
  "commercial fryer", "restaurant equipment". "Bakery" only exists under
  `Food, Beverages & Tobacco > Food Items > Bakery` (edible goods, not
  equipment) — irrelevant here (this catalog is 100% equipment/supplies, not
  finished baked goods for sale). `Business & Industrial > Food Service` exists
  but is only disposables/consumables (bakery boxes, cutlery, vending
  machines), not fryers/mixers/ovens. This business sells B2B food-service
  equipment; Shopify's public taxonomy is a B2C retail taxonomy. This is a real
  gap, not a bug in this app.
- **User's resolution (asked via AskUserQuestion, picked "coarse-but-real
  fallback"):** only offer categories that genuinely exist in Shopify's
  taxonomy. For equipment with no precise real match, fall back to the closest
  real PARENT node that does exist (e.g. generic "Kitchen Appliances"), rather
  than inventing a specific one or leaving it blank.
- **`backend/shopify/category_taxonomy.py`** — `CATEGORY_TAXONOMY`: 9 real
  Shopify parent groups (Kitchen Appliances, Kitchen Appliance Accessories,
  Kitchen Tools & Utensils, Cookware & Bakeware, Food Storage, Food Service,
  Retail, Industrial Storage, Carts & Islands), each with real gid + full path,
  and a curated set of real child leaf nodes relevant to this catalog (~68
  total, e.g. Deep Fryers, Commercial Refrigerators, Stand Mixers, **Donut
  Makers** — a genuinely real node at
  `hg-11-7-46-2` under Toasters & Grills). Every gid/path was verified against
  the downloaded taxonomy file (tests assert well-formed `gid://shopify/...`
  prefixes + uniqueness — `test_category_taxonomy_gids_are_well_formed_and_unique`).
  Each group is ALSO itself a selectable option (the coarse fallback) alongside
  its more specific children.
- **`taxonomy_pools()` no longer derives `categories` from `Product.category`**
  — those DB values are AI-guessed/scraped free text, frequently identical to
  `product_type` (confirmed: querying both pools returned near-identical
  ~259-value lists full of typos/casing variants/non-product junk like
  "Consulting", "shipping charge"). Category options now come exclusively from
  `CATEGORY_TAXONOMY` (`category_tree` in the API response) —
  `test_taxonomy_pools_exposes_curated_category_tree_not_db_values` guards this.
- **Frontend:** `editColType.category = 'category'` (new type). Both the inline
  cell editor and the bulk-bar field render a `<select>` with one `<optgroup>`
  per real Shopify group (`editCategoryGroups()`), each group offering itself
  (`"<Group> (general)"`) plus its specific real children. No datalist, no
  free-text fallback — the point is that only real, verified values are
  selectable. Stored value is the plain leaf/group name string (e.g. "Deep
  Fryers"); a future GraphQL push would resolve the gid by looking the name
  back up in `CATEGORY_TAXONOMY`.

## Editor UX (columns, pickers, widths)

- **product_type/collections/tags: free-form OR select existing.** Typed
  free-form (datalist autocomplete inline; text box in the bulk bar) OR chosen
  from a "Select existing" checkbox picker — multi-select for list fields
  (collections/tags), single-select for product_type. This picker is now
  available **inline per-cell**, not just in the bulk bar (2026-07-13):
  `editCellPickerOpen`/`editCellPickerFiltered(col)`/`editCellTogglePick(v)`
  mirror the bulk-bar equivalents (`editPoolFor(col)` is the shared pool
  lookup both use) but read/write `editDraft` for the single active cell
  instead of `editBulkValue` across many rows. The picker button uses
  `@mousedown.prevent` (not on the checkboxes themselves) so opening it or
  checking a box doesn't blur the adjacent free-text input and prematurely
  commit/close the cell — checkbox toggling itself happens on `click`, which
  mousedown.prevent doesn't block, only the focus-shift/blur does.
- **category: fixed select with `<optgroup>`, no picker.** Deliberately NOT
  part of the free-form-or-pick flow above (`editPoolFor` has no `category`
  branch) — see "Category taxonomy" above for why.
- **Column show/hide:** "Columns" chooser (`editColVisible`, persisted to
  localStorage; grid loops over `editVisibleColumns()`). Toggling re-wires the
  resizable grid (`_wireEditGrid` resets table-layout + pinned widths so grip
  indices realign).
- **Column default width:** every column (including Title, as of 2026-07-13)
  renders inside `.edit-col-long` (~30-character default, ellipsis, full text
  in the `title` tooltip) — see the two later dated entries below for the full
  history (`editLongCols` was removed; the cap-lift-on-resize is now
  per-column, not per-table).

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

## 2026-07-13 — Removed Wt Unit/Qty columns, fixed dropdown z-index bug, capped all column widths

- **Removed `weight_unit` ("Wt Unit") and `inventory_quantity` ("Qty") columns**
  entirely (backend `COLUMNS`, `_NUMERIC_COLS`, both projections, `_VARIANT_FIELD_KEYS`;
  frontend `editColType`/`editColScope`/`editColLabels`/`editNumericCol`).
  `editWeightUnitOptions` and `editSelectOptions`'s fallback branch removed too —
  `status` was the only remaining `select`-type column.
- **Root-caused the "Columns" dropdown rendering under the grid's header line":**
  confirmed via CDP that `getComputedStyle(dropdown).zIndex === "auto"` despite
  the `z-30` class — the purged `tailwind.min.css` only ships `.z-40`/`.z-50`
  (grepped: no `.z-10`/`.z-20`/`.z-30`). Both the dropdown (`z-30`) and the
  sticky grid `<thead>` (`z-10`) silently fell back to `z-index: auto`, so plain
  DOM order decided paint order — the `<thead>` (later in the DOM) painted over
  the dropdown (earlier in the DOM). Fixed by adding real `.z-10`/`.z-20`/`.z-30`
  rules to `style.css`, same pattern as the existing indigo/amber utilities.
  Verified post-fix: dropdown computes `z-index: 30`, thead stays `auto` → no
  more overlap (screenshot confirmed).
- **All columns now default to ~30 characters**, not just Description.
  `editIsLongCol`/`editLongCols` removed (was an opt-in allow-list of one);
  `.edit-col-long` is now applied to every column's display span, Title
  included. To let a manually-widened column actually show more text (rather
  than padding blank space), `.edit-col-long` switched from `inline-block` to
  `display:block` with a `table.col-resize-active .edit-col-long { max-width: 100%; }`
  override — `col-resize-active` is the class `_wireTableResize`'s `pinTable()`
  already adds to the table on first resize, so no new JS hook was needed.
  Verified: default header widths cap at 244px (~30ch at text-xs) for
  long-text columns (Title/Tags/Collections/Description/Handle), shorter
  columns (Vendor, SKU, etc.) size naturally under that; the CSS override
  flips `max-width` from `30ch` to `100%` once `col-resize-active` is present.

## 2026-07-13 (later) — Column-width cap survived a false-fix; two real bugs found

User reported "column width does not default to 30" after the fix above shipped.
This is the escalation case (bug survived one fix attempt) — traced properly
instead of guessing again. Found TWO distinct bugs in the previous fix, both now
corrected:

1. **The cap-lift was scoped to the whole TABLE, not the resized COLUMN.**
   `pinTable()` adds `.col-resize-active` to the table as soon as ANY column has
   a saved width (even from a single previously-resized column, or literally on
   every page load if `hasSaved`). The CSS rule
   `table.col-resize-active .edit-col-long { max-width: 100% }` matched on that
   table-wide class, so ONE resized column silently lifted the cap for EVERY
   column. Fixed by replacing the class-based rule with `_syncLongColCaps()` in
   `app.js`, which injects a `<style id="colcap-...">` rule scoped per column via
   `:nth-child()` — only for column indices actually present in the saved-widths
   map, keyed to the table via a `data-resize-key` attribute.
2. **Saved widths were keyed by raw array position (`saved[i]`), not by column
   identity.** `_wireEditGrid` (fired on every "Columns" chooser show/hide
   toggle) fully re-wires resize state and re-reads `localStorage` against the
   CURRENTLY VISIBLE `ths` — so hiding/showing any column, or adding/removing a
   column (like Wt Unit/Qty removal earlier this session), shifts every later
   column's index and silently reattaches an old saved width to a DIFFERENT
   column now sitting at that slot. This was pre-existing/latent (triggered by
   the "Columns" chooser feature itself, not just this session's changes) and is
   the more likely full explanation for "every column" being affected. Fixed by
   keying persisted widths (and the cap-lift map) by each column's header LABEL
   text (`_colId(th, i)` — first `<span>` in the header, falling back to
   `textContent`, then a positional placeholder for label-less headers like the
   checkbox column) instead of position. Old numeric-indexed localStorage
   entries from before this fix simply don't match any label now, so they're
   harmlessly ignored rather than misapplied — no migration needed.
   `_syncLongColCaps` takes `colIds` (name → current position) to build the
   `:nth-child()` selector, since CSS selectors are inherently positional even
   though storage keys are now name-based.
- Verified via CDP: (a) seeding stale numeric-indexed `localStorage` (simulating
  pre-fix data at old Wt-Unit/Qty-era indices) — every column still correctly
  defaulted to content-width-capped-at-30ch, none spuriously widened; (b)
  seeding a name-keyed `{"Description": 500}` and toggling the Barcode column's
  visibility off/on — Description stayed pinned at 500px, every other column
  stayed correctly capped, across the toggle.

## 2026-07-13 (later still) — Tags/Collections: top-of-page filter dropdowns + quick bulk toggle

User's ask: Tags/Collections "should be drop downs with checkboxes... displayed
at the top of the page like the column selection drop down." Clarified via
AskUserQuestion this meant **both** filtering and editing (two distinct
mechanisms, same visual pattern as Columns — persistent, immediate per-checkbox
effect, no separate "Apply" step).

- **Filtering (new):** the old "Tag contains…"/"Collection contains…" free-text
  substring inputs in Attribute filters are replaced with "Tags ▾"/
  "Collections ▾" checkbox-dropdown buttons, sourced from `editFacets.tags` /
  `editPools.collections` (the full, pre-filter option lists). Multi-select,
  OR'd within each facet (row matches if it has ANY selected tag AND ANY
  selected collection, when both are set). `editFilters.tag`/`.collection`
  (scalar strings) → `editFilters.tags`/`.collections` (arrays);
  `editToggleTagFilter`/`editToggleCollectionFilter` mutate the array and
  reload immediately, exactly like `editToggleColumn`.
  - Backend: `_matches()` in `edit_products.py` does exact (not substring) set
    intersection now — `f["tags"]`/`f["collections"]` are lists. Route params
    renamed `tag`→`tags`, `collection`→`collections` (comma-separated,
    parsed to a list in `routes.py`).
- **Editing (new, additive):** the bulk edit bar gained dedicated "Tags ▾"/
  "Collections ▾" buttons *before* the generic field/mode/value flow — each
  checkbox toggles that one value across every selected row immediately
  (`editBulkListToggle(field, v)`: Add if any selected row is missing it,
  Remove once every selected row already has it — checked state via
  `editBulkListChecked`). This doesn't replace the generic bulk flow (still
  useful for "Set (replace)" mode, wholesale-replacing a row's list) — it's a
  faster path for the common "add/remove one value" case. Both share
  `editPoolFor(field)` for the option list.
- Verified via CDP: toggling a tag in the new filter dropdown correctly
  narrowed 5,582 variants → 10 matching a specific tag; toggling a tag via the
  new bulk quick-editor on a selected row correctly appended it to that row's
  effective tags and marked the row dirty.

## 2026-07-13 (yet later) — Tags/Collections consolidated to ONE control each + top-level Save

Follow-up refinement: the previous entry's two separate mechanisms (a filter
dropdown in Attribute filters, a quick-edit dropdown in the bulk bar) were
consolidated per the user's explicit spec: "2 checkboxes above tags and 2
checkboxes above collections... filter and edit... mutually exclusive but the
default will be both checkboxes blank."

- **ONE dropdown per field now**, not two. `editTagsMode`/`editCollectionsMode`
  (`null | 'filter' | 'edit'`, default `null`) sit above the "Tags ▾"/
  "Collections ▾" button as two checkboxes labeled Filter/Edit.
  `editSetTagsMode(mode)` toggles: clicking the already-active mode's checkbox
  turns it back to `null` (so "blank" is a reachable, valid state, not just
  the unvisited default) — this is what makes them mutually exclusive AND
  default-blank at once, rather than a plain two-state toggle.
  - Dropdown button is `:disabled="!editTagsMode"` — no mode picked yet =
    nothing to click into.
  - `editTagsChecked(v)`/`editTagsToggle(v)` dispatch on the current mode:
    `'filter'` → same `editFilters.tags` array + reload as before; `'edit'` →
    delegates to `editBulkListChecked`/`editBulkListToggle('tags', v)` (added
    last entry) against whatever rows are currently selected in the grid. If
    edit mode is on but nothing is selected, toggling shows a toast ("Select
    rows first...") instead of silently no-op'ing.
  - Removed the bulk bar's dedicated Tags/Collections quick buttons from the
    prior entry (`editBulkTagsOpen` etc.) — fully superseded by Edit mode on
    the top control. The generic bulk field/mode/value flow still exists
    separately for `tags`/`collections`' "Set (replace)" case, which the
    checkbox toggle (Add/Remove one at a time) doesn't cover.
- **Top-of-page Save button** (header row, next to the "Edit Products" title):
  calls the SAME `editOpenReview()` as the existing "Review & push →" button in
  the summary bar — confirmed with the user first, since Save triggers a live,
  unreversible Shopify write and the push path is still unverified against a
  real store (see Phase 4 notes above). No new push mechanism, just a second,
  more prominent entry point to the existing review/confirm modal. Disabled
  when `editPendingCount() === 0`, shows the pending count as a badge.

## 2026-07-13 (final round) — Filter/Edit checkboxes removed; per-column pop-up instead

Immediate follow-up: the Filter/Edit mode checkboxes (previous entry) are gone
again — replaced with a pop-up modal triggered from the Tags/Collections
column headers themselves, which the user judged a cleaner mechanism for
*editing* specifically (bulk filtering by tag/collection has no UI now; the
backend/`editFilters.tags`/`.collections` capability from two entries up is
left in place, untouched, in case a filter UI returns later — nothing calls it
today, but it's tested and harmless to keep).

- **Removed:** the whole Attribute-filters block with the Filter/Edit
  checkboxes + Tags/Collections dropdown, and its supporting JS
  (`editTagsMode`/`editCollectionsMode`/`editSetTagsMode`/`editSetCollectionsMode`/
  `editTagsChecked`/`editTagsToggle`/`editCollectionsChecked`/`editCollectionsToggle`,
  `editTagsOpen`/`Search`, `editCollectionsOpen`/`Search`) — all dead once the
  UI that drove them was deleted.
- **Added: per-column pop-up editor.** A small "▤" button appears in the grid
  header — `x-show="col === 'tags' || col === 'collections'"` — only visible
  on those two columns (it exists in the DOM for every column via the shared
  header template, per Alpine's `x-show`; only CSS-hidden elsewhere, confirmed
  via `getComputedStyle(...).display` during verification — a plain
  `.textContent` check on the header is misleading since hidden elements'
  text still concatenates in). `@click.stop` keeps it from also triggering
  `editSort(col)` on the same click.
  - Clicking it with **no rows selected** shows a toast ("Select one or more
    rows first") instead of opening — editing without a target is meaningless.
  - With rows selected, opens `editColPopup` ('tags' | 'collections'): a modal
    (same visual pattern as the Review & Push modal) listing every pool value
    with a checkbox to its left, `editColPopupSearch` filter box, scrollable.
  - **Pre-checks whatever the selected row(s) already have** —
    `editColPopupChecked(v)` delegates to `editBulkListChecked(field, v)`
    (checked only if ALL selected rows already carry it; a partially-shared
    value across a multi-row selection reads as unchecked, same convention as
    the earlier bulk quick-toggle — not a new rule).
  - Toggling a checkbox calls `editBulkListToggle(field, v)` immediately
    (Add/Remove across every selected row) — same underlying mechanism as
    before, just triggered from the column header instead of a top-of-page
    control. Nothing pushes to Shopify here; still staged locally until Save.
- Verified via CDP: selected a row with tags `["Donut Nozzles", "Edhard Filler
  Accessories", "Free Shipping"]`, opened the Tags pop-up — modal listed all
  748 pool tags and pre-checked exactly those 3; toggling a new tag correctly
  appended it to the row's effective tags.
