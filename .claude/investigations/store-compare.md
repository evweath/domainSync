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
