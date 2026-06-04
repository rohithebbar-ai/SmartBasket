#!/usr/bin/env python3
"""
Worker process entry point. Starts all background workers as concurrent tasks.

Run with:
  uv run python workers/run_workers.py
  make workers

Workers:
  personalisation_worker — Kafka consumer for product.viewed / cart.updated /
                           order.created → writes user_preferences to PostgreSQL
  pricing engine         — runs every 120s, reads Redis demand counters,
                           updates products.current_price

Both run in a single asyncio event loop, separate from the FastAPI web process,
so they never block HTTP request handling.
"""

import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

log = logging.getLogger(__name__)


async def main() -> None:
    from workers.personalisation_worker import start as run_personalisation_worker
    from workers.scheduled_agents.post_purchase import run_post_purchase_worker

    log.info("Starting worker process")
    try:
        await asyncio.gather(
            run_personalisation_worker(),
            run_post_purchase_worker(),
        )
    except asyncio.CancelledError:
        log.info("Worker process shutting down")


if __name__ == "__main__":
    asyncio.run(main())
