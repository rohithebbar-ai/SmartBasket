#!/usr/bin/env python3
import argparse
import asyncio
import logging
import os
from pathlib import Path

import redis.asyncio as aioredis
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger(__name__)


def _make_async_dsn(database_url: str) -> str:
    """Ensure the DSN uses the asyncpg driver for SQLAlchemy."""
    url = database_url.split("?")[0]
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


async def _set_redis_key(redis: aioredis.Redis, key: str, values: set[str]) -> int:
    async with redis.pipeline(transaction=True) as pipe:
        pipe.delete(key)
        if values:
            pipe.sadd(key, *values)
        await pipe.execute()
    log.info("Indexed %s — %d values", key, len(values))
    return len(values)


async def index_fashion(engine, redis: aioredis.Redis) -> None:
    async with engine.connect() as conn:
        # JSONB attribute columns
        for attr in ("colour", "pattern", "garment_group", "section"):
            rows = await conn.execute(text(
                f"""
                SELECT DISTINCT attributes->>:attr AS val
                FROM products
                WHERE external_product_id IS NOT NULL
                  AND attributes->>:attr IS NOT NULL
                  AND attributes->>:attr != ''
                """
            ), {"attr": attr})
            values = {row.val for row in rows}
            await _set_redis_key(redis, f"attrs:fashion:{attr}", values)

        # Plain column
        rows = await conn.execute(text(
            """
            SELECT DISTINCT category
            FROM products
            WHERE external_product_id IS NOT NULL
              AND category IS NOT NULL
              AND category != ''
            """
        ))
        await _set_redis_key(redis, "attrs:fashion:category", {row.category for row in rows})


async def index_electronics(engine, redis: aioredis.Redis) -> None:
    async with engine.connect() as conn:
        for column in ("brand", "category"):
            rows = await conn.execute(text(
                f"""
                SELECT DISTINCT {column}
                FROM products
                WHERE external_product_id IS NULL
                  AND is_active = true
                  AND {column} IS NOT NULL
                  AND {column} != ''
                """
            ))
            await _set_redis_key(redis, f"attrs:electronics:{column}", {row[0] for row in rows})

        rows = await conn.execute(text(
            """
            SELECT DISTINCT specs->>'ram_gb' AS val
            FROM products
            WHERE external_product_id IS NULL
              AND is_active = true
              AND specs->>'ram_gb' IS NOT NULL
            """
        ))
        await _set_redis_key(redis, "attrs:electronics:ram", {row.val for row in rows})

        # specs->'use_cases' is a JSONB array; unnest individual elements
        rows = await conn.execute(text(
            """
            SELECT DISTINCT jsonb_array_elements_text(specs->'use_cases') AS val
            FROM products
            WHERE external_product_id IS NULL
              AND is_active = true
              AND specs ? 'use_cases'
            """
        ))
        await _set_redis_key(redis, "attrs:electronics:use_case", {row.val for row in rows if row.val})


async def run(catalogue: str | None = None) -> None:
    dsn = _make_async_dsn(os.environ["DATABASE_URL"])
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    engine = create_async_engine(dsn, echo=False)
    redis = aioredis.from_url(redis_url, decode_responses=True)

    try:
        if catalogue is None or catalogue == "fashion":
            log.info("Indexing fashion attributes…")
            await index_fashion(engine, redis)

        if catalogue is None or catalogue == "electronics":
            log.info("Indexing electronics attributes…")
            await index_electronics(engine, redis)
    finally:
        await engine.dispose()
        await redis.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Post-ETL attribute indexer")
    parser.add_argument(
        "--catalogue",
        choices=["fashion", "electronics"],
        default=None,
        help="Limit indexing to a single catalogue (default: both)",
    )
    args = parser.parse_args()
    asyncio.run(run(args.catalogue))


if __name__ == "__main__":
    main()
