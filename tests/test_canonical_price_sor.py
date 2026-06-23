"""
SoR consolidation: canonical price must always come from the system of record
(donut-equipment.com), regardless of which store was scraped most recently.
Products with no SoR source fall back to the latest-scraped real price.
"""
from datetime import datetime, timedelta


def _setup_db(tmp_path, monkeypatch):
    import backend.config as cfg_mod
    import backend.database.db as db_mod
    monkeypatch.setattr(cfg_mod.config, "db_path", lambda: tmp_path / "t.db")
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod.init_db()
    return db_mod


def test_canonical_pinned_to_sor_even_when_secondary_scraped_later(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    from backend.database.db import session_scope
    from backend.database.models import Product, ProductSource
    from backend.dedup.engine import recompute_product_prices

    t0 = datetime(2026, 6, 1)
    with session_scope() as db:
        p = Product(canonical_title="Wall Case", sku="BK-WALL58", is_active=True)
        db.add(p)
        db.flush()
        # SoR source scraped EARLIER, secondary scraped LATER + cheaper.
        db.add(ProductSource(product_id=p.id, source_site="donut-equipment.com",
                             source_url="https://donut-equipment.com/products/x?variant=1",
                             source_price=5882.13, scraped_at=t0, is_active=True))
        db.add(ProductSource(product_id=p.id, source_site="donut-supplies.com",
                             source_url="https://donut-supplies.com/products/x?variant=2",
                             source_price=4868.93, scraped_at=t0 + timedelta(days=5), is_active=True))
        db.flush()
        recompute_product_prices(db, p)
        assert p.price_canonical == 5882.13          # SoR, not the later/cheaper one
        assert p.price_min == 4868.93                 # range still spans both
        assert p.price_max == 5882.13


def test_canonical_falls_back_to_latest_when_no_sor_source(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    from backend.database.db import session_scope
    from backend.database.models import Product, ProductSource
    from backend.dedup.engine import recompute_product_prices

    t0 = datetime(2026, 6, 1)
    with session_scope() as db:
        p = Product(canonical_title="Scoop", sku="AS-38", is_active=True)
        db.add(p)
        db.flush()
        db.add(ProductSource(product_id=p.id, source_site="bakerywholesalers.com",
                             source_url="https://bakerywholesalers.com/products/y?variant=1",
                             source_price=20.0, scraped_at=t0, is_active=True))
        db.add(ProductSource(product_id=p.id, source_site="donut-supplies.com",
                             source_url="https://donut-supplies.com/products/y?variant=2",
                             source_price=18.0, scraped_at=t0 + timedelta(days=3), is_active=True))
        db.flush()
        recompute_product_prices(db, p)
        assert p.price_canonical == 18.0             # latest-scraped, no SoR present
