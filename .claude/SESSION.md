# Session State — 2026-05-21T16:35:00-05:00

## Accomplished This Session

- **Shopify Sync page** (full implementation):
  - Backend: `GET /api/shopify-sync/config`, `POST /api/shopify-sync/preview`, `POST /api/shopify-sync/export` in `backend/api/routes.py`
  - 13 attribute groups: Core Identity, Description, SEO, Pricing, Inventory, Shipping, Options/Variants, Images, Gift Card, Collections, Metafields, Variant Misc, Status/Visibility
  - CSV builder maps `ProductSource` + `Product` fields to all Shopify CSV columns (UTF-8 BOM output)
  - Scope filters: all / source_only / diffs_only
  - Frontend: `🛍️ Shopify Sync` nav item, source store radio, scope selector, search filter, Preview + Export CSV buttons, per-group MERGE/REPLACE/SKIP toggles, All MERGE / Skip All shortcuts, 10-row sample preview table

- **Store Compare page** (implemented earlier this session, already committed):
  - `GET /api/products/store-comparison` endpoint
  - Accordion UI comparing canonical vs per-source attributes across 9 sections
  - Amber-highlighted diffs, "Use" button to adopt source values via `PUT /api/products/{id}/canonical`

- **Beat This Price fix** (implemented earlier this session, already committed):
  - Changed `find_suppliers()` to use `multi_engine_search` (DDG + Bing + Google + Yahoo) instead of DDG-only `_text_search`

- Committed as `929c4ee` ("Add Shopify Sync page for source-store CSV export"), pushed to `origin/main`

## In Progress

Nothing — all work is committed and pushed.

## Next Steps

- **Shopify Sync enhancements** (potential):
  - Add `Command` column to CSV rows (MERGE vs REPLACE per Shopify import spec)
  - Support exporting from multiple source stores in one CSV
  - Add option to include/exclude inactive products
  - Metafields group currently covers only Google Shopping columns; could add custom metafield definitions

- **Store Compare page** (potential improvements):
  - Variant-level comparison (ProductOption rows per source)
  - "Adopt all from source" bulk button per store column

- **General**:
  - 500+ duplicates flagged — may want to review/merge workflow
  - 29 competitors in Competitors tab — price comparison data freshness

## Key Context

- **Model field names**: `Product` uses `canonical_title`, `canonical_description`, `price_canonical`, `price_min`, `price_max` — NOT `title`, `description`, `price`
- **ProductSource fields**: `source_site`, `source_url`, `source_title`, `source_description`, `source_price`, `source_sku`, `source_manufacturer`, `source_category`
- **ProductImage field**: `source_url` (not `url`), `alt_text`
- **ProductOption fields**: `option_group`, `option_value` (not `name`, `value`)
- **Product relationships**: `product.sources` (list of ProductSource), `product.images`, `product.options`, `product.tags`
- **Config access**: `config.get("source_sites", default=[])` returns list of dicts with `domain`, `name`, `enabled` keys
- **Auth**: Cookie-based session — POST `/api/auth/login` with `{"username":"admin","password":"changeme"}`; no Bearer token
- **Server start**: `source .venv/bin/activate && uvicorn backend.app:app --host 0.0.0.0 --port 8743 --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem --reload`
- **Session backup hook** auto-commits on stop — squash these with `git reset --soft <last-real-commit>` before pushing
- DB: `data/donut_intel.db` (SQLite WAL mode)
- Source domains: donut-supplies.com, donut-equipment.com, bakerywholesalers.com
- git remote: github.com:evweath/donut-intel.git, branch: main
