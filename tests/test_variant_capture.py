"""
Stage 1 (SoR variant consolidation): the Shopify scraper must capture EVERY
variant as its own first-class ScrapedProduct, not just variants[0].

Each emitted product must carry:
- its own SKU / price / availability,
- a distinct source_url (…/products/<handle>?variant=<id>) so the
  (source_site, source_url) uniqueness constraint holds per variant,
- a parent reference (parent_handle + shopify_product_id) so variants can be
  regrouped into a product-with-variants for Shopify sync/display,
- a display title that distinguishes non-default variants.
"""
import pytest

from backend.scrapers.shopify_scraper import _expand_variants


_ITEM = {
    "id": 987654321,
    "handle": "fryer-3000",
    "title": "Donut Fryer 3000",
    "vendor": "AcmeFry",
    "product_type": "Fryers",
    "body_html": "<p>A great fryer.</p>",
    "images": [{"src": "https://cdn.example.com/fryer.jpg"}],
    "options": [{"name": "Capacity", "position": 1, "values": ["12L", "24L"]}],
    "variants": [
        {"id": 111, "title": "12L", "sku": "FRY-12", "price": "1999.00",
         "available": True, "option1": "12L"},
        {"id": 222, "title": "24L", "sku": "FRY-24", "price": "2499.00",
         "available": False, "option1": "24L"},
    ],
}


def test_expands_every_variant():
    products = _expand_variants(_ITEM, "https://store.example.com", "donut-equipment.com")
    assert len(products) == 2


def test_each_variant_has_distinct_url_with_variant_id():
    products = _expand_variants(_ITEM, "https://store.example.com", "donut-equipment.com")
    urls = {p.url for p in products}
    assert urls == {
        "https://store.example.com/products/fryer-3000?variant=111",
        "https://store.example.com/products/fryer-3000?variant=222",
    }


def test_variant_owns_its_sku_and_price():
    products = _expand_variants(_ITEM, "https://store.example.com", "donut-equipment.com")
    by_sku = {p.sku: p for p in products}
    assert by_sku["FRY-12"].price == 1999.00
    assert by_sku["FRY-24"].price == 2499.00
    assert by_sku["FRY-24"].in_stock is False


def test_parent_reference_carried_on_every_variant():
    products = _expand_variants(_ITEM, "https://store.example.com", "donut-equipment.com")
    for p in products:
        assert p.parent_handle == "fryer-3000"
        assert p.shopify_product_id == "987654321"


def test_non_default_variant_title_distinguishes_display_title():
    products = _expand_variants(_ITEM, "https://store.example.com", "donut-equipment.com")
    titles = {p.title for p in products}
    assert titles == {"Donut Fryer 3000 - 12L", "Donut Fryer 3000 - 24L"}


def test_single_default_variant_keeps_plain_title_and_base_url_gets_variant_id():
    item = {
        "id": 42,
        "handle": "solo",
        "title": "Solo Mixer",
        "variants": [{"id": 9, "title": "Default Title", "sku": "SOLO", "price": "10.0",
                      "available": True}],
    }
    products = _expand_variants(item, "https://s.example.com", "donut-equipment.com")
    assert len(products) == 1
    assert products[0].title == "Solo Mixer"
    assert products[0].url == "https://s.example.com/products/solo?variant=9"
    assert products[0].parent_handle == "solo"


def test_persist_stores_parent_reference_on_product(tmp_path, monkeypatch):
    """Stage 2: each variant persists as its own Product carrying the parent ref."""
    import backend.config as cfg_mod
    import backend.database.db as db_mod

    monkeypatch.setattr(cfg_mod.config, "db_path", lambda: tmp_path / "t.db")
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod.init_db()

    from backend.database.db import session_scope
    from backend.database.models import Product, ProductSource
    from backend.scrapers.source_scraper import SourceScraper

    scraper = SourceScraper(session_id=None)
    variants = _expand_variants(_ITEM, "https://store.example.com", "donut-equipment.com")
    for sp in variants:
        assert scraper._persist_product(sp, "donut-equipment.com") == "new"

    with session_scope() as db:
        products = db.query(Product).order_by(Product.id).all()
        assert len(products) == 2
        for p in products:
            assert p.parent_handle == "fryer-3000"
            assert p.shopify_product_id == "987654321"
        # Distinct per-variant source rows under the uniqueness constraint.
        urls = {s.source_url for s in db.query(ProductSource).all()}
        assert any("variant=111" in u for u in urls)
        assert any("variant=222" in u for u in urls)
