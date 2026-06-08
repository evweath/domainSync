# Shopify Sync — Investigation File

## Architecture

```
Shopify Sync page
  → Settings: Shopify API credentials UI (store URL, access token)
  → Source CSV export: GET /api/shopify/export-csv (source-store products → CSV)
  → Live Sync pipeline:
    → routes.py: POST /api/shopify/sync
      → shopify/: authenticates with destination store API
      → pushes product updates (title, price, description, images, status)
      → returns sync log per product
  → frontend: index.html Shopify Sync section + Live Sync page
```

## Confirmed Root Causes (do not re-investigate)

### Live Sync page not rendering (RESOLVED — 2026-05-22)
- **Root cause:** Alpine.js component initialization order — `x-data` scope was referencing a method before the component mounted.
- **Fix:** Reordered component initialization in `index.html` Shopify Sync section.

### Destination store selector missing (RESOLVED — 2026-05-22)
- **Root cause:** Sync page hardcoded destination store; no UI to select which Shopify store to push to.
- **Fix:** Added destination store dropdown to Shopify Sync page.

### Source site scan using slow HTML scrape instead of API (RESOLVED — 2026-05-19)
- **Root cause:** Source-site scanner was fetching and parsing HTML pages. Shopify stores expose `/products.json` which returns structured data much faster.
- **Fix:** Added `/products.json` fast path for source-site scans in `competitor/scraper.py`.

## Known Failure Modes

- **Shopify API rate limits:** Shopify enforces 2 req/s for REST API. Bulk sync can hit this. The sync pipeline should throttle — verify it does before adding more products to sync batch.
- **Access token scope:** Shopify access tokens need `write_products` scope. If sync silently fails, check token scopes in the Shopify Partner dashboard.
- **Credentials storage:** Shopify credentials are stored in `config/settings.yaml` — never commit this file. It's in `.gitignore` as of 2026-05-21.

## Failed Attempts (do not repeat)

| Session | What was tried | Why it failed |
|---|---|---|
| — | — | — |

## Open Questions

- Does the Live Sync pipeline handle partial failures? If 3 of 10 products fail to sync, does it report which ones?
- The CSV export — is it used as input to the Live Sync, or are they independent flows?
