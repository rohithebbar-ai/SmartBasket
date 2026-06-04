#!/usr/bin/env python3
"""
Scheduled agent runner. Starts all APScheduler jobs.

Run with:
  uv run python workers/run_scheduled_agents.py

Schedules:
  trend_intelligence   — nightly  (01:00)
  restock_prediction   — daily    (06:00)
  post_purchase        — every 6h
  catalogue_gap        — weekly   (Monday 02:00)
"""
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


async def main() -> None:
    from workers.scheduled_agents.trend_intelligence import run as run_trend
    from workers.scheduled_agents.restock_prediction import run as run_restock
    from workers.scheduled_agents.post_purchase import run_post_purchase_worker
    from workers.scheduled_agents.catalogue_gap import run as run_catalogue_gap

    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_trend,        CronTrigger(hour=1, minute=0),   id="trend_intelligence")
    scheduler.add_job(run_restock,      CronTrigger(hour=6, minute=0),   id="restock_prediction")
    scheduler.add_job(run_post_purchase_worker, IntervalTrigger(hours=6), id="post_purchase")
    scheduler.add_job(run_catalogue_gap, CronTrigger(day_of_week="mon", hour=2), id="catalogue_gap")

    scheduler.start()
    log.info("Scheduled agents started")
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
