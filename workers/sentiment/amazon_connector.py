"""
Streams real customer reviews from McAuley-Lab/Amazon-Reviews-2023.

Accesses the raw JSONL files directly — bypasses the dataset's deprecated
loading script. Uses both Amazon_Fashion and Clothing_Shoes_and_Jewelry
review files for maximum coverage.

The review pool (4,000 reviews, ~2 MB) is cached locally in
.cache/review_pool.json so subsequent runs skip the HuggingFace stream.
Cache is valid for 7 days, then automatically refreshed.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from pathlib import Path

log = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).resolve().parents[2] / ".cache" / "review_pool.json"
_CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days

# Direct paths to raw JSONL review files (no loading script required)
_REVIEW_FILES = [
    "hf://datasets/McAuley-Lab/Amazon-Reviews-2023/raw/review_categories/Amazon_Fashion.jsonl",
    "hf://datasets/McAuley-Lab/Amazon-Reviews-2023/raw/review_categories/Clothing_Shoes_and_Jewelry.jsonl",
]

# Keywords to bucket reviews into fashion categories (first match wins)
_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("dress",      ["dress", "gown", "frock", "maxi", "midi dress"]),
    ("jeans",      ["jeans", "denim", "skinny jean"]),
    ("jacket",     ["jacket", "blazer", "parka", "puffer", "windbreaker"]),
    ("hoodie",     ["hoodie", "sweatshirt", "pullover", "fleece"]),
    ("sweater",    ["sweater", "jumper", "knit", "cardigan"]),
    ("skirt",      ["skirt"]),
    ("shorts",     ["shorts"]),
    ("trousers",   ["trousers", "pants", "chino", "slacks", "jogger"]),
    ("shirt",      ["shirt", "blouse", "button-up", "button-down"]),
    ("top",        ["top", "t-shirt", "tshirt", "tee ", "vest ", "tank"]),
    ("coat",       ["coat", "trench", "overcoat"]),
]

_FALLBACK_CATEGORY = "clothing"


def _classify_review(text: str, title: str) -> str:
    combined = (text + " " + title).lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(kw in combined for kw in keywords):
            return category
    return _FALLBACK_CATEGORY


def build_review_pool(
    total_limit: int = 4000,
    min_text_length: int = 40,
) -> dict[str, list[dict]]:
    """
    Streams real Amazon fashion reviews and buckets them by category.

    Returns dict keyed by category. Reviews sorted by helpfulness (best first).
    Streams from HuggingFace directly — nothing written to disk.
    """
    import datasets as hf_datasets

    hf_datasets.disable_caching()

    # ── Cache check ──────────────────────────────────────────────────────────
    if _CACHE_PATH.exists():
        age = time.time() - _CACHE_PATH.stat().st_mtime
        if age < _CACHE_TTL_SECONDS:
            log.info("Loading review pool from cache (%s, %.0fh old)", _CACHE_PATH, age / 3600)
            cached = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            for cat in cached:
                cached[cat].sort(
                    key=lambda r: (r["helpful_vote"] + (2 if r["verified"] else 0)),
                    reverse=True,
                )
            return cached
        else:
            log.info("Cache expired (%.0f days old) — refreshing from HuggingFace", age / 86400)

    log.info("Streaming Amazon fashion reviews from HuggingFace (limit=%d)…", total_limit)

    ds = hf_datasets.load_dataset(
        "json",
        data_files={"train": _REVIEW_FILES},
        split="train",
        streaming=True,
    )

    pool: dict[str, list[dict]] = defaultdict(list)
    count = 0

    for row in ds:
        if count >= total_limit:
            break

        text = (row.get("text") or "").strip()
        title = (row.get("title") or "").strip()

        if len(text) < min_text_length:
            continue

        try:
            rating = int(float(row.get("rating", 3)))
        except (ValueError, TypeError):
            rating = 3

        helpful = 0
        try:
            helpful = int(row.get("helpful_vote", 0))
        except (ValueError, TypeError):
            pass

        category = _classify_review(text, title)
        pool[category].append({
            "rating": rating,
            "text": text,
            "title": title,
            "helpful_vote": helpful,
            "verified": str(row.get("verified_purchase", "False")).lower() == "true",
        })
        count += 1

    # Sort each bucket: helpful + verified first, then by rating (mixed)
    for cat in pool:
        pool[cat].sort(
            key=lambda r: (r["helpful_vote"] + (2 if r["verified"] else 0)),
            reverse=True,
        )

    log.info(
        "Review pool built: %d reviews across %d categories",
        count,
        len(pool),
    )
    for cat, reviews in sorted(pool.items(), key=lambda x: -len(x[1])):
        log.info("  %-12s  %d reviews", cat, len(reviews))

    # ── Save to cache ─────────────────────────────────────────────────────────
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(dict(pool), ensure_ascii=False), encoding="utf-8")
        log.info("Review pool cached to %s", _CACHE_PATH)
    except Exception as e:
        log.warning("Could not write review pool cache: %s", e)

    return dict(pool)


def get_reviews_for_category(
    pool: dict[str, list[dict]],
    hm_category: str,
    n_positive: int = 18,
    n_negative: int = 7,
) -> list[dict]:
    """
    Return a balanced set of real reviews for the given H&M category.
    Falls back to general 'clothing' pool if category has fewer than 5 reviews.
    """
    key = _hm_to_pool_key(hm_category)
    reviews = pool.get(key, [])

    if len(reviews) < 5:
        reviews = pool.get(_FALLBACK_CATEGORY, [])

    positives = [r for r in reviews if r["rating"] >= 4][:n_positive]
    negatives = [r for r in reviews if r["rating"] <= 2][:n_negative]

    if len(positives) < n_positive:
        mid = [r for r in reviews if r["rating"] == 3]
        positives += mid[: n_positive - len(positives)]

    return positives + negatives


def _hm_to_pool_key(hm_category: str) -> str:
    lowered = hm_category.lower()
    for key, keywords in _CATEGORY_KEYWORDS:
        if any(kw in lowered for kw in keywords):
            return key
    return _FALLBACK_CATEGORY
