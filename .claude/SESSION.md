# Session State — 2026-05-11T17:30:00

## Accomplished This Session

- Restarted service (was not running)
- Fixed `donutequipment.com` (ID 28) base_url from `/d_en/` path → `https://www.donutequipment.com/`
- Deactivated `bakeryequipment.com` (ID 26) — completely blocked, all requests fail
- Fixed `session_scope()` rollback bug in `run_competitor_scan`: consecutive_failures now properly increments in a separate inner session
- Added skip threshold: competitors with ≥10 consecutive failures are skipped with INFO log (not ERROR spam)
- Added per-product competitor search feature:
  - Products page now shows 1 entry per unique canonical title (4815 → 1931 unique)
  - Checkboxes on every product row + select-all header
  - "Competitor Search" bar with "find up to N competitors per product" input
  - Sequential search: visits result URLs one at a time, stops when N unique competitor domains with matches found
  - Real-time progress via WebSocket (shows current domain being visited)
  - On completion: refreshes Competitors + Price Comparison screens
  - New API: `POST /api/products/competitor-search`
  - New file: `backend/competitor/product_search.py`
- All changes committed: `4edd75a`

## In Progress

- Nothing actively in progress

## Next Steps

- Test Competitor Search feature end-to-end from the UI (Products page → check boxes → Competitor Search button)
- Watch logs for new ERROR patterns post-restart
- Consider manually setting consecutive_failures for `restaurantware.com` to trigger the skip threshold (old session bug kept it at 0; will auto-increment on next failed scan now)
- rfbakery.com and chefstore.com still fail on sitemap fetches — deactivate if consistently unreachable

## Key Context

- Service: `https://127.0.0.1:8743` (PID 54118, self-signed cert, localhost only)
- Auth: admin / changeme (session-based cookies)
- DB: `data/donut_intel.db` (SQLite WAL mode)
- Source domains: donut-supplies.com, donut-equipment.com, bakerywholesalers.com
- Active competitors: ald.kitchen, bakemark.com, bakesupplyplus.com, chefstore.com, chefstoys.com, ckitchen.com, discountbakeryequip.com, donutequipment.com, katom.com, restaurantsupply.com, restaurantware.com, rfbakery.com
- ddgs package (not duckduckgo-search) — always pass `backend='duckduckgo'`
- git remote: github.com:evweath/donut-intel.git, branch: main
- Products page dedup: `unique_by_title=True` (default) in `list_products` API — `backend/api/routes.py:155`
- New competitor search endpoint: `POST /api/products/competitor-search` — `{product_ids, max_competitors, max_urls}`
- Product search file: `backend/competitor/product_search.py`
- Product search progress events: `product_comp_search_progress`, `product_competitor_search_complete`, `product_competitor_search_error`
- Scraping profile model: `backend/database/models.py:CompetitorScrapingProfile`
- Scraping profile API: `GET/PUT /api/competitors/{id}/profile` (`backend/api/routes.py:~765`)
