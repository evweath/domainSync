"""
SoR consolidation Stage 3 cleanup — migrate competitor matches off orphaned
pre-regen products onto the new per-variant products, then retire the orphans.

After the variant regen, each old (cross-store merged) Product was superseded by
fresh per-variant Products. Competitor matches still point at the old IDs. SKU is
the stable cross-store key (handles differ per store; SKUs don't), so we re-point
each match by SKU to the new product — preferring the system-of-record store
(donut-equipment.com), falling back to any store that carries the SKU.

Dry-run by default. Pass --apply to write.

    .venv/bin/python scripts/migrate_competitor_matches.py          # dry run
    .venv/bin/python scripts/migrate_competitor_matches.py --apply  # commit
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from backend.database.db import init_db, session_scope

SOR_SITE = "donut-equipment.com"


def _orphan_ids(db):
    return {r[0] for r in db.execute(text("""
        SELECT p.id FROM products p
        WHERE p.is_active=1 AND NOT EXISTS (
            SELECT 1 FROM product_sources s
            WHERE s.product_id=p.id AND s.source_status!='archived')
    """)).fetchall()}


def _new_product_by_sku(db):
    """sku -> new active product id. Prefer a product with an active SoR source."""
    de, any_ = {}, {}
    rows = db.execute(text("""
        SELECT p.id, p.sku,
               MAX(CASE WHEN s.source_site=:sor THEN 1 ELSE 0 END) AS is_sor
        FROM products p
        JOIN product_sources s ON s.product_id=p.id AND s.source_status!='archived'
        WHERE p.is_active=1 AND p.sku IS NOT NULL AND p.sku!=''
        GROUP BY p.id, p.sku
    """), {"sor": SOR_SITE}).fetchall()
    for pid, sku, is_sor in rows:
        any_.setdefault(sku, pid)
        if is_sor:
            de.setdefault(sku, pid)
    return de, any_


def main(apply: bool):
    init_db()
    with session_scope() as db:
        orphans = _orphan_ids(db)
        de_by_sku, any_by_sku = _new_product_by_sku(db)

        # Old product id -> its SKU (Product.sku, fallback to a source sku).
        # Effective SKU = Product.sku, falling back to any non-empty source_sku
        # on the orphan (some old products never got Product.sku populated).
        matches = db.execute(text("""
            SELECT m.id, m.master_product_id,
                   COALESCE(NULLIF(p.sku, ''), (
                       SELECT s.source_sku FROM product_sources s
                       WHERE s.product_id=p.id AND s.source_sku IS NOT NULL AND s.source_sku!=''
                       LIMIT 1
                   )) AS eff_sku
            FROM competitor_product_matches m
            JOIN products p ON p.id=m.master_product_id
            WHERE m.is_active=1
        """)).fetchall()

        mig_de = mig_any = unmapped_nosku = unmapped_nohit = not_orphan = 0
        plan = []  # (match_id, new_pid)
        for mid, master_id, sku in matches:
            if master_id not in orphans:
                not_orphan += 1
                continue
            if not sku:
                unmapped_nosku += 1
                continue
            target = de_by_sku.get(sku)
            if target:
                mig_de += 1
            else:
                target = any_by_sku.get(sku)
                if target:
                    mig_any += 1
            if not target:
                unmapped_nohit += 1
                continue
            if target != master_id:
                plan.append((mid, target))

        print(f"active competitor matches           : {len(matches)}")
        print(f"  on non-orphan products (untouched): {not_orphan}")
        print(f"  re-point via SoR sku match        : {mig_de}")
        print(f"  re-point via any-store sku match  : {mig_any}")
        print(f"  unmapped (orphan sku is null)     : {unmapped_nosku}")
        print(f"  unmapped (sku not in new catalog) : {unmapped_nohit}")
        print(f"  total re-point operations         : {len(plan)}")
        print(f"orphans to retire (is_active=0)     : {len(orphans)}")

        if not apply:
            print("\nDRY RUN — no changes written. Re-run with --apply to commit.")
            return

        for mid, new_pid in plan:
            db.execute(
                text("UPDATE competitor_product_matches SET master_product_id=:p WHERE id=:m"),
                {"p": new_pid, "m": mid},
            )
        retired = db.execute(text("""
            UPDATE products SET is_active=0
            WHERE id IN (
                SELECT p.id FROM products p
                WHERE p.is_active=1 AND NOT EXISTS (
                    SELECT 1 FROM product_sources s
                    WHERE s.product_id=p.id AND s.source_status!='archived')
            )
        """)).rowcount
        print(f"\nAPPLIED: re-pointed {len(plan)} matches, retired {retired} orphan products.")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
