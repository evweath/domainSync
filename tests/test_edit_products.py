"""Edit Products page: snapshot/DB projection + search/filter/sort/facets.

Every product becomes one row PER VARIANT. The snapshot path (raw Shopify
objects) is the rich, preferred source; the DB path is a best-effort fallback
for stores without a recent scan.
"""
import pytest

from backend.shopify import edit_products as ep


# ---------------------------------------------------------------------------
# Snapshot projection (pure function, no I/O)
# ---------------------------------------------------------------------------
def _snapshot():
    return {
        "shop": {"name": "Test Shop"},
        "collections": {
            "100": {"id": 100, "title": "All Equipment"},
            "200": {"id": 200, "title": "Fillers"},
        },
        "product_collections": {"9001": [100, 200]},
        "products": {
            "widget-a": {
                "id": 9001,
                "handle": "widget-a",
                "title": "Widget A",
                "body_html": "<p>Great <b>widget</b>.</p>",
                "vendor": "Acme",
                "product_type": "Tools",
                "status": "active",
                "tags": "Free Shipping, Popular",
                "images": [{"src": "http://img/1.png"}, {"src": "http://img/2.png"}],
                "variants": [
                    {"id": 1, "title": "Small", "sku": "WA-S", "price": "10.00",
                     "compare_at_price": "12.00", "weight": "1.5", "weight_unit": "kg",
                     "barcode": "111", "inventory_quantity": 5, "option1": "Small"},
                    {"id": 2, "title": "Large", "sku": "WA-L", "price": "20.00",
                     "weight": "2.0", "option1": "Large"},
                ],
            },
            "widget-b": {
                "id": 9002,
                "handle": "widget-b",
                "title": "Widget B",
                "vendor": "Beta",
                "product_type": "Parts",
                "status": "draft",
                "tags": "",
                "images": [],
                "variants": [
                    {"id": 3, "title": "Default Title", "sku": "WB", "price": "5.50"},
                ],
            },
        },
    }


def test_project_snapshot_one_row_per_variant():
    rows = ep._project_snapshot("shop.example", _snapshot())
    # Widget A has 2 variants, Widget B has 1 → 3 rows total.
    assert len(rows) == 3

    a_small = next(r for r in rows if r["sku"] == "WA-S")
    assert a_small["store"] == "shop.example"
    assert a_small["data_source"] == "scan"
    assert a_small["title"] == "Widget A"
    assert a_small["vendor"] == "Acme"
    assert a_small["price"] == 10.0            # coerced from string
    assert a_small["compare_at_price"] == 12.0
    assert a_small["weight"] == 1.5
    assert a_small["image_count"] == 2
    assert a_small["primary_image"] == "http://img/1.png"
    assert a_small["tags"] == ["Free Shipping", "Popular"]
    assert set(a_small["collections"]) == {"All Equipment", "Fillers"}
    assert a_small["description"] == "Great widget ."  # HTML stripped
    assert a_small["variant_title"] == "Small"
    assert a_small["url"] == "https://shop.example/products/widget-a"
    # Every row carries every declared column.
    for col in ep.COLUMNS:
        assert col in a_small


def test_project_snapshot_default_title_blanked_and_missing_prices():
    rows = ep._project_snapshot("shop.example", _snapshot())
    b = next(r for r in rows if r["sku"] == "WB")
    assert b["variant_title"] == ""            # "Default Title" → blank
    assert b["compare_at_price"] is None       # absent price stays None, not 0
    assert b["tags"] == []
    assert b["collections"] == []
    assert b["status"] == "draft"


# ---------------------------------------------------------------------------
# query(): search / filters / sort / facets / pagination
# ---------------------------------------------------------------------------
@pytest.fixture
def synthetic_query(monkeypatch):
    rows = ep._project_snapshot("shop.example", _snapshot())
    monkeypatch.setattr(ep, "_store_rows", lambda db, st: (rows, "scan"))
    return rows


def test_query_search_matches_across_attributes(synthetic_query):
    # "popular" only appears in Widget A's tags → both its variants match.
    r = ep.query(None, stores=["shop.example"], search="popular")
    assert r["total"] == 2
    assert all(row["title"] == "Widget A" for row in r["rows"])


def test_query_price_filter_and_sort(synthetic_query):
    r = ep.query(None, stores=["shop.example"], filters={"min_price": 10},
                 sort_by="price", sort_order="desc")
    prices = [row["price"] for row in r["rows"]]
    assert prices == [20.0, 10.0]              # 5.50 excluded, sorted desc


def test_query_vendor_and_status_exact_filters(synthetic_query):
    assert ep.query(None, stores=["shop.example"], filters={"vendor": "Acme"})["total"] == 2
    assert ep.query(None, stores=["shop.example"], filters={"status": "draft"})["total"] == 1


def test_query_has_image_filter(synthetic_query):
    assert ep.query(None, stores=["shop.example"], filters={"has_image": True})["total"] == 2
    assert ep.query(None, stores=["shop.example"], filters={"has_image": False})["total"] == 1


def test_query_collection_filter(synthetic_query):
    assert ep.query(None, stores=["shop.example"], filters={"collection": "fillers"})["total"] == 2
    assert ep.query(None, stores=["shop.example"], filters={"collection": "nope"})["total"] == 0


def test_query_facets_and_pagination(synthetic_query):
    r = ep.query(None, stores=["shop.example"], per_page=2, page=1)
    assert r["total"] == 3
    assert r["pages"] == 2
    assert len(r["rows"]) == 2
    assert set(r["facets"]["vendors"]) == {"Acme", "Beta"}
    assert set(r["facets"]["statuses"]) == {"active", "draft"}
    assert "Fillers" in r["facets"]["collections"]
    # Page 2 has the remaining row.
    assert len(ep.query(None, stores=["shop.example"], per_page=2, page=2)["rows"]) == 1


# ---------------------------------------------------------------------------
# DB fallback projection (temp database)
# ---------------------------------------------------------------------------
@pytest.fixture
def db_session(tmp_path, monkeypatch):
    import backend.config as cfg_mod
    import backend.database.db as db_mod

    monkeypatch.setattr(cfg_mod.config, "db_path", lambda: tmp_path / "t.db")
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod.init_db()

    from backend.database.db import session_scope
    from backend.database.models import Product, ProductSource, ProductOption, ProductTag

    with session_scope() as db:
        db.add(Product(canonical_title="Canon Widget", manufacturer="Acme",
                       category="Tools", weight=3.0, is_active=True))
        db.flush()
        db.add(ProductSource(product_id=1, source_site="db-store.com",
                             source_url="https://db-store.com/p/1",
                             source_title="Widget on Store", source_price=42.0,
                             source_sku="DBW", source_status="active", is_active=True))
        db.add(ProductTag(product_id=1, tag="clearance"))
        db.add(ProductOption(product_id=1, option_group="Size",
                             option_value="XL", price_modifier=5.0, sku_suffix="-XL",
                             source_site="db-store.com"))

    with session_scope() as db:
        yield db


def test_project_db_fallback(db_session):
    rows = ep._project_db(db_session, "db-store.com")
    assert len(rows) == 1                       # one option → one variant row
    row = rows[0]
    assert row["data_source"] == "db"
    assert row["title"] == "Widget on Store"
    assert row["vendor"] == "Acme"
    assert row["product_type"] == "Tools"
    assert row["sku"] == "DBW-XL"               # base sku + suffix
    assert row["price"] == 47.0                 # 42 + 5 modifier
    assert row["tags"] == ["clearance"]
    assert row["weight"] == 3.0                 # from canonical Product
    assert row["variant_title"] == "Size / XL"
    for col in ep.COLUMNS:
        assert col in row


def test_project_db_no_options_single_row(db_session):
    from backend.database.db import session_scope
    from backend.database.models import ProductSource
    with session_scope() as db:
        db.add(ProductSource(product_id=1, source_site="plain.com",
                             source_url="https://plain.com/p/1",
                             source_title="Plain", source_price=9.0,
                             source_sku="PL", source_status="active", is_active=True))
    rows = ep._project_db(db_session, "plain.com")
    assert len(rows) == 1
    assert rows[0]["price"] == 9.0
    assert rows[0]["variant_title"] == ""


# ---------------------------------------------------------------------------
# Write-back: staged edits → executor transactions (Phase 4)
# ---------------------------------------------------------------------------
def _changes():
    return [
        {"store": "s.com", "data_source": "scan", "product_id": "111", "variant_id": "42",
         "field": "price", "scope": "variant", "old": 10.0, "new": 12.5},
        {"store": "s.com", "data_source": "scan", "product_id": "111", "variant_id": "42",
         "field": "status", "scope": "product", "old": "active", "new": "draft"},
        {"store": "s.com", "data_source": "scan", "product_id": "111", "variant_id": "42",
         "field": "tags", "scope": "product", "old": ["a", "b"], "new": ["b", "c"]},
        {"store": "db.com", "data_source": "db", "product_id": "9", "variant_id": "9",
         "field": "price", "scope": "variant", "old": 1, "new": 2},
    ]


def test_build_edit_transactions_maps_fields_and_risk():
    items = {it["field"]: it for it in ep.build_edit_transactions(_changes()[:3])}

    price = items["price"]
    assert price["risk"] == "MEDIUM" and price["pushable"]
    assert price["txn"]["resource_type"] == "variant_field"
    assert price["txn"]["product_id"] == 111 and price["txn"]["meta"]["variant_id"] == 42
    assert price["txn"]["meta"]["field_key"] == "price"

    status = items["status"]
    assert status["risk"] == "HIGH"
    assert status["txn"]["resource_type"] == "product_field"
    assert status["txn"]["meta"]["field_key"] == "status"

    tags = items["tags"]
    assert tags["risk"] == "LOW"
    assert tags["txn"]["resource_type"] == "tags"
    assert tags["txn"]["meta"]["tags_to_add"] == ["c"]
    assert tags["txn"]["meta"]["tags_to_remove"] == ["a"]


def test_build_edit_transactions_blocks_db_rows():
    item = ep.build_edit_transactions([_changes()[3]])[0]
    assert item["pushable"] is False
    assert item["txn"] is None
    assert "scan" in item["reason"].lower()


def test_build_edit_transactions_collections_add_remove():
    ch = {"store": "s.com", "data_source": "scan", "product_id": "111", "variant_id": "42",
          "field": "collections", "scope": "product", "old": ["A", "B"], "new": ["B", "C", "D"]}
    item = ep.build_edit_transactions([ch])[0]
    assert item["pushable"] is True
    assert item["txn"]["resource_type"] == "collections"
    assert item["txn"]["product_id"] == 111
    assert item["txn"]["meta"]["add"] == ["C", "D"]
    assert item["txn"]["meta"]["remove"] == ["A"]


def test_build_edit_transactions_category_not_pushed():
    ch = {"store": "s.com", "data_source": "scan", "product_id": "111", "variant_id": "42",
          "field": "category", "scope": "product", "old": "", "new": "Fryers"}
    item = ep.build_edit_transactions([ch])[0]
    assert item["pushable"] is False       # Shopify taxonomy Category not writable here
    assert item["txn"] is None
    assert "category" in item["reason"].lower()


# ---------------------------------------------------------------------------
# Category taxonomy: must stay a curated, verified subset of Shopify's real
# taxonomy (see backend/shopify/category_taxonomy.py) — no invented names/gids.
# ---------------------------------------------------------------------------
def test_category_taxonomy_gids_are_well_formed_and_unique():
    from backend.shopify.category_taxonomy import CATEGORY_TAXONOMY

    seen_gids = set()
    seen_names = set()
    for grp in CATEGORY_TAXONOMY:
        for gid in (grp["gid"], *[o["gid"] for o in grp["options"]]):
            assert gid.startswith("gid://shopify/TaxonomyCategory/")
            assert gid not in seen_gids, f"duplicate gid: {gid}"
            seen_gids.add(gid)
        # Leaf option names must be unique across the whole tree (frontend
        # <select> stores just the name, not the gid) and each option's path
        # must actually end with its own name and start with the group's path.
        for opt in grp["options"]:
            assert opt["name"] not in seen_names, f"duplicate category name: {opt['name']}"
            seen_names.add(opt["name"])
            assert opt["path"].startswith(grp["path"] + " > ")
            assert opt["path"].endswith(opt["name"])


def test_category_options_flattens_groups_and_leaves():
    from backend.shopify.category_taxonomy import CATEGORY_TAXONOMY, category_options

    flat = category_options()
    total_leaves = sum(len(g["options"]) for g in CATEGORY_TAXONOMY)
    # One entry per group header (itself selectable) + one per leaf option.
    assert len(flat) == len(CATEGORY_TAXONOMY) + total_leaves
    assert flat[0] == {"name": "Kitchen Appliances",
                        "gid": "gid://shopify/TaxonomyCategory/hg-11-7",
                        "path": "Home & Garden > Kitchen & Dining > Kitchen Appliances",
                        "group": "Kitchen Appliances"}


def test_taxonomy_pools_exposes_curated_category_tree_not_db_values(db_session):
    from backend.database.db import session_scope
    from backend.database.models import Product

    # A junky, AI-guessed/free-text category value already in the DB — this
    # must NOT leak into the category picker; the picker is the fixed curated
    # tree, not "whatever's already in Product.category".
    with session_scope() as db:
        db.add(Product(canonical_title="Junk", category="Totally Made Up Category"))

    from backend.shopify.category_taxonomy import CATEGORY_TAXONOMY

    pools = ep.taxonomy_pools(db_session)
    assert pools["category_tree"] == CATEGORY_TAXONOMY
    all_names = {c["name"] for c in pools["categories"]}
    assert "Totally Made Up Category" not in all_names


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import backend.config as cfg_mod
    import backend.database.db as db_mod
    monkeypatch.setattr(cfg_mod.config, "db_path", lambda: tmp_path / "t.db")
    db_mod._engine = None
    db_mod._SessionLocal = None
    db_mod.init_db()
    from backend.api.routes import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_review_endpoint_counts(client):
    r = client.post("/api/edit-products/review", json={"changes": _changes()}).json()
    assert r["total"] == 4
    assert r["pushable"] == 3
    assert r["blocked"] == 1
    assert r["risk_counts"]["HIGH"] == 1
    # 'txn' must never leak to the browser payload.
    assert all("txn" not in it for it in r["items"])


def test_execute_backgrounds_groups_by_store_skips_db_and_maps_results(client, monkeypatch):
    import time
    import backend.api.routes as routes
    import backend.shopify.executor as executor_mod

    async def fake_creds(domain):
        return ("https://x.myshopify.com", "tok")

    async def fake_exec(store_url, token, txns, progress_cb=None):
        # Echo one ok and one error to prove result mapping by id.
        out = []
        for i, t in enumerate(txns):
            r = {"id": t["id"], "status": "ok" if i == 0 else "error",
                 "error": None if i == 0 else "boom"}
            if progress_cb:
                await progress_cb(r)
            out.append(r)
        return out

    monkeypatch.setattr(routes, "_get_site_credentials", fake_creds)
    monkeypatch.setattr(executor_mod, "execute_transactions", fake_exec)

    start = client.post("/api/edit-products/execute", json={"changes": _changes()}).json()
    assert start["status"] == "started"
    assert start["skipped"] == 1        # the db-sourced change recorded up front

    for _ in range(50):
        s = client.get("/api/edit-products/execute-status").json()
        if s["finished"]:
            break
        time.sleep(0.05)
    assert s["finished"]
    res = s["results"]
    assert len(res) == 4                 # every change accounted for by change_id
    assert sum(1 for v in res.values() if v["status"] == "ok") == 1
    assert sum(1 for v in res.values() if v["status"] == "error") == 2
    assert sum(1 for v in res.values() if v["status"] == "skipped") == 1
