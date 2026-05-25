# Session State — 2026-05-21T17:15:00-05:00

## Accomplished This Session

- **Shopify API Credentials UI** (Settings page):
  - Added `shopify_store_url`, `shopify_api_key`, `shopify_access_token` fields to each source site in `config/settings.yaml`
  - `PUT /api/source-sites/{domain}/credentials` — persists credentials by patching the list entry directly (`config._settings["source_sites"]`) and calling `config._save()`
  - `POST /api/source-sites/{domain}/test-connection` — verifies via `/admin/api/2024-01/shop.json`, returns shop name + plan
  - Settings page section: one card per store, Store URL + API Key + Access Token inputs (password masked), Save + Test Connection buttons, inline connection status badge

- **Live Sync pipeline** (`⚡ Live Sync` nav item, commit `52bc202`):
  - `backend/shopify/client.py` — async Shopify Admin REST client, cursor-paginated, rate-limit back-off (leaky bucket), CRUD for products/variants/images/collections/metafields
  - `backend/shopify/scanner.py` — full store scan into snapshot: `{shop, products (by handle), products_by_id, collections, collects, product_collections, collection_products, metafields}`
  - `backend/shopify/differ.py` — diff engine: scalar fields, tags (set diff with MERGE/replace), variants, images, collection memberships; each transaction has `risk_level` (LOW/MEDIUM/HIGH/CRITICAL), `warnings[]`, `affected_relationships[]`
  - `backend/shopify/executor.py` — executes approved transactions: CREATE/UPDATE products, merge/replace tags, add/remove collection memberships, delete images/products
  - New endpoints: `POST /api/shopify-live/scan`, `GET /api/shopify-live/scan-status`, `POST /api/shopify-live/diff`, `POST /api/shopify-live/execute`
  - Scan cache: `_scan_cache` dict in routes.py — in-memory per server process, keyed by domain
  - UI: 5-step workflow (Configure → Diff → Review → Execute → Done), warnings default ON with confirmation-gated disable, per-transaction approve/reject toggle, bulk approve/reject visible or all, filter by risk level or approval state

- **Shopify Sync CSV page** (`🛍️ Shopify Sync`, commit `929c4ee`):
  - 13 attribute groups with MERGE/REPLACE/SKIP per group
  - Preview (product count + row count + 10-row sample) and CSV export
  - Uses scraped `ProductSource` data from DB — not live Shopify API

- **Store Compare page** (`🔀 Store Compare`, commit `b09fe52`):
  - Accordion comparing canonical vs per-source attributes, amber diffs, "Use" button → `PUT /api/products/{id}/canonical`

- **Beat This Price fix** (commit `b09fe52`):
  - `find_suppliers()` now uses `multi_engine_search` (DDG + Bing + Google + Yahoo) — was DDG-only

- **Security**: Anthropic API key was inadvertently committed in `settings.yaml` via the session backup hook, caught by GitHub push protection, scrubbed from the amend before push. Key is now blank in repo — must be re-entered in Settings → AI Categorization.

## In Progress

Nothing — all work committed and pushed (`52bc202` is HEAD on `origin/main`).

## Next Steps

- **Enter Shopify credentials**: Settings → Shopify API Credentials → fill in Store URL + Access Token for each store, then Test Connection
- **Test Live Sync end-to-end**: once credentials are in, pick source + destination, click Scan & Diff, review the transaction queue, approve a small batch, execute
- **Live Sync enhancements** (not yet built):
  - WebSocket progress during scan (currently a blocking spinner — large catalogs can take 2 min)
  - Persist scan snapshots to disk so they survive server restarts
  - Smart collection rule diffing (currently only custom collections are write-synced; smart collections are read-only in Shopify API)
  - Metafield WRITE support in executor (currently only reads metafields during scan)
- **Shopify Sync CSV** (potential):
  - Add `Command` column (MERGE vs REPLACE per Shopify CSV import spec)
  - Multi-source export in one CSV

## Key Context

- **CRITICAL**: `settings.yaml` must NOT be committed with real API keys — the session backup hook commits it automatically. Always check `git diff config/settings.yaml` before pushing, or add it to `.gitignore`
- **Model field names**: `Product` uses `canonical_title`, `canonical_description`, `price_canonical` — NOT `title`, `description`, `price`
- **ProductSource fields**: `source_site`, `source_title`, `source_description`, `source_price`, `source_sku`, `source_manufacturer`, `source_category`
- **ProductImage**: `source_url` (not `url`), `alt_text`
- **ProductOption**: `option_group`, `option_value` (not `name`, `value`)
- **Config list update pattern**: `config.get("source_sites", default=[])` returns plain dicts; to update a list item patch `config._settings["source_sites"]` directly then call `config._save()`
- **Auth**: cookie-based — POST `/api/auth/login` `{"username":"admin","password":"changeme"}`; no Bearer token
- **Server start**: `source .venv/bin/activate && uvicorn backend.app:app --host 127.0.0.1 --port 8743 --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem --reload`
- **NEVER bind to 0.0.0.0** — always use 127.0.0.1 to prevent LAN exposure
- **Port conflict on restart**: use `lsof -ti :8743 | xargs kill -9` before starting
- **Session backup hook** auto-commits everything on stop — always squash with `git reset --soft <last-real-commit>` and re-commit cleanly before pushing
- DB: `data/donut_intel.db` (SQLite WAL mode)
- Source domains: donut-supplies.com, donut-equipment.com, bakerywholesalers.com
- git remote: github.com:evweath/donut-intel.git, branch: main
