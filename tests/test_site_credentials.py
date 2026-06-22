"""
Tests for source-site credential resolution.

Two ways a site can authenticate to Shopify:
  1. client_id + client_secret  -> client_credentials token exchange (Plus-org /
     installed Partner apps). Fails for stores the app can't be installed on.
  2. A pre-issued Admin API access token (shpat_… / atkn_…) from an in-admin
     custom app. Store-local, can't be refused by Shopify, never expires.

`_static_token` implements path 2's precedence: if a store_url + access_token are
configured, use them verbatim and skip the exchange entirely.
"""
from backend.api.routes import _static_token


def test_static_token_returned_when_present():
    site = {
        "shopify_store_url": "https://equipmentplus.myshopify.com",
        "shopify_access_token": "shpat_abc123",
    }
    assert _static_token(site) == ("https://equipmentplus.myshopify.com", "shpat_abc123")


def test_static_token_none_without_token():
    # client_id/secret only -> must fall through to the exchange path.
    site = {
        "shopify_store_url": "https://equipmentplus.myshopify.com",
        "shopify_client_id": "id",
        "shopify_client_secret": "secret",
    }
    assert _static_token(site) is None


def test_static_token_none_without_store_url():
    assert _static_token({"shopify_access_token": "shpat_abc123"}) is None


def test_static_token_ignores_whitespace_only():
    site = {"shopify_store_url": "  ", "shopify_access_token": "  "}
    assert _static_token(site) is None


def test_static_token_strips_surrounding_whitespace():
    site = {
        "shopify_store_url": "  https://x.myshopify.com  ",
        "shopify_access_token": "  shpat_x  ",
    }
    assert _static_token(site) == ("https://x.myshopify.com", "shpat_x")
