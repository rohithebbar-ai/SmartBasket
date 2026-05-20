"""
check_price_trend — queries price_history for the 7-day average and computes
how far the current price deviates, as a percentage.

If the product has no history (new listing or unpopulated table) the node
passes through without setting price_trend_pct — present_price_insight will
skip the surge warning in that case.

Reads:  state.pending_tool_args["product_id"]
        state.pending_tool_args["current_price"]
Writes: state.price_trend_pct  (float, % above 7-day avg; negative = below avg)
        state.pending_tool_args["price_change_reason"] (latest reason from price_history)

Outgoing edge: → present_price_insight
"""

import logging

from sqlalchemy import text

from app.agent.state import ShopSenseState
from app.database import AsyncSessionLocal

log = logging.getLogger(__name__)

_HISTORY_SQL = text("""
    SELECT
        AVG(CAST(new_price AS FLOAT))    AS avg_7d,
        MAX(reason)                       AS latest_reason
    FROM price_history
    WHERE product_id = :product_id
      AND changed_at >= NOW() - INTERVAL '7 days'
""")


async def check_price_trend(state: ShopSenseState) -> dict:
    args: dict = state.get("pending_tool_args") or {}
    product_id = args.get("product_id")
    current_price: float = float(args.get("current_price") or 0.0)

    if not product_id or current_price == 0.0:
        return {}

    try:
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(_HISTORY_SQL, {"product_id": product_id})
            ).mappings().first()
    except Exception as exc:
        log.warning("check_price_trend DB query failed for %s: %s", product_id, exc)
        return {}

    if row is None or row["avg_7d"] is None:
        return {}

    avg_7d: float = float(row["avg_7d"])
    if avg_7d == 0.0:
        return {}

    trend_pct = (current_price - avg_7d) / avg_7d * 100.0
    reason: str = row["latest_reason"] or ""

    updated_args = {**args, "price_change_reason": reason}

    return {
        "price_trend_pct": round(trend_pct, 2),
        "pending_tool_args": updated_args,
    }
