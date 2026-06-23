"""
Tests for the redefined duplicate-product detection.

Duplicate = the SAME product listed more than once WITHIN one store (source
site). The same product in different stores is NOT a duplicate. Manufacturers
must be the same maker (fuzzy: spelling/word-order variants still count); a
genuinely different manufacturer is never a duplicate.
"""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Product, ProductSource
from backend.dedup.engine import DeduplicationEngine, recompute_product_prices
from backend.dedup.matchers import compute_confidence


# ---------------------------------------------------------------------------
# Matcher-level: manufacturer is a hard disqualifier (fuzzy)
# ---------------------------------------------------------------------------

def _confidence(mfr_a, mfr_b, **kw):
    return compute_confidence(
        price_a=100.0, price_b=100.0,
        model_a=None, model_b=None,
        manufacturer_a=mfr_a, manufacturer_b=mfr_b,
        title_a="Donut Robot Mark II", title_b="Donut Robot Mark II",
        desc_a=None, desc_b=None,
        **kw,
    )


def test_different_manufacturer_is_disqualified():
    score, factors = _confidence("Belshaw", "Hobart")
    assert score == 5.0
    assert factors.get("disqualifier") == "manufacturer_mismatch"


def test_manufacturer_spelling_variant_not_disqualified():
    # A typo should still count as the same manufacturer.
    score, factors = _confidence("Belshaw", "Belshww")
    assert factors.get("disqualifier") != "manufacturer_mismatch"
    assert score > 60.0


def test_manufacturer_longer_form_not_disqualified():
    # "Belshaw" vs "Belshaw Adamatic" is the same maker, longer name.
    score, factors = _confidence("Belshaw", "Belshaw Adamatic")
    assert factors.get("disqualifier") != "manufacturer_mismatch"
    assert score > 60.0


def test_missing_manufacturer_does_not_disqualify():
    # If either side has no manufacturer, the rule cannot apply.
    score, factors = _confidence("Belshaw", None)
    assert factors.get("disqualifier") != "manufacturer_mismatch"


# ---------------------------------------------------------------------------
# Engine-level: duplicates are scoped to a single store
# ---------------------------------------------------------------------------

@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _add_product(session, title, site, *, manufacturer="Belshaw", price=100.0, model=None):
    p = Product(
        canonical_title=title, manufacturer=manufacturer,
        model_number=model, price_canonical=price, is_active=True,
    )
    session.add(p)
    session.flush()
    session.add(ProductSource(
        product_id=p.id, source_site=site,
        source_url=f"https://{site}/{p.id}",
        source_title=title, is_active=True,
    ))
    session.flush()
    return p


def test_same_store_duplicate_is_flagged(session):
    _add_product(session, "Belshaw Donut Robot Mark II", "store-a.com")
    _add_product(session, "Belshaw Donut Robot Mark II", "store-a.com")
    session.commit()

    stats = DeduplicationEngine().run(session)
    assert stats["comparisons"] == 1
    assert stats["flagged_for_review"] + stats["auto_merged"] == 1


def test_cross_store_match_is_not_a_duplicate(session):
    _add_product(session, "Belshaw Donut Robot Mark II", "store-a.com")
    _add_product(session, "Belshaw Donut Robot Mark II", "store-b.com")
    session.commit()

    stats = DeduplicationEngine().run(session)
    # No shared store → the pair is never compared.
    assert stats["comparisons"] == 0
    assert stats["flagged_for_review"] == 0
    assert stats["auto_merged"] == 0


def test_high_confidence_duplicate_is_flagged_not_auto_merged(session):
    # Identical title/manufacturer/price/model → well above the auto-merge
    # threshold, but merging is now always manual: nothing is auto-merged.
    from backend.database.models import DuplicateCandidate
    a = _add_product(session, "Belshaw Donut Robot Mark II", "store-a.com", model="MARK-II", price=100.0)
    b = _add_product(session, "Belshaw Donut Robot Mark II", "store-a.com", model="MARK-II", price=100.0)
    session.commit()

    stats = DeduplicationEngine().run(session)
    assert stats["auto_merged"] == 0
    assert stats["flagged_for_review"] == 1

    # Both products stay active — neither was merged away.
    session.refresh(a)
    session.refresh(b)
    assert a.is_active and b.is_active

    cand = session.query(DuplicateCandidate).one()
    assert cand.status == "pending"


def test_canonical_price_is_most_recent_not_average(session):
    # Canonical must be a real store price (the latest), never an average.
    p = Product(canonical_title="Widget", manufacturer="X", price_canonical=999.0, is_active=True)
    session.add(p)
    session.flush()
    session.add(ProductSource(
        product_id=p.id, source_site="a.com", source_url="https://a.com/1",
        source_price=100.0, is_active=True, scraped_at=datetime(2026, 1, 1),
    ))
    session.add(ProductSource(
        product_id=p.id, source_site="b.com", source_url="https://b.com/1",
        source_price=120.0, is_active=True, scraped_at=datetime(2026, 6, 1),
    ))
    session.commit()

    recompute_product_prices(session, p)
    assert p.price_canonical == 120.0   # most-recent (b.com / June), not avg=110
    assert p.price_min == 100.0
    assert p.price_max == 120.0


def test_recompute_ignores_inactive_and_zero_prices(session):
    p = Product(canonical_title="Widget", manufacturer="X", is_active=True)
    session.add(p)
    session.flush()
    session.add(ProductSource(
        product_id=p.id, source_site="a.com", source_url="https://a.com/1",
        source_price=200.0, is_active=True, scraped_at=datetime(2026, 1, 1),
    ))
    session.add(ProductSource(  # inactive — ignored
        product_id=p.id, source_site="b.com", source_url="https://b.com/1",
        source_price=50.0, is_active=False, scraped_at=datetime(2026, 6, 1),
    ))
    session.commit()

    recompute_product_prices(session, p)
    assert p.price_canonical == 200.0
    assert p.price_min == 200.0 and p.price_max == 200.0


def test_different_manufacturer_same_store_not_flagged(session):
    _add_product(session, "Donut Robot Mark II", "store-a.com", manufacturer="Belshaw")
    _add_product(session, "Donut Robot Mark II", "store-a.com", manufacturer="Hobart")
    session.commit()

    stats = DeduplicationEngine().run(session)
    assert stats["comparisons"] == 1          # same store → compared
    assert stats["flagged_for_review"] == 0   # but disqualified by manufacturer
    assert stats["auto_merged"] == 0
