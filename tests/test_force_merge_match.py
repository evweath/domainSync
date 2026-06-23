"""
Stage 4 (SoR consolidation): cross-store auto-merge matching precedence.

SKU is the stable cross-store key, so it must win over model/title. Title-fuzzy
is the weakest signal and is restricted to titles UNIQUE among SoR products — a
title shared by several variants can't disambiguate which variant to merge into.
"""
from backend.dedup.force_merge import _best_primary_match

# SoR (primary) indexes: SKU 'FRY-12' → product 10, model 'M-99' → product 20.
SKU_INDEX = {"fry-12": 10, "m-only": 30}
MODEL_INDEX = {"m-99": 20, "m-only-model": 30}
# Only product 40 has a unique title; 50/51 share "Shared Variant Title".
UNIQUE_TITLES = [(40, "Distinct Commercial Glaze Warmer")]


def _match(sku=None, model=None, title=None, threshold=80.0):
    return _best_primary_match(sku, model, title, SKU_INDEX, MODEL_INDEX,
                               UNIQUE_TITLES, threshold)


def test_sku_wins_over_model_and_title():
    # Even with a conflicting model + title, SKU decides.
    r = _match(sku="FRY-12", model="M-99", title="Distinct Commercial Glaze Warmer")
    assert r["status"] == "matched"
    assert r["product_id"] == 10
    assert r["confidence"] == 98.0
    assert r["reason"].startswith("sku")


def test_sku_match_is_case_and_space_insensitive():
    assert _match(sku="  fry-12 ")["product_id"] == 10


def test_model_used_when_sku_absent():
    r = _match(model="M-99")
    assert r["product_id"] == 20
    assert r["reason"].startswith("model_number")


def test_title_fuzzy_matches_unique_title_above_threshold():
    r = _match(title="Distinct Commercial Glaze Warmer")
    assert r["status"] == "matched"
    assert r["product_id"] == 40
    assert r["reason"].startswith("title_fuzzy")


def test_title_below_threshold_is_uncertain_not_merged():
    # ~60% overlap → uncertain band (>=50, <80), no merge.
    r = _match(title="Distinct Commercial Warmer Unit XL Deluxe Model")
    assert r["status"] in ("uncertain", "exception")
    assert r["product_id"] is None


def test_unmatched_sku_is_exception_not_forced_into_a_sibling():
    # A genuinely SoR-missing product (SKU not in index, no model, no unique
    # title hit) must NOT merge — Stage 5 needs it surfaced as missing.
    r = _match(sku="DS-ONLY-123", title="totally unrelated widget xyz")
    assert r["status"] == "exception"
    assert r["product_id"] is None
