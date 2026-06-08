# donut-intel — Claude Project Instructions

## Architecture Quick Reference

- **Backend:** FastAPI (`backend/app.py`), SQLite via SQLAlchemy (`backend/database/`)
- **Search layer (two-layer split):**
  - `backend/search/core/` — shared plumbing, ONE copy each: `constants.py`, `fetch.py` (`_curl_get`), `parse.py` (`_domain`, `_extract_price/_model`), `engines.py` (the 8 engine adapters), `rank.py` (`multi_engine_search`, `_aggregate_and_rank`, `fuzzy_score`).
  - `backend/search/pages/` — one module per app page, owns query+scoring+shaping only: `find_product.py`, `beat_price.py`, `competitor_site.py`, `find_customers.py`.
  - `backend/search/engine.py` — backward-compat **shim** that re-exports the above. Existing `from backend.search.engine import ...` still works. New code imports from `core/` or `pages/` directly.
  - **Rule:** fix an engine/parsing bug ONCE in `core/`. Change a page's behavior in its `pages/` module without touching others. Never copy plumbing into a page module.
- **Competitor search:** `backend/competitor/` — `product_search.py`, `web_search_scan.py` (Phase 3 TODO: these still hold their own drifted copies of `_parse_jsonld`/`_parse_meta`/`_curl_fetch` — migrate to `core/`).
- **Scrapers:** `backend/scrapers/` — `source_scraper.py`, `yahoo_shopping_scraper.py`
- **Routes:** `backend/api/routes.py`
- **Frontend:** `frontend/index.html` (Alpine.js), `frontend/js/app.js`
- **Config:** `config/settings.yaml` — **never commit, contains real API keys**
- **Server:** `bash start.sh` / `lsof -ti :8743 | xargs kill -9`
- **Tests:** `.venv/bin/python -m pytest tests/ -v`

## Critical Facts (do not re-learn these)

- **Shopping engines** (`shopping`, `bing_shopping`) are the **only** source of structured price data (`$XX.XX`). Organic engines (`ddg`, `bing`, `google`, `yahoo`) almost never return price fields. Any "price is null" bug traces upstream to whether shopping engines are in the search call.
- **Rate limiting:** Bing/Google/DDG rate-limit after heavy use. Empty results from `find_suppliers` are usually rate-limiting, not a code bug. Wait ~1 hour or use the cached-fallback path (`routes.py:2925`).
- **Auth:** POST `/api/auth/login` `{"username":"admin","password":"changeme"}` — cookie-based session.

## Bug Investigation Protocol

**Before writing any code to fix a bug:**

1. **Read `.claude/investigations/<feature>.md`** for this feature. If a prior entry exists, explicitly state what was tried and why it failed before proposing anything new.
2. **Trace the execution path** from the API route/entry point down to where the bad value first appears. Write it out:
   ```
   Route → function → sub-call → where value goes wrong
   ```
3. **State your root-cause hypothesis** in one sentence and ask the user to confirm before editing any file.
4. **Write a failing test first** (in `tests/`) that reproduces the bug. The test must fail before the fix and pass after. Skip this step only for pure UI/CSS bugs.
5. **After the fix:** update the investigation file with what you did, why it worked, and any lessons.

**Escalation rule:** If a bug has survived one failed fix attempt, steps 1–4 above are mandatory — no exceptions.

## Per-Feature Investigation Files

Located in `.claude/investigations/`. Read the relevant file before working on any feature:

- `beat-this-price.md` — Beat This Price search, price display, color logic
- `competitor-search.md` — competitor product search, query building, DB locking, rate limiting
- `store-compare.md` — cross-store diff detection, attribute status
- `shopify-sync.md` — Shopify API credentials, live sync pipeline
- `yahoo-scraper.md` — Yahoo Shopping PLA scraper, domain blocklist

## Testing

- Run tests: `.venv/bin/python -m pytest tests/ -v`
- Run a single file: `.venv/bin/python -m pytest tests/test_engine.py -v`
- Tests must pass before any commit.

## Session Protocol

- At session start: read `SESSION.md` and the investigation file for the feature being worked on.
- At session end: update `SESSION.md` and any investigation files touched this session.
