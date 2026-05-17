"""
Streams McAuley Lab Amazon Reviews 2023 (Electronics) and inserts matched
reviews into PostgreSQL immediately — no RAM accumulation.

Behaviour:
  - Phase 1: streams metadata JSONL to find laptop ASINs, saves to
    data/raw/asin_index.json. Skipped on restart (file already exists).
  - Phase 2: loads current review counts from DB so restarts are safe.
  - Phase 3: streams review JSONL via a generator; each matched review is
    inserted immediately. Stops as soon as every product has hit its target.
  - Phase 4: fills any product still below MIN_SYNTHETIC_FILL with Faker reviews.

Run:
    DATABASE_URL=postgresql+asyncpg://shopsense:shopsense@localhost:5432/shopsense \
      python data/ingestion/fetch_amazon_reviews.py
"""

import asyncio
import json
import logging
import os
import random
import sys
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Generator

import asyncpg
import requests
from faker import Faker
from rapidfuzz import fuzz, process as fuzz_process

from db_utils import dual_connect, fetch_primary, fetchval_primary

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)
fake = Faker()

# ── Constants ─────────────────────────────────────────────────────────────────

HF_BASE = "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main/raw"
META_URL  = f"{HF_BASE}/meta_categories/meta_Electronics.jsonl"
REVIEW_URL = f"{HF_BASE}/review_categories/Electronics.jsonl"

ASIN_INDEX_PATH = Path("data/raw/asin_index.json")

LAPTOP_KEYWORDS  = {"laptop", "notebook", "macbook", "chromebook", "ultrabook", "thinkpad", "ideapad"}
FUZZY_THRESHOLD  = 72
MIN_REVIEWS      = 5
MAX_REVIEWS      = 15
MIN_SYNTHETIC_FILL = 5   # products with fewer real reviews get topped up
MAX_STREAM_ROWS  = 2_000_000  # stop streaming after this many rows regardless
LOG_EVERY        = 50_000


# ── Streaming helper ──────────────────────────────────────────────────────────

def _stream_jsonl(url: str) -> Generator[dict, None, None]:
    """Yields parsed JSON objects from a remote JSONL file without loading it all."""
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        r.encoding = "utf-8"
        buf = ""
        for chunk in r.iter_content(chunk_size=65536, decode_unicode=True):
            buf += chunk
            lines = buf.split("\n")
            buf = lines[-1]
            for line in lines[:-1]:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        pass
        if buf.strip():
            try:
                yield json.loads(buf)
            except json.JSONDecodeError:
                pass


def _asyncpg_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _is_laptop(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in LAPTOP_KEYWORDS)


# ── Phase 1: ASIN index ───────────────────────────────────────────────────────

def load_or_build_asin_index() -> dict[str, dict]:
    """
    Loads laptop ASIN index from disk if available (skips re-streaming).
    Otherwise streams the metadata JSONL, filters laptop items, saves to disk.
    """
    if ASIN_INDEX_PATH.exists():
        log.info("Loading ASIN index from %s …", ASIN_INDEX_PATH)
        with open(ASIN_INDEX_PATH) as f:
            data = json.load(f)
        log.info("Loaded %d laptop ASINs from cache.", len(data))
        return data

    log.info("Streaming Electronics metadata to build ASIN index…")
    asin_index: dict[str, dict] = {}
    total = 0
    for row in _stream_jsonl(META_URL):
        total += 1
        if total % LOG_EVERY == 0:
            log.info("  meta rows: %d  laptop ASINs: %d", total, len(asin_index))
        title = row.get("title") or ""
        if not _is_laptop(title):
            continue
        asin = row.get("parent_asin") or row.get("asin")
        if asin:
            asin_index[asin] = {
                "title": title,
                "store": (row.get("store") or "").strip(),
            }

    log.info("Done. %d meta rows → %d laptop ASINs.", total, len(asin_index))
    ASIN_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ASIN_INDEX_PATH, "w") as f:
        json.dump(asin_index, f)
    log.info("ASIN index saved to %s", ASIN_INDEX_PATH)
    return asin_index


# ── Phase 2: fuzzy matcher ────────────────────────────────────────────────────

def build_matcher(products: list[dict]):
    """
    Returns a function match_asin(asin, meta) → product_id | None.
    Results are cached in a dict so each ASIN is only fuzzy-matched once.
    """
    by_brand: dict[str, list[dict]] = defaultdict(list)
    for p in products:
        by_brand[p["brand"].lower()].append(p)

    _cache: dict[str, uuid.UUID | None] = {}

    def match_asin(asin: str, meta: dict) -> uuid.UUID | None:
        if asin in _cache:
            return _cache[asin]

        amazon_title = meta["title"]
        amazon_store = meta["store"].lower()

        candidate_brands: set[str] = set()
        if amazon_store:
            candidate_brands.add(amazon_store)
        first_word = amazon_title.split()[0].lower() if amazon_title.split() else ""
        if first_word:
            candidate_brands.add(first_word)

        candidates: list[dict] = []
        for brand_key in by_brand:
            if any(fuzz.token_sort_ratio(brand_key, cb) >= 80 for cb in candidate_brands):
                candidates.extend(by_brand[brand_key])

        product_id = None
        if candidates:
            result = fuzz_process.extractOne(
                amazon_title,
                [p["name"] for p in candidates],
                scorer=fuzz.token_sort_ratio,
                score_cutoff=FUZZY_THRESHOLD,
            )
            if result is not None:
                _, _, idx = result
                product_id = candidates[idx]["id"]

        _cache[asin] = product_id
        return product_id

    return match_asin


# ── Phase 3: review generator ─────────────────────────────────────────────────

def matched_review_stream(
    asin_index: dict[str, dict],
    match_asin,
    product_targets: dict[uuid.UUID, int],
    product_counts: dict[uuid.UUID, int],
) -> Generator[tuple[uuid.UUID, dict], None, None]:
    """
    Yields (product_id, review_dict) for each matched review.
    Stops automatically once every product has hit its target count.
    Uses O(1) memory — no accumulation.
    """
    remaining = sum(
        1 for pid, target in product_targets.items()
        if product_counts.get(pid, 0) < target
    )
    log.info("%d products still need reviews.", remaining)
    if remaining == 0 or MAX_STREAM_ROWS == 0:
        return

    total = skipped = matched = 0
    for row in _stream_jsonl(REVIEW_URL):
        total += 1
        if total % LOG_EVERY == 0:
            log.info(
                "  review rows: %d  matched: %d  skipped: %d  products remaining: %d",
                total, matched, skipped, remaining,
            )

        if total >= MAX_STREAM_ROWS:
            log.info("Hit MAX_STREAM_ROWS=%d cap. Stopping stream.", MAX_STREAM_ROWS)
            break

        asin = row.get("parent_asin") or row.get("asin")
        if not asin or asin not in asin_index:
            skipped += 1
            continue

        product_id = match_asin(asin, asin_index[asin])
        if product_id is None:
            skipped += 1
            continue

        current = product_counts.get(product_id, 0)
        target  = product_targets.get(product_id, 0)
        if current >= target:
            continue

        text   = (row.get("text") or "").strip()
        rating = row.get("rating")
        if not text or rating is None:
            continue

        matched += 1
        yield product_id, {"rating": int(rating), "text": text[:2000]}

        product_counts[product_id] = current + 1
        if product_counts[product_id] >= target:
            remaining -= 1
            if remaining == 0:
                log.info("All products filled after %d review rows. Stopping early.", total)
                break

    log.info("Stream finished. Total rows: %d  matched: %d", total, matched)


# ── Phase 4: synthetic fill ───────────────────────────────────────────────────

REVIEW_TEMPLATES = {
    5: [
        "Blazing fast processor. {feat} is outstanding for my daily workload.",
        "Best laptop I've owned. {feat} exceeded expectations — battery lasts all day.",
        "Absolutely love the {feat}. Build quality is premium, no flex on the chassis.",
        "Highly recommend. {feat} handles everything I throw at it with ease.",
    ],
    4: [
        "Solid machine overall. {feat} is great, just wish the fan was quieter.",
        "Good value. {feat} performs well for productivity and light creative work.",
        "Happy with the purchase. {feat} is a strong point — minor nitpicks aside.",
        "Does the job. {feat} is reliable, trackpad could be more precise.",
    ],
    3: [
        "Decent but nothing special. {feat} is average compared to rivals at this price.",
        "Mixed feelings — {feat} is fine for basic tasks but struggles under load.",
        "Gets the job done. {feat} mediocre, would not pay full price for this.",
    ],
    2: [
        "Disappointed with {feat}. Expected better at this price point.",
        "Several issues after a month. {feat} is underwhelming and support was slow.",
    ],
    1: [
        "Terrible. {feat} failed within days and customer support was unhelpful.",
        "Avoid. {feat} is broken out of the box — returning immediately.",
    ],
}

FEATURES = [
    "the keyboard", "the display", "build quality", "the trackpad",
    "RAM performance", "SSD speed", "the webcam", "speaker quality",
    "thermal management", "the hinge mechanism", "battery life",
]


def _synthetic_review() -> dict:
    rating = random.choices([5, 4, 3, 2, 1], weights=[38, 30, 20, 7, 5])[0]
    text = random.choice(REVIEW_TEMPLATES[rating]).format(feat=random.choice(FEATURES))
    return {"rating": rating, "text": text}


# ── DB helpers ────────────────────────────────────────────────────────────────

REVIEW_SQL = (
    "INSERT INTO reviews (id, product_id, rating, review_text) "
    "VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING"
)
BACKFILL_SQL = """
    UPDATE products p SET avg_rating = sub.avg
    FROM (
        SELECT product_id, ROUND(AVG(rating)::numeric, 2) AS avg
        FROM reviews GROUP BY product_id
    ) sub WHERE p.id = sub.product_id
"""


async def get_existing_counts(conns: list, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    rows = await fetch_primary(
        conns,
        "SELECT product_id, COUNT(*)::int AS cnt FROM reviews "
        "WHERE product_id = ANY($1) GROUP BY product_id",
        product_ids,
    )
    return {r["product_id"]: r["cnt"] for r in rows}


async def insert_review(conns: list, product_id: uuid.UUID, rev: dict) -> None:
    rid = uuid.uuid4()
    text = rev["text"] or None
    rating = rev["rating"]
    for conn in conns:
        try:
            await conn.execute(REVIEW_SQL, rid, product_id, rating, text)
        except asyncpg.ForeignKeyViolationError:
            pass  # product doesn't exist on this DB — skip


async def backfill_avg_rating(conns: list) -> None:
    for conn in conns:
        await conn.execute(BACKFILL_SQL)
    log.info("avg_rating back-filled on all DBs.")


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    async with dual_connect() as conns:
        products = [
            {"id": r["id"], "name": r["name"], "brand": r["brand"]}
            for r in await fetch_primary(conns, "SELECT id, name, brand FROM products WHERE is_active = true")
        ]
        product_ids = [p["id"] for p in products]
        log.info("Loaded %d products from DB.", len(products))

        product_targets: dict[uuid.UUID, int] = {
            p["id"]: random.randint(MIN_REVIEWS, MAX_REVIEWS)
            for p in products
        }

        # Restarts pick up where we left off — existing counts loaded from primary
        product_counts = await get_existing_counts(conns, product_ids)
        already_done = sum(1 for pid in product_ids if product_counts.get(pid, 0) >= product_targets[pid])
        log.info("Products already at target: %d / %d", already_done, len(products))

        # Phase 1 — ASIN index (cached to disk after first run)
        asin_index = load_or_build_asin_index()

        # Phase 2 — fuzzy matcher with per-ASIN cache
        match_asin = build_matcher(products)

        # Phase 3 — stream reviews, insert to ALL DBs immediately
        inserted = 0
        for product_id, rev in matched_review_stream(
            asin_index, match_asin, product_targets, product_counts
        ):
            await insert_review(conns, product_id, rev)
            inserted += 1
            if inserted % 5000 == 0:
                log.info("  inserted %d reviews so far…", inserted)

        log.info("Streaming phase done. Inserted: %d", inserted)

        # Phase 4 — batch synthetic fill for products still below MIN_SYNTHETIC_FILL
        log.info("Loading current review counts for synthetic fill…")
        count_rows = await fetch_primary(conns,
            "SELECT product_id, COUNT(*)::int AS cnt FROM reviews GROUP BY product_id"
        )
        existing_counts = {r["product_id"]: r["cnt"] for r in count_rows}

        batch: list[tuple] = []
        for p in products:
            pid = p["id"]
            current = existing_counts.get(pid, 0)
            if current < MIN_SYNTHETIC_FILL:
                needed = random.randint(MIN_SYNTHETIC_FILL, MAX_REVIEWS // 2) - current
                for _ in range(max(needed, 0)):
                    rev = _synthetic_review()
                    batch.append((uuid.uuid4(), pid, rev["rating"], rev["text"]))

        log.info("Batch-inserting %d synthetic reviews to all DBs…", len(batch))
        for conn in conns:
            await conn.executemany(
                "INSERT INTO reviews (id, product_id, rating, review_text) "
                "VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
                batch,
            )
            log.info("  done on one DB.")

        log.info("Synthetic reviews inserted: %d", len(batch))

        await backfill_avg_rating(conns)

        total = await fetchval_primary(conns, "SELECT COUNT(*) FROM reviews")
        log.info("Done. Total reviews in DB: %d", total)


if __name__ == "__main__":
    asyncio.run(main())
