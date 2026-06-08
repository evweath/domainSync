# Yahoo Shopping Scraper — Investigation File

## Architecture

```
Yahoo Shopping PLA scraper
  → scripts/: yahoo scan command (CLI trigger)
  → backend/scrapers/yahoo_shopping_scraper.py
    → fetches Yahoo Shopping search results (PLAs with price + merchant)
    → parses price, merchant, product URL from PLA markup
    → stores as CompetitorProduct or BeatPriceResult rows
  → blocklist: filters known noise domains before storing
```

## Confirmed Root Causes (do not re-investigate)

### Yahoo scraper returning wrong domains (RESOLVED — 2026-05-27)
- **Root cause:** Yahoo PLA links go through a redirect (`shopping.yahoo.com/...`). Scraper was storing the redirect URL domain (`shopping.yahoo.com`) instead of the final merchant domain.
- **Fix:** Added redirect resolution to extract the actual merchant domain. See `yahoo_shopping_scraper.py`.

### False positive results from aggregator/directory sites (RESOLVED — 2026-05-27)
- **Root cause:** Sites like PriceGrabber, Bizrate, and shopping aggregators appeared as "competitors" because they list the product. They're not actual competing stores.
- **Fix:** Expanded blocklist in `yahoo_shopping_scraper.py` to filter known aggregators, directories, and marketplaces that aren't direct competitors.

## Known Facts

- Yahoo Shopping PLAs are live and active as of 2026-06-02. `search.yahoo.com` shows PLAs with prices and merchant names for product searches. This is a valid, active data source.
- Yahoo scraper does not require an API key — it scrapes the public search page. This means it can be rate-limited or blocked; rotate user agents if results drop off.

## Known Failure Modes

- **Yahoo changing PLA markup:** Scrapers break silently when Yahoo changes its HTML structure. If scraper returns 0 results but Yahoo shows PLAs in browser, inspect the current DOM and update CSS selectors in `yahoo_shopping_scraper.py`.
- **Rate limiting:** Yahoo will 429 or serve a CAPTCHA page after heavy scraping. Implement delays between requests.

## Failed Attempts (do not repeat)

| Session | What was tried | Why it failed |
|---|---|---|
| Pre-2026-05-27 | Assumed Yahoo Shopping was dead/inactive | Yahoo PLAs were active; source was just not implemented yet |

## Open Questions

- How often should Yahoo PLAs be re-scraped for freshness? Prices change frequently for commodity products.
- Is there a way to detect when Yahoo has served a CAPTCHA page vs. real results?
