"""
Shared DB utility for ingestion scripts.

Returns asyncpg connections to write to:
  - Always: DATABASE_URL (local Docker postgres)
  - If set: MIRROR_DATABASE_URL (Supabase) — ingestion only, never used by the app

Usage:
    async with dual_connect() as conns:
        for conn in conns:
            await conn.execute(...)
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import asyncpg
from dotenv import load_dotenv

# Load .env from project root (two levels up from data/ingestion/)
load_dotenv(Path(__file__).parent.parent.parent / ".env")


def _asyncpg_dsn(url: str) -> str:
    return (
        url.replace("postgresql+asyncpg://", "postgresql://")
           .replace("postgres+asyncpg://", "postgresql://")
    )


def _get_dsns() -> list[tuple[str, str]]:
    """
    Returns list of (label, dsn) to write to.
    Local is always FIRST so fetch_primary / fetchval_primary reads from local
    (fast) regardless of which URL is the app's DATABASE_URL.
    """
    primary = os.environ.get("DATABASE_URL", "")
    mirror  = os.environ.get("MIRROR_DATABASE_URL", "").strip()

    if not primary and not mirror:
        raise RuntimeError("DATABASE_URL is not set")

    # Determine which URL is local vs remote by checking for localhost/127
    def _is_local(url: str) -> bool:
        return "localhost" in url or "127.0.0.1" in url

    targets: list[tuple[str, str]] = []

    # Always put local first so reads are fast
    for label, url in [("primary", primary), ("mirror", mirror)]:
        if not url:
            continue
        if _is_local(url):
            targets.insert(0, ("local", _asyncpg_dsn(url)))
        else:
            targets.append(("supabase", _asyncpg_dsn(url)))
            print("Mirror write enabled → Supabase")

    if not targets:
        raise RuntimeError("No valid DATABASE_URL configured")

    return targets


@asynccontextmanager
async def dual_connect() -> AsyncGenerator[list[asyncpg.Connection], None]:
    """
    Async context manager that opens connections to all configured databases
    and closes them cleanly on exit.

    async with dual_connect() as conns:
        for conn in conns:
            await conn.execute(...)
    """
    targets = _get_dsns()
    conns: list[asyncpg.Connection] = []
    try:
        for label, dsn in targets:
            conn = await asyncpg.connect(dsn)
            conns.append(conn)
            print(f"  connected → {label}")
        yield conns
    finally:
        for conn in conns:
            await conn.close()


async def exec_all(conns: list[asyncpg.Connection], query: str, *args) -> None:
    """Executes the same query+args on every connection."""
    for conn in conns:
        await conn.execute(query, *args)


async def fetchval_primary(conns: list[asyncpg.Connection], query: str, *args):
    """Runs fetchval on the primary (first) connection only."""
    return await conns[0].fetchval(query, *args)


async def fetch_primary(conns: list[asyncpg.Connection], query: str, *args):
    """Runs fetch on the primary (first) connection only."""
    return await conns[0].fetch(query, *args)
