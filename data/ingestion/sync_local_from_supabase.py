"""
One-time sync: copy all products from Supabase to local Docker postgres
with the EXACT SAME UUIDs so both DBs are aligned for review ingestion.
"""
import asyncio
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")


def _to_asyncpg_dsn(url: str) -> str:
    return (
        url.replace("postgresql+asyncpg://", "postgresql://")
           .replace("postgres+asyncpg://", "postgresql://")
    )


async def main() -> None:
    supabase_dsn = _to_asyncpg_dsn(os.environ["DATABASE_URL"])
    local_dsn    = _to_asyncpg_dsn(os.environ["MIRROR_DATABASE_URL"])

    print("Connecting...")
    supabase = await asyncpg.connect(supabase_dsn)
    local    = await asyncpg.connect(local_dsn)

    rows = await supabase.fetch("SELECT * FROM products")
    print(f"Supabase: {len(rows)} products")

    # Wipe local (cascade clears reviews too) and replace with Supabase rows
    await local.execute("TRUNCATE TABLE products CASCADE")

    inserted = 0
    for row in rows:
        await local.execute(
            "INSERT INTO products "
            "(id,name,brand,category,base_price,current_price,specs,stock_count,avg_rating,is_active,created_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
            row["id"], row["name"], row["brand"], row["category"],
            row["base_price"], row["current_price"], row["specs"],
            row["stock_count"], row["avg_rating"], row["is_active"], row["created_at"],
        )
        inserted += 1
        if inserted % 1000 == 0:
            print(f"  copied {inserted}/{len(rows)}...")

    count = await local.fetchval("SELECT COUNT(*) FROM products")
    print(f"Done. Local now has {count} products with Supabase UUIDs.")

    await supabase.close()
    await local.close()


if __name__ == "__main__":
    asyncio.run(main())
