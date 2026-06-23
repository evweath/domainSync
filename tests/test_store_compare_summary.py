"""
Stage 5 (SoR consolidation): Store Compare per-store gap summary.

For each store: present / missing / only_here counts over the merged catalog.
`missing_from_sor` = catalog products with no active donut-equipment.com source.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import backend.config as cfg_mod
    import backend.database.db as db_mod

    monkeypatch.setattr(cfg_mod.config, "db_path", lambda: tmp_path / "t.db")
    # Two enabled stores: the SoR and one secondary.
    monkeypatch.setattr(cfg_mod.config, "get", _patched_get(cfg_mod.config))
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod.init_db()

    from backend.database.db import session_scope
    from backend.database.models import Product, ProductSource

    def src(pid, site, price, url):
        return ProductSource(product_id=pid, source_site=site, source_url=url,
                             source_price=price, source_status="active", is_active=True)

    with session_scope() as db:
        # P1: in both stores. P2: SoR only. P3: secondary only (missing from SoR).
        for title, sku in [("P1", "S1"), ("P2", "S2"), ("P3", "S3")]:
            db.add(Product(canonical_title=title, sku=sku, is_active=True))
        db.flush()
        db.add(src(1, "donut-equipment.com", 10, "https://donut-equipment.com/p/1?variant=1"))
        db.add(src(1, "donut-supplies.com", 11, "https://donut-supplies.com/p/1?variant=1"))
        db.add(src(2, "donut-equipment.com", 20, "https://donut-equipment.com/p/2?variant=1"))
        db.add(src(3, "donut-supplies.com", 30, "https://donut-supplies.com/p/3?variant=1"))

    from backend.api.routes import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _patched_get(cfg):
    orig = cfg.get

    def get(*keys, default=None):
        if keys == ("source_sites",):
            return [
                {"domain": "donut-equipment.com", "enabled": True},
                {"domain": "donut-supplies.com", "enabled": True},
            ]
        return orig(*keys, default=default)

    return get


def test_summary_counts(client):
    r = client.get("/api/products/store-comparison/summary")
    assert r.status_code == 200
    data = r.json()
    assert data["total_products"] == 3
    assert data["sor_site"] == "donut-equipment.com"
    # P3 is on a secondary store only → missing from SoR.
    assert data["missing_from_sor"] == 1

    by_site = {s["site"]: s for s in data["stores"]}
    sor = by_site["donut-equipment.com"]
    assert sor["present"] == 2 and sor["missing"] == 1 and sor["only_here"] == 1  # P2 SoR-exclusive
    sec = by_site["donut-supplies.com"]
    assert sec["present"] == 2 and sec["missing"] == 1 and sec["only_here"] == 1  # P3 secondary-exclusive
