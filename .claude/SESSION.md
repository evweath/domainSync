# Session State — 2026-06-09T18:00:00Z

## Accomplished This Session
- Renamed app from "Donut Intel Platform" to **domainSync** throughout all files
- Changed server port **8743 → 8800**
- Removed 7 pages from frontend and all associated backend code:
  - Competitors page
  - Products (catalog browse) page
  - Source Domain Products page
  - Find This Product page
  - Beat This Price page
  - Find Me Customers page
  - Price Comparison (matrix) page
- Deleted backend modules no longer needed:
  - `backend/competitor/` (entire directory — 7 files)
  - `backend/search/pages/find_product.py`, `beat_price.py`, `find_customers.py`, `competitor_site.py`
- Extracted `_is_shopify_store` / `scrape_shopify_store` from deleted `competitor/scraper.py` into new `backend/scrapers/shopify_scraper.py` so `source_scraper.py` still works
- Restored `GET /api/competitors/managed-lists`, `POST /api/competitors/managed-domain`, `DELETE /api/competitors/managed-domain` — used by Settings page managed-lists UI
- Fixed `addManagedUrl` / `removeManagedDomain` in app.js to call the new slimmer endpoints
- All 4 tests pass; server boots cleanly on port 8800
- Committed as `f7e4d0d` on branch `main`
- Backed up to `~/.claude_home/domainSync/`

## In Progress
- **GitHub push is pending** — the SSH key in `~/.ssh/id_ed25519` is a deploy key scoped only to `evweath/donut-intel`; it cannot push to `evweath/domainSync`

## Next Steps
1. Push to GitHub — pick one:
   - Add the deploy key to `https://github.com/evweath/domainSync/settings/keys` (Allow write access), then run `git push domainsync main`
   - Or: `git push https://<PAT>@github.com/evweath/domainSync.git main`
2. Verify the live app at `https://localhost:8800` — run `bash start.sh` from the project root
3. Optional: update `config/settings.yaml` database path if you want domainSync to use a separate DB from donut-intel (currently shares `./data/donut_intel.db`)

## Key Context
- Project root: `/Users/evw/dev/domainSync/donut-intel/`
- Remote added: `domainsync → git@github.com:evweath/domainSync.git` (write blocked until deploy key added)
- Port: 8800 (set in `config/settings.yaml` and hardened in `backend/app.py` CORS + startup log)
- Settings page managed-lists section still works fully — uses the new trimmed endpoints
- `backend/search/core/` and the search engine shim were preserved (used by source scanning)
- `backend/competitor/` models (Competitor, CompetitorProductMatch) remain in the DB schema and are still referenced by `GET /api/stats` — safe to keep
