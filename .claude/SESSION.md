# Session State — 2026-05-26T19:30:00-05:00

## Accomplished This Session

- **Bing Shopping scraper** (`backend/search/engine.py` → `_bing_shopping_search`): Fully rewritten. Bing Shopping merchant links use `class="br-offLink"` anchors whose `href` points to `https://www.bing.com/aclick?...&u=<URL-safe-base64>`. The `u=` param base64-decodes to the actual merchant URL. Scraper now finds these anchors, decodes the URL, and extracts title from `<span title="...">` and price from `class="br-price"`. **Returns 10 real merchant results with prices.**

- **Google Shopping / SerpAPI** (`_serpapi_shopping_search`): Rewritten with two-stage fallback:
  - Stage 1: `engine=google` organic — harvests `inline_shopping_results[].link` (direct merchant URLs, query-dependent; sometimes absent)
  - Stage 2: `engine=google_shopping` + concurrent `serpapi_immersive_product_api` calls — fetches `product_results.stores[].link` and `stores[].price` for top 8 results. **Returns 8 real merchant results with prices.**

- **Yahoo Shopping replacement** (`_yahoo_shopping_search`): Yahoo Shopping desktop redirects to "Yahoo Scout" (AI chat); mobile has no product data in server-rendered HTML. Replaced with **Walmart** scraper that parses `__NEXT_DATA__` JSON at `props.pageProps.initialData.searchResult.itemStacks[N].items[M]`. **Returns 10 results with prices.**
  - User asked to retry Yahoo — unblocked sites, retested, confirmed no product data in any Yahoo Shopping URL variant. Will revisit tomorrow.

- Added `import base64` to `backend/search/engine.py` imports.

## In Progress

- **Yahoo Shopping / `yahoo_shopping` engine slot**: User unblocked Yahoo sites and wants to try again tomorrow. Current Walmart replacement works. Outstanding question: keep Walmart, try a different site, or remove the engine.

## Next Steps

1. **Decide on `yahoo_shopping` engine**: options — (a) keep Walmart, (b) try a different comparison shopping site, (c) remove engine. Walmart currently works and returns 10 results.
2. **Restart server and end-to-end test** the full competitor search flow with updated scrapers (Bing + SerpAPI/Google + Walmart confirmed working in isolation; need to verify integration in `multi_engine_search` and `run_product_competitor_search`).
3. **Verify UI flow**: product catalog → select products → competitor search → search-mode card grid → pause modal at 100 domains tried.

## Key Context

- **Server start**: `.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8743 --ssl-keyfile config/key.pem --ssl-certfile config/cert.pem >> logs/uvicorn.out 2>&1 &`
- **Kill port before restart**: `lsof -ti :8743 | xargs kill -9`
- **Auth**: cookie-based — POST `/api/auth/login` `{"username":"admin","password":"changeme"}`
- **venv**: `.venv/bin/python3` (not system python3)
- **CRITICAL**: `config/settings.yaml` contains real API keys — do NOT commit it. Check `git diff config/settings.yaml` before any push.
- **SerpAPI key**: configured and working (64-char key in `settings.yaml` under `serpapi.api_key`)
- **Bing Shopping** is most reliable: no API key needed, 10+ results consistently, uses `br-offLink` base64 decode
- **SerpAPI immersive**: 1 credit for `google_shopping` call + up to 8 more credits for immersive item calls (up to 9 credits/search)
- **Walmart `__NEXT_DATA__` path**: `props.pageProps.initialData.searchResult.itemStacks[N].items[M]` — fields: `canonicalUrl`, `name`, `price` (numeric), `priceInfo.currentPrice`
- **`_yahoo_shopping_search` source label**: still `'yahoo_shopping'` for `multi_engine_search` shopping_indices compatibility
- All scraper changes committed in `7cd9323` and `0f21dc9` on branch `main`
- **NEVER bind to 0.0.0.0** — always use 127.0.0.1
- DB: `data/donut_intel.db` (SQLite WAL mode)
- git remote: github.com:evweath/donut-intel.git, branch: main
