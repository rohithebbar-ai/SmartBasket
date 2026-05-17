#!/usr/bin/env python3
"""
Worker process entry point. Starts all background workers as concurrent tasks.

Run with: uv run python workers/run_workers.py
Or:       make workers

Workers started:
  - personalisation_worker: Kafka consumer → user preference profiles
  - pricing engine: runs every 120s, reads Redis demand counters, updates prices

This process runs separately from the FastAPI web server so LangGraph workflows
and pricing cycles never block web request handling.
"""

# TODO: implement in Week 3 (Day 14)
# import asyncio
# from workers.personalisation_worker import start as start_personalisation
# from app.search.pricing_engine import run_pricing_loop
#
# async def main():
#     await asyncio.gather(
#         start_personalisation(),
#         run_pricing_loop(),
#     )
#
# if __name__ == "__main__":
#     asyncio.run(main())
