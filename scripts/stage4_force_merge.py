"""SoR consolidation Stage 4 runner — cross-store auto-merge into the SoR.

Merges every secondary store's per-variant listings INTO the matching
donut-equipment.com product (SKU → model → title). Idempotent: already-merged
products are skipped. Safe to re-run.

    .venv/bin/python scripts/stage4_force_merge.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database.db import init_db
from backend.dedup.force_merge import force_merge_source_sites


def main():
    init_db()
    summary = force_merge_source_sites(progress=lambda m: print("[stage4]", m, flush=True))
    print("[stage4] SUMMARY:", {k: v for k, v in summary.items() if k != "exceptions"})
    print("[stage4] exceptions (no SoR match):", len(summary["exceptions"]))


if __name__ == "__main__":
    main()
