"""
Bulk upsert normalised product rows to Supabase (PostgreSQL).

Uses asyncpg directly for performance on large batches.
ON CONFLICT (external_product_id) DO UPDATE — safe to re-run.
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field

import asyncpg

log = logging.getLogger(__name__)

UPSERT_SQL = """
INSERT INTO products (
    external_product_id, name, brand, category, description,
    image_url, attributes,
    base_price, current_price, stock_count, avg_rating,
    is_active, embedding_status, last_ingested_at
)
VALUES (
    $1, $2, $3, $4, $5,
    $6, $7::jsonb,
    $8, $9, $10, $11,
    $12, 'pending', NOW()
)
ON CONFLICT (external_product_id) DO UPDATE SET
    name             = EXCLUDED.name,
    brand            = EXCLUDED.brand,
    category         = EXCLUDED.category,
    description      = EXCLUDED.description,
    image_url        = EXCLUDED.image_url,
    attributes       = EXCLUDED.attributes,
    base_price       = EXCLUDED.base_price,
    current_price    = EXCLUDED.current_price,
    stock_count      = EXCLUDED.stock_count,
    is_active        = EXCLUDED.is_active,
    embedding_status = 'pending',
    last_ingested_at = NOW()
"""


@dataclass
class LoadResult:
    inserted: int = 0
    errors: list[str] = field(default_factory=list)


def _make_dsn(database_url: str) -> str:
    """Strip SQLAlchemy driver prefix for asyncpg."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


async def load_batch(rows: list[dict], conn: asyncpg.Connection) -> LoadResult:
    result = LoadResult()
    records = []
    for row in rows:
        try:
            records.append((
                row["external_product_id"],
                row["name"],
                row.get("brand", "H&M"),
                row["category"],
                row.get("description"),
                row.get("image_url"),
                json.dumps(row.get("attributes", {})),
                float(row["base_price"]),
                float(row["current_price"]),
                int(row.get("stock_count", 50)),
                float(row.get("avg_rating", 0.0)),
                bool(row.get("is_active", True)),
            ))
        except Exception as e:
            result.errors.append(f"{row.get('external_product_id')}: {e}")

    if records:
        await conn.executemany(UPSERT_SQL, records)
        result.inserted = len(records)

    return result


async def load_all(batches: list[list[dict]], database_url: str) -> LoadResult:
    """Load all batches through a single connection."""
    dsn = _make_dsn(database_url)
    conn = await asyncpg.connect(dsn)
    total = LoadResult()
    try:
        for batch in batches:
            r = await load_batch(batch, conn)
            total.inserted += r.inserted
            total.errors.extend(r.errors)
    finally:
        await conn.close()
    return total
