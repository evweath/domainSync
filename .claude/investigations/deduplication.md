# Deduplication — Investigation File

## Definition of a duplicate (current — set 2026-06-23)

A **duplicate** is the **same product listed more than once WITHIN one store**
(source site / shopify domain). Specifically:

- Same store (shared `source_site`) — **required**.
- Identical or near-identical product name/title, manufacturer, and price.
- **Manufacturer must be the same maker** — spelling variants, word-order, and
  longer/shorter forms count (fuzzy), but a genuinely different manufacturer is
  never a duplicate.
- **Variants** (same product, different size/weight/color option) are NOT
  duplicates.
- Size/weight is NOT mandatory for the match (too often missing in scraped data).
- The same product in **different stores** is NOT a duplicate — that is a
  cross-store comparison, surfaced on the **Store Comparison** page (see
  `store-compare.md`).

## Architecture

```
backend/dedup/engine.py    DeduplicationEngine.run() — O(n²) pair comparison
backend/dedup/matchers.py  compute_confidence() — weighted score + disqualifiers
backend/dedup/force_merge.py  explicit cross-site catalog linking (sync pipeline)
config/settings.yaml       deduplication: weights + thresholds
```

## Behavioral change (2026-06-23): cross-store → same-store

- **Before:** `engine.run()` compared products only across DIFFERENT source
  sites and SKIPPED same-store pairs (`if sites_a == sites_b and len(sites_a)==1: continue`).
  Its purpose was cross-store catalog unification.
- **After:** It only compares products that **share a common source site**
  (`if not (sites_a & sites_b): continue`). Duplicates are now within-store.
- **Manufacturer is now a hard disqualifier** in `compute_confidence()`: if both
  products have a manufacturer and `fuzz.token_set_ratio(a, b) < 80`, the pair is
  capped at 5.0 with `disqualifier="manufacturer_mismatch"`. `manufacturer_match()`
  now uses `max(token_sort_ratio, token_set_ratio)` so same-maker name variants
  score high enough to clear the review threshold.
- **Left untouched:** the merge / reject actions, `_merge_products`, and
  `force_merge_source_sites()` (the explicit cross-store catalog linker).

### Auto-merge disabled (2026-06-23)
- Per user: "do not keep automerge … if I want to merge data between stores I
  want it manually invoked." `engine.run()` no longer calls `_merge_products`.
  Every pair scoring ≥ `manual_review_threshold` is recorded as a **pending**
  `DuplicateCandidate` for the user to merge/reject in the UI. `stats["auto_merged"]`
  is now always 0 (kept for compatibility / the periodic-commit counter).
- `_merge_products` and `manual_merge` still exist and are reachable via the
  resolve endpoint (`POST /api/dedup/candidates/{id}/resolve` with action "merge").
- Test: `test_high_confidence_duplicate_is_flagged_not_auto_merged`.

### Consequence to remember
`engine.run()` no longer auto-merges the same product across stores. Cross-store
catalog unification now depends solely on `force_merge_source_sites()`. If the
unified-catalog/Store-Compare view starts missing cross-store links, that's why —
run/inspect force_merge, don't "fix" the engine back to cross-store.

### Canonical price was a synthetic average (FIXED — 2026-06-23)
- **Symptom:** Duplicate Review / Store Compare showed a product price that matched no store. E.g. PID 7857 displayed $1149.24 while all its stores actually list $1185.15.
- **Root cause:** `_merge_products` set `price_canonical = sum(all_prices)/len(all_prices)` where `all_prices` mixed BOTH products' `price_canonical` + `price_min` + `price_max` (engine.py, old line ~238, comment "first pass: use average"). The mean equals no real price, includes stale min/max, and drifts every merge. PID 7857 = mean(1077.41, 1185.15, 1185.15) = 1149.24.
- **Why the field exists:** `price_canonical` is the single "our price" consumed by exports (`exporter.py` → written to Shopify/CSV), reports/beat-price (`reporter.py`), competitor matching (`routes.py:1678`), and price filter/sort. A representative price is genuinely needed; averaging was just the wrong way to pick it.
- **Fix:** New `recompute_product_prices(session, product)` in engine.py — `price_canonical` = most-recently-scraped **active source price** (a real store price); `price_min`/`price_max` = range across active source prices. `_merge_products` now calls it instead of averaging. `recompute_all_product_prices(session)` backfills.
- **Backfill run 2026-06-23:** recomputed 4603 active products. PID 7857 1149.24 → 1185.15; PID 9 23060.54 → 21900.0.
- **Going forward:** scraper already sets `canonical = scraped.price` on update (most-recent for that source); merge now recomputes. So canonical stays a real price.

### Residual data-hygiene notes (not bugs in this logic)
- Some products have MULTIPLE active `ProductSource` rows for the same site/url (e.g. PID 9 had 5 active donut-supplies.com rows incl. a 28452.05 outlier), inflating price_min/max. Re-scrapes aren't deactivating superseded sources. Separate cleanup.
- Old CROSS-store `DuplicateCandidate` rows (created before the same-store change) still exist as pending and won't be re-scored by `run()` (no shared site). Their stored `match_reasons` may be stale. Consider clearing them.

## Tests

`tests/test_dedup.py`:
- `test_same_store_duplicate_is_flagged` — two near-identical listings in one store → 1 candidate.
- `test_cross_store_match_is_not_a_duplicate` — same product, two stores → `comparisons == 0`.
- `test_different_manufacturer_same_store_not_flagged` — compared but disqualified.
- manufacturer matcher tests: different maker disqualified; spelling/longer-form variants not.

## Scoring reference (config/settings.yaml `deduplication`)

weights price 40 / model 35 / manufacturer 15 / title 20 / description 10 (total 120);
`auto_merge_threshold` 85, `manual_review_threshold` 60, `price_tolerance_percent` 2.0.
Hard disqualifiers (cap 5.0): manufacturer_mismatch, model_number_mismatch, sku_mismatch.
