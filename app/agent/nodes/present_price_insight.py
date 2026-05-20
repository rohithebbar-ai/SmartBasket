"""
present_price_insight — shows a proactive price-surge warning when the current
price is more than 10% above the 7-day average.

Normal path (no surge or insight already shown):
  → writes nothing; graph continues to propose_tool_action.

Surge path (price_trend_pct > 10.0 and not price_insight_shown):
  → calls LLM with PRICE_INSIGHT_PROMPT
  → sets final_response to the insight message
  → sets price_insight_shown = True
  → sets pending_tool_description = insight message (so await_confirmation
    interrupts with the surge context, not the generic add-to-cart prompt)
  → graph routes to await_confirmation (user can set alert or proceed)

The routing conditional in graph.py routes:
  surge (price_insight_shown just set True)  → await_confirmation
  no surge                                   → propose_tool_action

Reads:  state.price_trend_pct, state.price_insight_shown,
        state.pending_tool_args (product_name, current_price, price_change_reason)
Writes: state.final_response        ← surge path only
        state.pending_tool_description ← surge path only
        state.price_insight_shown   ← surge path only
        state.awaiting_confirmation ← surge path only

Outgoing edges (conditional):
  → await_confirmation  (surge shown — pending_tool_description is the insight)
  → propose_tool_action (no surge or already shown)
"""

import logging

from app.agent.prompts import PRICE_INSIGHT_PROMPT
from app.agent.state import ShopSenseState
from app.llm import call_llm

log = logging.getLogger(__name__)

_SURGE_THRESHOLD = 3.0


async def present_price_insight(state: ShopSenseState) -> dict:
    trend_pct: float = state.get("price_trend_pct") or 0.0
    already_shown: bool = state.get("price_insight_shown") or False

    if already_shown or trend_pct <= _SURGE_THRESHOLD:
        return {}

    args: dict = state.get("pending_tool_args") or {}
    product_name: str = args.get("product_name", "this product")
    current_price: float = float(args.get("current_price") or 0.0)
    reason: str = args.get("price_change_reason") or "high seasonal demand"
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
        log.warning("present_price_insight LLM call failed: %s", exc)
        insight = (
            f"{product_name} is currently ₹{current_price:,.0f}, "
            f"which is {abs(trend_pct):.1f}% {trend_direction} the recent average. "
            "Would you like to set a price-drop alert and wait, or proceed now?"
        )

    return {
        "final_response": insight,
        "pending_tool_description": insight,
        "price_insight_shown": True,
        "awaiting_confirmation": True,
    }
