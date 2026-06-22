"""
Tests for Shopify scope-error detection.

A valid client_credentials token can read /shop.json with no special scope,
so the Settings connection test ("✓ Connected") passes even when the app was
never granted read_products. The first time anything reads /products.json
(Scan Now), Shopify returns:

    403 {"errors":"[API] This action requires merchant approval for read_products scope."}

`missing_scope` extracts the scope name from that body so callers can render an
actionable message instead of the raw JSON.
"""
from backend.shopify.client import ShopifyError, missing_scope

_SCOPE_403 = '{"errors":"[API] This action requires merchant approval for read_products scope."}'


def test_missing_scope_extracts_scope_name():
    assert missing_scope(403, _SCOPE_403) == "read_products"


def test_missing_scope_handles_write_scope():
    body = '{"errors":"[API] This action requires merchant approval for write_products scope."}'
    assert missing_scope(403, body) == "write_products"


def test_missing_scope_none_when_not_403():
    # Same wording but a non-403 status is not a scope-approval problem.
    assert missing_scope(401, _SCOPE_403) is None


def test_missing_scope_none_for_unrelated_403():
    assert missing_scope(403, '{"errors":"Not Found"}') is None


def test_missing_scope_none_for_empty_body():
    assert missing_scope(403, "") is None
    assert missing_scope(403, None) is None


def test_shopify_error_exposes_missing_scope():
    err = ShopifyError(403, _SCOPE_403)
    assert err.missing_scope == "read_products"


def test_shopify_error_missing_scope_none_for_other_errors():
    assert ShopifyError(429, "Rate limited").missing_scope is None
