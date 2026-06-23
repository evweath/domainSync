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

## Connection Troubleshooting Panel (2026-06-08)

Settings → **🔌 Shopify Connection Log** shows live output of connection attempts to
source stores (2"-wide box, polls every 3s while Settings is open).

- **Where events are emitted:** `backend/shopify/client.py` records to
  `backend/shopify/connlog.py` (a dedicated 200-line ring buffer, separate from the
  main `log_tail` buffer so connection lines aren't pushed out during scans).
  Instrumented points: `fetch_access_token` (auth), `ShopifyClient.__aenter__`
  (session open), `get_shop` (✓ connected), and `_get` (429 / HTTP errors / network
  errors). All source-store reads go through these, so every attempt is captured.
- **Markers:** `→` attempt, `✓` success, `✗` failure, `…` rate-limit wait. Frontend
  colors lines by marker. **Secrets (tokens, client_secret) are never logged** — only
  host, status, and message.
- **API:** `GET /api/shopify/connection-log?n=150` → `{lines:[...]}`;
  `POST /api/shopify/connection-log/clear`.
- **Buffer is per-process, in-memory** — cleared on server restart. If the panel is
  empty after a restart, that's expected until the next connection attempt.

### Connect failures + per-store auth (DIAGNOSED 2026-06-08)
- **Symptom:** `ConnectError: All connection attempts failed` / `ConnectTimeout` when connecting source stores after a credentials reset.
- **Root cause #1 (network):** This machine is on a VPN/corporate network (`utun0–3`, `10.141.222.x`) with **intermittent/flapping outbound egress**. Live tests to Shopify's IP (`23.227.38.74:443`) alternated CONNECTED / "Network is unreachable" / ConnectTimeout within ~2 min, then went 8/8 stable. DNS is dual-stack. The error is purely TCP-layer (no HTTP response) — credentials are irrelevant to it.
  - **Fix applied:** retry-with-backoff on transient `httpx` connection errors in `client.py` (`_with_connect_retry`, 4 attempts, 0.6→1.2→2.4→4.8s) wrapping `fetch_access_token` + all `ShopifyClient` request methods, plus explicit `connect` timeouts. After this, all three stores reached Shopify with no ConnectError.
- **Root cause #2 (per-store creds):** With the network mitigated, `client_credentials` token exchange results split:
  - `donut-supplies.com` → **works end-to-end** (token + get_shop OK, plan professional). Proves the `client_credentials` algorithm + flow are valid (earlier doubt about it was wrong).
  - `donut-equipment.com` (equipmentplus) and `bakerywholesalers.com` (bakery-wholesalers) → Shopify returns **HTTP 400 "Oauth error invalid_request"** at auth. That's a credential rejection, not a network issue → **the client_id/client_secret for those two stores are wrong / mismatched / not configured for the token exchange.** Re-enter those two stores' API credentials (correct app for that store, no whitespace).
- **Diagnostic value of the panel:** `✗ ... ConnectError` = network/egress; `✗ Auth ... 400` = credentials. The panel distinguishes them directly.
- **CORRECTION (2026-06-22):** Root cause #2's "credentials are wrong" conclusion was a symptom, not the cause. The real reason donut-equipment / bakerywholesalers / equipmentplus fail is that **the Shopify app ("sync"/"sync2") cannot be installed on those stores at all** — Shopify rejects the install with an OAuth error and only offers a dev store ("My store 2"). No valid token can exist for a store the app isn't installed on, so the 400 at auth and the later 403 read_products are both downstream of a missing install. donut-supplies works because the app IS installed there (likely same Plus org). See next entry.

### Scan Now 403 "requires merchant approval for read_products scope" (DIAGNOSED + MITIGATED — 2026-06-22)
- **Symptom:** Live Sync → **Scan Now** fails with `✗ Scan failed: Shopify API 403: {"errors":"[API] This action requires merchant approval for read_products scope."}` — even though Settings shows the store as "✓ Connected".
- **Trace:** `runLiveScan` (app.js) → `POST /api/shopify-live/scan` (routes.py) → `_get_site_credentials` (token exchange **succeeds**) → `scan_store` → `ShopifyClient._get("/products.json")` → **403 here** → `ShopifyError` → toast.
- **Root cause (NOT a code bug):** The `client_credentials` token is valid but the Shopify custom app on that store was never granted the `read_products` Admin API access scope by the merchant. Shopify enforces scopes **per-endpoint**: `/shop.json` needs none, `/products.json` needs `read_products`.
- **Why "use the Settings connection" didn't help:** Scan Now already uses the *same* channel (`_get_site_credentials`, same token). The old Settings test only read `/shop.json` (no scope) so it reported "Connected" while products were still blocked — a misleadingly green check.
- **Real fix (Shopify-side only):** Shopify Admin → Settings → Apps and sales channels → Develop apps → (app) → Configuration → Admin API access scopes → enable `read_products` (+ `write_products` for sync) → Save → re-install/approve.
- **Code mitigations applied (don't re-investigate these as bugs):**
  - `backend/shopify/client.py`: added `missing_scope(status, body)` + `ShopifyError.missing_scope` — parses the un-granted scope name from a 403 body (`_SCOPE_APPROVAL_RE`). Tested in `tests/test_shopify_scope.py`.
  - `routes.py /api/shopify-live/scan`: catches `ShopifyError`, and on a scope 403 returns an actionable message naming the store + scope + where to enable it (instead of raw JSON).
  - `routes.py /api/source-sites/{domain}/test-connection`: now **also probes `/products.json?limit=1`** after `/shop.json`. Returns `products_ok` and, when false, `missing_scope`/`warning`. Frontend (`app.js` + `index.html`) shows a new amber **⚠ warn** badge ("Connected, but missing 'read_products' scope…") so Settings no longer falsely reports full connectivity.
  - `client.py fetch_access_token`: now logs the **scopes Shopify actually granted** the token (the `scope` field it used to discard) to the Connection Log — ground truth for "config says enabled but token lacks it" disputes. Scopes aren't secret.

### App cannot be installed on the target stores → pre-issued token path (2026-06-22)
- **Real blocker (Shopify-side, not code):** Shopify refuses to install the Partner app ("sync"/"sync2") on `donut-equipment.com`, `bakerywholesalers.com`, `equipmentplus.myshopify.com` — only on the dev store "My store 2". A `client_credentials` token can't exist for a store the app isn't installed on, so the 400-at-auth and 403-read_products were both downstream symptoms. `donut-supplies.com` works because the app IS installed there (likely same Plus org; client_credentials is generally Plus-org-gated).
- **Two real fixes (merchant/Shopify side):** (1) create a custom app **inside each store's own admin** (Settings → Develop apps) — store-local, can't be refused, yields a permanent Admin API access token; or (2) set up Partner **custom distribution** / bring stores into the same Plus org.
- **Code support added for fix #1 — pre-issued token path:**
  - `routes.py _static_token(site)`: if a site has `shopify_store_url` + `shopify_access_token`, `_get_site_credentials` returns them verbatim and **skips the client_credentials exchange and token cache entirely**. Client_id/secret become optional when a token is present. Tested in `tests/test_site_credentials.py`.
  - Storage/UI were already in place: `ShopifyCredentialsRequest.shopify_access_token`, the save endpoint, and the Settings "Access Token (shpat_…/atkn_…)" input all predate this — only the resolution in `_get_site_credentials` was missing.
  - **To use:** in each problem store's admin create a custom app with `read_products`/`write_products`, install it, copy its Admin API access token into Settings → that store → Access Token, Save. Scan/Sync then authenticate with that token directly.

### Store facts corrected + the in-admin app blocker (2026-06-22)
- **Plus-org theory was WRONG.** No store is on Plus — all are on **Grow**. `donut-supplies.com` works NOT because of org membership (it's *not* in the org) but because it has its own in-admin custom app **"dsm"**. So "client_credentials needs Plus org" is false; per-store custom apps are the working pattern.
- **The three target stores are in the same org as apps sync/sync2.** User has **admin** (not necessarily *owner*) on all stores.
- **Real remaining blocker:** Creating an in-admin custom app requires **"Allow custom app development"**, which **only the store OWNER can enable** — admin/staff access is not enough. On `equipmentplus.myshopify.com` it was enabled (user created an Admin API key with the right scopes ✅). On `donut-equipment.com` and `bakerywholesalers.com` the option isn't offered → custom app development is still disabled there and the **store owner must turn it on** (Settings → Apps and sales channels → Develop apps → Allow custom app development).
- **Status:** equipmentplus is unblocked via the pre-issued token path — paste its Admin API token into Settings → Access Token. The other two are blocked on the owner enabling custom app development; no code change can bypass that.
- **Admin API access token is shown ONCE.** In an in-admin custom app you can always re-read the API key + API secret key, but the **Admin API access token** (`shpat_…`) is revealed only once right after Install (a "Reveal token once" link). If missed, uninstall + reinstall the app to regenerate it, then copy immediately. Alternatively, try the API key/secret via the existing client_credentials path first (that's how donut-supplies' "dsm" works) — only fall back to reinstalling for the token if that returns 400 invalid_request.

### CRITICAL: NO store can read products — even donut-supplies (REVEALED 2026-06-22)
- The new `/products.json` probe in test-connection shows **donut-supplies' app ("dsm") connects but lacks read_products** — same as the others. The 2026-06-08 "donut-supplies works end-to-end" conclusion was wrong: it only ever exercised `/shop.json` (no scope). **So API product read has never worked on any store**; the whole symptom chain reduces to "no app with read_products is installed anywhere."
- **Why they can't just add the scope:** sync/sync2/dsm are **Partner-dashboard apps**. Changing scopes there requires releasing a **new app version** and the merchant **re-authorizing via the OAuth install flow** — and that install flow is exactly what throws the OAuth `invalid_request` error on these stores. There is no in-place "edit scopes" for a Partner app the way there is for an in-admin custom app.
- **Escape hatch = in-admin custom apps** (Settings → Develop apps), which sync/sync2/dsm are NOT. In-admin apps: scopes are **editable in place** (Configuration → Admin API access scopes → Edit), reinstall is one click **inside the store admin with no external OAuth redirect**, and they issue a static Admin API token the new `_static_token` path consumes. This sidesteps the OAuth-install error entirely. Blocked only by the per-store owner "Allow custom app development" gate.
- **Recommended proof path:** pick ONE store with custom-app-dev available (equipmentplus already has an in-admin app; or donut-supplies, not in the org), create/edit an in-admin app with read_products+write_products, use its token, confirm Scan Now. Then replicate.
- **Possible code fallback (not yet built):** the **public storefront** `https://<store>/products.json` needs no auth/scope but returns only *published* products with limited fields (no drafts/archived/metafields/cost). Insufficient for full sync, but a candidate read path if no app can ever be authorized. The existing `competitor/scraper.py` already uses a /products.json fast path — different from Admin API scan_store.

### Intermittent "Load failed" on save/any request — uvicorn keep-alive (FIXED 2026-06-22)
- **Symptom:** Editing a form for a few seconds then Saving shows "Load failed"; a refresh + retry works. Not a server crash (server stays up, curl returns 200).
- **Root cause:** `start.sh` ran uvicorn with the **default `--timeout-keep-alive 5`**. After ~5s idle the server closes the keep-alive socket, but the browser reuses it for the next request → dead socket → fetch() rejects with TypeError "Load failed". Also made successful saves look failed (the post-save `loadSettings()` refresh hit the dead socket inside the same try/catch).
- **Fix:** (1) `start.sh` now passes `--timeout-keep-alive 75` on both uvicorn invocations; (2) `app.js api()` retries once (200ms) on a network-level fetch rejection before surfacing it. Unrelated to the earlier post-`kill -9` "load failed", which was a one-off severed socket on restart.

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
