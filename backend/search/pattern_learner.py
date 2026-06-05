"""
Search pattern generation and effectiveness tracking for Beat This Price.

Each "pattern" is a relative strategy for deriving a search query from a
product title by progressively dropping trailing words:

  full       — full title as-is (including any post-dash suffix)
  pre_dash   — only the words before the first ' - '
  pd_m1      — pre-dash words minus the last word
  pd_m2      — pre-dash words minus 2 last words
  ...        — continues down to a minimum of 2 words

The system runs all applicable patterns concurrently, scores every result
against the original title using fuzzy matching, and learns which patterns
historically produce the highest match scores.  After LEARN_THRESHOLD distinct
product searches the active set is capped to the top MAX_ACTIVE patterns.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from backend.database.models import BeatPricePatternStats

# All pattern IDs in default execution order.
ALL_PATTERN_IDS: List[str] = [
    "full",
    "pre_dash",
    "pd_m1", "pd_m2", "pd_m3", "pd_m4",
    "pd_m5", "pd_m6", "pd_m7", "pd_m8",
]

LEARN_THRESHOLD = 1000   # product searches before locking to top patterns
MAX_ACTIVE = 3           # patterns kept after threshold is reached


# ---------------------------------------------------------------------------
# Query generation
# ---------------------------------------------------------------------------

def _pre_dash_words(title: str) -> List[str]:
    """Words preceding the first ' - ' in title, or all words if no dash."""
    for sep in (" - ", " -"):
        if sep in title:
            return title.split(sep, 1)[0].strip().split()
    return title.split()


def generate_queries(title: str) -> List[Tuple[str, str]]:
    """
    Return an ordered list of (pattern_id, query_text) for a product title.

    Rules:
    - Starts with the full title (strategy 0).
    - Then the pre-dash portion (strategy 1).
    - Then the pre-dash words minus one word per step until only 2 remain.
    - Duplicate texts are skipped so identical adjacent strategies collapse.
    - Any candidate with fewer than 2 words is omitted.
    """
    seen: set = set()
    out: List[Tuple[str, str]] = []

    def _push(pid: str, text: str) -> None:
        text = text.strip()
        if text and text not in seen and len(text.split()) >= 2:
            seen.add(text)
            out.append((pid, text))

    _push("full", title)

    words = _pre_dash_words(title)
    _push("pre_dash", " ".join(words))

    reduction_pids = ["pd_m1", "pd_m2", "pd_m3", "pd_m4",
                      "pd_m5", "pd_m6", "pd_m7", "pd_m8"]
    for i, pid in enumerate(reduction_pids):
        n = len(words) - (i + 1)
        if n < 2:
            break
        _push(pid, " ".join(words[:n]))

    return out


# ---------------------------------------------------------------------------
# Pattern stats management
# ---------------------------------------------------------------------------

def get_active_patterns(db: Session) -> List[str]:
    """
    Return pattern IDs to execute, ordered best-first.

    Before LEARN_THRESHOLD: all known IDs (ranked rows first, then defaults).
    After LEARN_THRESHOLD: top MAX_ACTIVE by avg_best_fuzzy.
    """
    rows: List[BeatPricePatternStats] = db.query(BeatPricePatternStats).all()

    full_row = next((r for r in rows if r.pattern_id == "full"), None)
    learned_enough = full_row and full_row.total_products >= LEARN_THRESHOLD

    ranked = sorted(rows, key=lambda r: -(r.avg_best_fuzzy or 0.0))

    if learned_enough:
        return [r.pattern_id for r in ranked[:MAX_ACTIVE]]

    ranked_ids = [r.pattern_id for r in ranked]
    remaining = [pid for pid in ALL_PATTERN_IDS if pid not in set(ranked_ids)]
    return ranked_ids + remaining


def record_pattern_results(
    db: Session,
    used_pattern_ids: List[str],
    per_pattern_best_fuzzy: Dict[str, int],
) -> None:
    """
    Update pattern effectiveness stats after one product search.

    used_pattern_ids : patterns that were actually executed.
    per_pattern_best_fuzzy : {pattern_id: best fuzzy score found} for each
        pattern that returned at least one result; missing keys treated as 0.
    """
    for pid in used_pattern_ids:
        best = int(per_pattern_best_fuzzy.get(pid, 0))
        row = db.query(BeatPricePatternStats).filter_by(pattern_id=pid).first()
        if row is None:
            row = BeatPricePatternStats(
                pattern_id=pid, total_products=0, sum_best_fuzzy=0.0, avg_best_fuzzy=0.0,
            )
            db.add(row)
        row.total_products += 1
        row.sum_best_fuzzy = (row.sum_best_fuzzy or 0.0) + best
        row.avg_best_fuzzy = row.sum_best_fuzzy / row.total_products

    # Re-rank all patterns
    all_rows: List[BeatPricePatternStats] = db.query(BeatPricePatternStats).all()
    for i, r in enumerate(sorted(all_rows, key=lambda r: -(r.avg_best_fuzzy or 0.0))):
        r.rank = i + 1

    db.flush()
