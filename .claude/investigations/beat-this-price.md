# Beat This Price — Investigation File

## Architecture

```
POST /api/beat-price
  → routes.py: find_suppliers(description, price_min, price_max, ...)
    → engine.py: multi_engine_search(query, engines=[...])  ← CRITICAL: must include 'shopping','bing_shopping'
    → engine.py: _score_and_merge()  ← preserves price across domain dedup
    → engine.py: _aggregate_and_rank()
  → routes.py: returns BeatPriceResult rows (or cached fallback)
Frontend: index.html:2303 renders price column; app.js:2036 colors price diff
```

## Confirmed Root Causes (do not re-investigate)

### Price null for all results (RESOLVED — 2026-06-05)
- **Root cause:** `find_suppliers` called `multi_engine_search` with only organic engines (`ddg`, `bing`, `google`, `yahoo`). Shopping engines were in a separate `_google_shopping_search` call that returned 0 results.
- **Fix:** Added `shopping`, `bing_shopping` to `multi_engine_search` call at `engine.py:1198`.
- **Key insight:** Organic search snippets almost never contain `$XX.XX` price patterns. Shopping engines are the only reliable source. Any future "price null" bug: check the engine list first.

### Price lost during domain dedup (RESOLVED — 2026-06-05)
- **Root cause:** `_score_and_merge` overwrote a lower-fuzzy shopping result (which had a price) with a higher-fuzzy organic result (no price), discarding the price.
- **Fix:** Added price carry-over logic at `engine.py:1241–1247`. If the new winner has no price but the displaced entry did, copy the price. Also promotes price from lower-score result if winner lacks one.

### Price column hidden when null (RESOLVED — 2026-06-05)
- **Root cause:** Frontend template had `x-show="r.price != null"` on outer price div, hiding the entire column slot when price was null.
- **Fix:** Removed the outer `x-show`; price slot always renders — shows `—` for null, actual value otherwise (`index.html:2303`).
- **Lesson:** Never hide the entire UI slot for missing data — it makes null invisible vs. "data shows slot is empty."

### Color logic inverted (RESOLVED — 2026-06-05)
- **Root cause:** Competitor cheaper than us was colored GREEN, competitor more expensive was RED. Inverted.
- **Fix:** Corrected in `index.html:2305`, `index.html:2309`, and `app.js:2036`.
- **Rule:** Competitor cheaper = RED (bad for us). Competitor more expensive = GREEN (we win).

## Known Failure Modes

- **Rate limiting:** Empty results from `find_suppliers` are usually Bing/Google/DDG rate-limiting, not a code bug. Cached fallback added at `routes.py:2925` — loads most recent `BeatPriceResult` rows from DB. Wait ~1 hour for rate limits to clear.
- **Zero shopping results despite correct engine list:** Check if the SerpAPI key in `config/settings.yaml` is valid and has quota.

## Failed Attempts (do not repeat)

| Session | What was tried | Why it failed |
|---|---|---|
| ~5 sessions before 2026-06-05 | Frontend null-check fixes, CSS display tweaks, color class changes | Root cause was upstream — `r.price` was null before reaching the frontend |
| Pre-fix | Checked `_score_and_merge` dedup logic | Dedup was a secondary issue; primary was shopping engines missing entirely |

## Open Questions

- Does `_google_shopping_search` ever return results? It's still called for model-number supplemental searches (`engine.py:1209`). Unclear if it works reliably vs. just `multi_engine_search` with shopping engines.
