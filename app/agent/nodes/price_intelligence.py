"""
price_intelligence — single node that queries the 7-day price average and, when the
current price is elevated above the configured threshold, surfaces a proactive insight
asking the user whether to wait for a price drop or proceed with the purchase.

Normal path (no history, or price within threshold, or insight already shown this turn):
  → returns nothing; graph continues to propose_tool_action.

Elevated-price path (trend_pct > _SURGE_THRESHOLD and not price_insight_shown):
  → generates an insight message via PRICE_INSIGHT_PROMPT
  → sets final_response and pending_tool_description to the insight
  → sets price_insight_shown = True and awaiting_confirmation = True
  → graph routes to await_confirmation so the user can choose to wait or proceed

Reads:  state.pending_tool_args (product_id, current_price, price_change_reason)
        state.price_insight_shown
Writes: state.price_trend_pct            ← always (when history exists)
        state.pending_tool_args          ← appends price_change_reason
        state.final_response             ← elevated-price path only
        state.pending_tool_description   ← elevated-price path only
        state.price_insight_shown        ← elevated-price path only
        state.awaiting_confirmation      ← elevated-price path only

Outgoing edges (conditional):
  → await_confirmation  (insight shown — user decides wait or proceed)
  → propose_tool_action (price within normal range)
"""

import logging

from sqlalchemy import text

from app.agent.prompts import PRICE_INSIGHT_PROMPT
from app.agent.state import ShopSenseState
from app.database import AsyncSessionLocal
from app.llm import call_llm

log = logging.getLogger(__name__)

_SURGE_THRESHOLD = 3.0  # percent above 7-day average

_HISTORY_SQL = text("""
    SELECT
        AVG(CAST(new_price AS FLOAT)) AS avg_7d,
        MAX(reason)                   AS latest_reason
    FROM price_history
    WHERE product_id = :product_id
      AND changed_at >= NOW() - INTERVAL '7 days'
""")


async def price_intelligence(state: ShopSenseState) -> dict:
    args: dict = state.get("pending_tool_args") or {}
    product_id = args.get("product_id")
    current_price: float = float(args.get("current_price") or 0.0)
    already_shown: bool = state.get("price_insight_shown") or False

    if not product_id or current_price == 0.0:
        return {}

    # ── Step 1: query 7-day average ───────────────────────────────────────────
    try:
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(_HISTORY_SQL, {"product_id": product_id})
            ).mappings().first()
    except Exception as exc:
        log.warning("price_intelligence DB query failed for %s: %s", product_id, exc)
        return {}

    if row is None or row["avg_7d"] is None:
        return {}

    avg_7d: float = float(row["avg_7d"])
    if avg_7d == 0.0:
        return {}

    trend_pct: float = round((current_price - avg_7d) / avg_7d * 100.0, 2)
    reason: str = row["latest_reason"] or "high seasonal demand"
    updated_args = {**args, "price_change_reason": reason}

    base_update = {
        "price_trend_pct": trend_pct,
        "pending_tool_args": updated_args,
    }

    # ── Step 2: surface insight only when price is elevated and not yet shown ─
    if already_shown or trend_pct <= _SURGE_THRESHOLD:
        return base_update

    product_name: str = args.get("product_name", "this product")
    trend_direction = "above" if trend_pct > 0 else "below"

    prompt = PRICE_INSIGHT_PROMPT.format(
        product_name=product_name,
        current_price=current_price,
        trend_pct=abs(trend_pct),
        trend_direction=trend_direction,
        reason=reason,
    )

    try:
        insight = await call_llm(prompt, tier="generation", max_tokens=150, temperature=0.3)
    except Exception as exc:
        log.warning("price_intelligence LLM call failed: %s", exc)
        insight = (
            f"{product_name} is currently ₹{current_price:,.0f}, "
            f"which is {abs(trend_pct):.1f}% {trend_direction} the recent average. "
            "Would you like to set a price-drop alert and wait, or proceed now?"
        )

    return {
        **base_update,
        "final_response": insight,
        "pending_tool_description": insight,
        "price_insight_shown": True,
        "awaiting_confirmation": True,
    }
