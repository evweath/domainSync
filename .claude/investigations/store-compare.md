# Store Compare — Investigation File

## Architecture

```
Store Compare page
  → routes.py: GET /api/store-compare
    → database: queries products across source sites (DS, BW, DE)
    → computes diffs: price, title, description, images, status per product
  → frontend: index.html store-compare section
    → filter panel (attribute checkboxes, diffs-only toggle)
    → per-product attribute status display
```

## Confirmed Root Causes (do not re-investigate)

### Diffs Only filter returning empty results (RESOLVED — 2026-05-21)
- **Root cause:** Diff detection logic was comparing stringified field values without normalization — trailing spaces, case differences, and float formatting caused false "same" comparisons, making Diffs Only filter return nothing.
- **Fix:** Normalized field values before comparison in `routes.py` store-compare diff detection.

### DS/BW products not appearing in DE catalog view (RESOLVED — 2026-05-27)
- **Root cause:** Source-site products (DS = source A, BW = source B) were not being force-merged into the DE catalog view when no exact match existed.
- **Fix:** Added force-merge logic: if a DS/BW product has no DE counterpart, include it as a catalog entry with source=DS/BW.

### Product status not tracked per source site (RESOLVED — 2026-05-21)
- **Root cause:** Status (active/draft/archived) was stored at product level, not per source site. A product archived on BW but active on DE appeared as archived everywhere.
- **Fix:** Added per-source status tracking; status is now stored and compared per site.

## Behavioral Changes (not bugs)

### `missing_from` filter: count-based → per-store (CHANGED — 2026-06-22)
- **What changed:** The "Missing from store:" dropdown on the Store Compare filter panel used to be count-based (Any / 1+ / 2+ / All stores) and `missing_from` was an `int` meaning "missing from at least N stores." It is now a **per-store** filter: options are "All" + one entry per `storeComp.source_sites` (label = `site.split('.')[0]`), and the selected value is a store domain.
- **Files:**
  - `frontend/index.html` — dropdown now `<option value="">All</option>` + `x-for` over `storeComp.source_sites`. Also added 3 `&nbsp;` after "Diffs only" label (cosmetic spacing).
  - `backend/api/routes.py` — `missing_from` param type `int` → `str`; gating changed `missing_from is not None` → `missing_from`; filter logic now `if missing_from and missing_from in site_srcs: continue` (keep only products where the selected store has no active source record). The old `missing_n` count computation was removed.
- **Why it's safe:** Frontend only sends `missing_from` when non-empty (`app.js` `f.missing_from !== ''`), so the empty-string "All" case never reaches the backend gate.
- **Note:** The old count-based filter is GONE — not kept alongside the new one. If a future request wants both, split into two separate controls/params.

### Store A vs Store B pairwise comparison (ADDED — 2026-06-23)
- **What changed:** Added two new dropdowns ("Compare store: Store A vs Store B") at the top of the Store Compare filter panel. Selecting both restricts the comparison to just those two stores; the cross-store "same product across stores" insight (formerly the implicit purpose of the dedup engine) now lives here.
- **Files:**
  - `backend/api/routes.py` — `GET /api/products/store-comparison` gained `store_a`/`store_b` params. When either is set, `source_sites` (the comparison columns) is scoped to `compare_pair`, and `base_q` is filtered to products with an active source on at least one selected store (`Product.sources.any(...)`). With both unset, behavior is unchanged (compare across all configured stores).
  - `frontend/js/app.js` — `storeCompFilters` gained `store_a`/`store_b`; sent as params in `loadStoreComparison`; reset in `storeCompClearFilters`; counted in `storeCompHasActiveFilters`.
  - `frontend/index.html` — new "Row 0" with the two store `<select>`s (options from `filterOptions.source_sites`).
- **Also:** Removed the "Any Stock" (`in_stock`) dropdown from the panel (Row 2 grid `lg:grid-cols-6` → `lg:grid-cols-5`). The `in_stock` state field + backend param remain (harmless, just no longer surfaced in the UI).
- **`filterOptions` was never defined.** The Manufacturer/Category/Source-site dropdowns referenced `filterOptions.*` in the HTML but `filterOptions` had no Alpine state and nothing loaded `/api/products/filters/options`, so they were silently empty. Added `filterOptions` state + `loadFilterOptions()` (called in `postLoginInit`). This is why those dropdowns now populate.

### Price "false same" — absent price coerced to 0.00 (FIXED — 2026-06-23)
- **Symptom (reported):** Store comparison said the price was the same across stores for a product whose prices actually differ.
- **Root cause (frontend logic):** `storeCompCellStatus` normalized price with `Number(v || 0).toFixed(2)`, so a null/absent price became `"0.00"`. That string is truthy, so the `if (!sNorm) → 'missing'` branch could NEVER fire for price; an absent price compared as a real `0.00` and read as a 'match' (green ✓ "same") instead of 'missing' (✕).
- **Fix:** `app.js storeCompCellStatus` — for `fieldType === 'price'`, return `''` for null/undefined/'' (a real `$0.00` is still kept). Now an absent price correctly resolves to 'missing'/'empty', not a false 'match'.
- **NOT the bug:** The `/api/system-of-record` "matching" classifier was audited against live data — 0 cases where a "matching" product had differing stored prices (e.g. pid 5104 = 473.54/473.54). Its `_norm` price rounding (`f"{v:.2f}"`) is sound. If SOR shows equal prices that differ on the live store, that is **stale scrape data**, not a logic bug.

### FINDING (not yet changed): comparison drops sources under non-configured domains
- `/api/products/store-comparison` only builds source columns for `config.source_sites` (enabled). The DB holds listings under legacy domains (`donut-supplies.com`, `bakerywholesalers.com`, `donut-equipment.com`) that do NOT all match the configured myshopify domains (`donut-supplies-com.myshopify.com`, `bakery-wholesalers.myshopify.com`, …). Result: a product's differing-price listings under legacy domains are silently dropped, so across 2000 products **no** product ever shows ≥2 priced stores → cross-store price diffs are invisible on this page. (The SoR view avoids this because you pass explicit `primary`/`compare_to` domains.) Needs a product/config decision: alias legacy↔myshopify domains, migrate `source_site` values, or compare over the union of configured + actual source sites. Also note `config.source_sites` contains a junk `"https:"` entry.

## Known Failure Modes

- **Stale scrape data:** Store Compare reflects whatever was last scraped. If a source site hasn't been scraped recently, diffs will be stale. Check scrape timestamps before investigating "wrong" diffs.
- **Fuzzy match misses:** The force-merge logic relies on fuzzy title matching to link DS/BW products to DE products. Very different titles (same product, different naming convention) will appear as separate rows instead of being linked.

## Failed Attempts (do not repeat)

| Session | What was tried | Why it failed |
|---|---|---|
| Pre-2026-05-21 | Filtering by `product.status` field | Status was a single field, not per-source — always matched DE's status |

## Open Questions

- The comprehensive filter panel added 2026-05-27 — does it correctly handle products that exist on only one source? (e.g., DS-only product with no DE counterpart)
- Image diff detection: are we comparing image URLs or actual image content? URL changes on re-upload would trigger false diffs.
