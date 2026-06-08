"""
Tests for the shared product-page parsers in backend/search/core/parse.py.

These lock in the Phase-3 consolidation: the two competitor scan modules
(product_search, web_search_scan) must use the SAME _parse_jsonld / _parse_meta
so they can never drift again. Before consolidation, product_search extracted
image+description while web_search_scan did not. See
.claude/investigations/competitor-search.md.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.search.core.parse import (
    _domain,
    _extract_price,
    _extract_price_float,
    _parse_jsonld,
    _parse_meta,
)
import backend.competitor.product_search as ps
import backend.competitor.web_search_scan as wss


def test_scan_modules_share_the_same_parsers():
    """The two scan modules must reference the identical core parser objects.

    If this fails, someone reintroduced a local _parse_jsonld/_parse_meta in one
    module — the exact drift that hid image/description from the web-search scan.
    """
    assert ps._parse_jsonld is wss._parse_jsonld is _parse_jsonld
    assert ps._parse_meta is wss._parse_meta is _parse_meta


def test_parse_jsonld_extracts_image_and_description():
    """Regression: the unified parser yields image + description (the keys the
    web-search scan path used to silently drop)."""
    html = (
        '<script type="application/ld+json">'
        '{"@type":"Product","name":"Belshaw Donut Robot","model":"MARK II",'
        '"image":"https://x.com/a.jpg","description":"A commercial fryer",'
        '"offers":{"price":"4999.00","availability":"InStock"}}'
        '</script>'
    )
    d = _parse_jsonld(html)
    assert d is not None
    assert d['title'] == 'Belshaw Donut Robot'
    assert d['model_number'] == 'MARK II'
    assert d['price'] == 4999.00          # JSON-LD price parsed to float
    assert d['image'] == 'https://x.com/a.jpg'
    assert d['description'] == 'A commercial fryer'
    assert d['in_stock'] is True


def test_parse_meta_extracts_image_and_description():
    """The OG/meta fallback also yields image + description."""
    html = (
        '<meta property="og:title" content="Donut Fryer">'
        '<meta property="og:image" content="https://x.com/f.jpg">'
        '<meta property="og:description" content="Fries donuts">'
        '<meta property="product:price:amount" content="1299.99">'
    )
    d = _parse_meta(html)
    assert d['title'] == 'Donut Fryer'
    assert d['image'] == 'https://x.com/f.jpg'
    assert d['description'] == 'Fries donuts'
    assert d['price'] == 1299.99


def test_domain_strips_only_literal_www_prefix():
    """Regression: _domain used lstrip('www.'), which strips any leading w/. chars
    and mangled major competitor hosts (walmart -> almart, webstaurantstore ->
    ebstaurantstore, wayfair -> ayfair). Must strip only the literal 'www.' prefix."""
    assert _domain('https://www.walmart.com/ip/123') == 'walmart.com'
    assert _domain('https://www.webstaurantstore.com/p') == 'webstaurantstore.com'
    assert _domain('https://www.wayfair.com') == 'wayfair.com'
    # non-www hosts and subdomains are untouched
    assert _domain('https://restaurantsupply.com/a') == 'restaurantsupply.com'
    assert _domain('https://shop.example.com/x') == 'shop.example.com'
    assert _domain('https://WWW.Burkett.com/Z') == 'burkett.com'


def test_price_extractors_str_vs_float():
    """_extract_price returns the display string ($-prefixed); _extract_price_float
    returns a number. Same regex, different contract — must not be merged."""
    assert _extract_price('was $1,299.99 today') == '$1,299.99'
    assert _extract_price_float('was $1,299.99 today') == 1299.99
    assert _extract_price('no price here') is None
    assert _extract_price_float('no price here') is None
