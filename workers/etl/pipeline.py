"""
ETL pipeline — Extract → Map → Validate → Normalise → Load

Usage:
  uv run python -m workers.etl.pipeline --source hm --limit 500
  uv run python -m workers.etl.pipeline --source hm            # full ~105k
"""
import argparse
import asyncio
import logging
import time

log = logging.getLogger(__name__)


async def run_pipeline(source: str = "hm", limit: int = 500) -> int:
    from app.config import settings
    from workers.etl.column_mapper import map_batch
    from workers.etl.validator import validate
    from workers.etl.normaliser import normalise
    from workers.etl.pg_loader import load_batch, _make_dsn
    import asyncpg

    if source == "hm":
        from workers.etl.connectors.hm_connector import HMConnector
        connector = HMConnector()
    else:
        raise ValueError(f"Unknown source: {source}")

    if not connector.validate_connection():
        raise RuntimeError(f"Cannot connect to source: {source}")

    dsn = _make_dsn(settings.database_url)
    conn = await asyncpg.connect(dsn)

    total_loaded   = 0
    total_skipped  = 0
    batch_num      = 0
    start          = time.time()

    log.info("Pipeline starting — source=%s limit=%s", source, limit or "all")

    try:
        async for raw_batch in connector.fetch_batches(limit=limit, batch_size=100):
            batch_num += 1
            mapped    = map_batch(raw_batch, source)
            valid, errors = validate(mapped)
            total_skipped += len(errors)
            normalised = normalise(valid)

            from workers.etl.pg_loader import load_batch as _load
            result = await _load(normalised, conn)
            total_loaded += result.inserted

            if total_loaded % 1000 < 100 or batch_num == 1:
                elapsed = time.time() - start
                rate    = total_loaded / elapsed if elapsed > 0 else 0
                log.info(
                    "Progress: %d loaded, %d skipped — %.1f rows/s",
                    total_loaded, total_skipped, rate,
                )
    finally:
        await conn.close()

    elapsed = time.time() - start
    log.info(
        "Pipeline complete: %d loaded, %d skipped in %.1fs",
        total_loaded, total_skipped, elapsed,
    )
    return total_loaded


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="SmartBasket ETL pipeline")
    parser.add_argument("--source", default="hm", choices=["hm"],
                        help="Data source connector")
    parser.add_argument("--limit", type=int, default=500,
                        help="Max products to ingest (0 = all, default 500 for local dev)")
    args = parser.parse_args()

    limit = args.limit if args.limit > 0 else 0
    count = asyncio.run(run_pipeline(source=args.source, limit=limit))
    print(f"\nLoaded {count} products into Supabase.")


if __name__ == "__main__":
    main()
