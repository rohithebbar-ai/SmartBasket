#!/usr/bin/env python3
import argparse
import asyncio
import json
import logging
import os
import time
from pathlib import Path

import asyncpg
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger(__name__)

_QUEUE_KEY = "embedding_queue"
_SENTIMENT_KEYS = (
    "style_sentiment",
    "quality_sentiment",
    "fit_sentiment",
    "comfort_sentiment",
    "versatility_sentiment",
    "delivery_sentiment",
)


def _asyncpg_url(database_url: str) -> str:
    """Strip SQLAlchemy driver prefix and any query-string suffix for asyncpg."""
    url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    if "?" in url:
        url = url[: url.index("?")]
    return url


# ── Text builders ──────────────────────────────────────────────────────────────

def _parse_attrs(row: dict) -> dict:
    raw = row.get("attributes") or {}
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}
    return dict(raw)


def build_embedding_text(row: dict) -> str:
    attrs = _parse_attrs(row)
    colour = attrs.get("colour") or attrs.get("colour_master")
    pattern = attrs.get("pattern")
    garment_group = attrs.get("garment_group")
    description = (row.get("description") or "")[:500]

    parts = [
        row.get("name"),
        row.get("category"),
        row.get("brand"),
        description or None,
        colour,
        pattern if pattern and pattern not in ("Solid", "undefined") else None,
        garment_group,
        f'Customers love: "{row["top_praise"]}"' if row.get("top_praise") else None,
    ]
    return ". ".join(p for p in parts if p)


def build_payload(row: dict) -> dict:
    attrs = _parse_attrs(row)
    payload: dict = {
        "product_id":      str(row["id"]),
        "name":            row.get("name"),
        "brand":           row.get("brand"),
        "category":        row.get("category"),
        "current_price":   float(row["current_price"]) if row.get("current_price") is not None else None,
        "avg_rating":      float(row["avg_rating"]) if row.get("avg_rating") is not None else None,
        "stock_available": (row.get("stock_count") or 0) > 0,
        "image_url":       row.get("image_url"),
        "description":     (row.get("description") or "")[:600],
        "attributes_json": json.dumps(attrs),
        "colour":          attrs.get("colour") or attrs.get("colour_master"),
        "pattern":         attrs.get("pattern"),
        "top_praise":      row.get("top_praise"),
        "top_complaint":   row.get("top_complaint"),
    }
    for key in _SENTIMENT_KEYS:
        value = row.get(key)
        if value is not None:
            payload[key] = float(value)
    return payload


# ── Queue management ───────────────────────────────────────────────────────────

async def enqueue_pending(pool: asyncpg.Pool, redis_client) -> int:
    rows = await pool.fetch(
        """
        SELECT id::text
        FROM products
        WHERE external_product_id IS NOT NULL
          AND sentiment_scored_at IS NOT NULL
          AND embedding_status = 'pending'
        """
    )
    if not rows:
        return 0
    ids = [r["id"] for r in rows]
    await redis_client.rpush(_QUEUE_KEY, *ids)
    log.info("Enqueued %d products into %s", len(ids), _QUEUE_KEY)
    return len(ids)


# ── Embedding with exponential backoff ─────────────────────────────────────────

async def _embed_with_retry(passages: list[str], embed_batch) -> list[list[float]]:
    loop = asyncio.get_running_loop()
    backoff = 5.0
    for attempt in range(3):
        try:
            return await loop.run_in_executor(None, embed_batch, passages)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 429:
                wait = min(backoff, 60.0)
                log.warning("Jina rate-limited (429) — waiting %.0fs (attempt %d/3)", wait, attempt + 1)
                await asyncio.sleep(wait)
                backoff *= 2
            else:
                raise
    # Final attempt — let the exception propagate
    return await loop.run_in_executor(None, embed_batch, passages)


# ── Main worker loop ───────────────────────────────────────────────────────────

async def run_worker(redis_client, pool: asyncpg.Pool, batch_size: int) -> None:
    from app.search.embedder import embed_batch
    from app.search.qdrant_ops import ensure_collection, upsert_batch

    loop = asyncio.get_running_loop()

    ensure_collection()

    total = await redis_client.llen(_QUEUE_KEY)
    if total == 0:
        log.info("Queue is empty — nothing to embed")
        return

    log.info("Starting embedding run: %d products in queue (batch_size=%d)", total, batch_size)
    done = 0
    start = time.monotonic()

    while True:
        raw = await redis_client.lpop(_QUEUE_KEY, batch_size)
        if raw is None:
            break

        ids = [item.decode() if isinstance(item, bytes) else item for item in raw]

        rows = await pool.fetch(
            """
            SELECT id, name, brand, category, description, image_url,
                   current_price, stock_count, avg_rating, attributes,
                   style_sentiment, quality_sentiment, fit_sentiment,
                   comfort_sentiment, versatility_sentiment, delivery_sentiment,
                   top_praise, top_complaint
            FROM products
            WHERE id = ANY($1::uuid[])
            """,
            ids,
        )

        if not rows:
            continue

        row_dicts = [dict(r) for r in rows]
        passages = [build_embedding_text(r) for r in row_dicts]
        payloads = [build_payload(r) for r in row_dicts]

        vectors = await _embed_with_retry(passages, embed_batch)

        points = [(str(r["id"]), vec, payload) for r, vec, payload in zip(row_dicts, vectors, payloads)]
        await loop.run_in_executor(None, upsert_batch, points)

        await pool.execute(
            "UPDATE products SET embedding_status = 'embedded' WHERE id = ANY($1::uuid[])",
            ids,
        )

        done += len(ids)
        elapsed = time.monotonic() - start
        rate = done / elapsed if elapsed > 0 else 0.0
        remaining = total - done
        eta = remaining / rate if rate > 0 else float("inf")
        log.info(
            "[%d/%d] %d products embedded (%.1f/s, ETA %.0fs)",
            done, total, len(ids), rate, eta,
        )

    log.info("Embedding run complete: %d products embedded in %.1fs", done, time.monotonic() - start)


# ── Entry point ────────────────────────────────────────────────────────────────

async def _async_main(args: argparse.Namespace) -> None:
    import redis.asyncio as aioredis

    database_url = _asyncpg_url(os.environ["DATABASE_URL"])
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    pool = await asyncpg.create_pool(
        database_url,
        min_size=1,
        max_size=3,
        command_timeout=30,
        server_settings={"tcp_keepalives_idle": "60"},
    )
    redis_client = aioredis.from_url(redis_url, decode_responses=False)

    try:
        if args.enqueue:
            await enqueue_pending(pool, redis_client)

        if args.run:
            await run_worker(redis_client, pool, args.batch_size)
    finally:
        await pool.close()
        await redis_client.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fashion embedding worker")
    parser.add_argument("--enqueue", action="store_true", help="Push pending product IDs to Redis queue")
    parser.add_argument("--run", action="store_true", help="Process the embedding queue")
    parser.add_argument("--batch-size", type=int, default=100, dest="batch_size")
    args = parser.parse_args()

    # Default: run unless --enqueue is passed alone
    args.run = args.run or not args.enqueue

    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
