"""
handle_purchase_intent — checkout entry flow (Day 13: steps 1-4 only).

Reads product context from state["sources"][0], which is set by the search node
that ran in the same or previous turn. The user typically says "I'll take it" or
"buy the first one" after seeing search results, so sources contains the product_id.

Steps implemented today:
  1. Identify product — read sources[0], fetch fresh price + stock from PostgreSQL.
  2. check_stock_status — if stock_count == 0, surface an out-of-stock message.
  3. get_delivery_estimate — hardcoded by stock level (MCP tool on Day 14).
  4. Build add_to_cart payload and route to check_price_trend → present_price_insight
     → propose_tool_action → await_confirmation.

Steps deferred to Day 14 (MCP):
  5. get_frequently_bought_together cross-sell after add_to_cart.
  6. Payment flow (process_payment tool).

Reads:  state.sources (product_id from previous search)
Writes: state.pending_tool ("add_to_cart")
        state.pending_tool_args (product_id, product_name, current_price,
                                 quantity, delivery_estimate)
        state.pending_tool_description (human-readable for propose_tool_action)
        state.cart_summary (stock_count, stock_available, delivery_days)
        state.final_response  ← error path only

Outgoing edges:
  → check_price_trend (normal — pending_tool set)
  → save_history     (error — product not found or out of stock)
"""

import logging

from sqlalchemy import text

from app.agent.state import ShopSenseState
from app.database import AsyncSessionLocal

log = logging.getLogger(__name__)

_STOCK_SQL = text("""
    SELECT id, name, brand, CAST(current_price AS FLOAT) AS current_price, stock_count
    FROM products
    WHERE id = :product_id
    LIMIT 1
""")

_NO_PRODUCT_MSG = (
    "Which product would you like to buy? Let me pull it up for you."
)
_OUT_OF_STOCK_MSG = (
    "Sorry, that product is out of stock right now. "
    "Want me to notify you when it's back?"
)


def _delivery_estimate(stock_count: int) -> tuple[str, int]:
    """Returns (human-readable estimate, days) based on stock level."""
    if stock_count > 10:
        return "3-5 business days", 4
    return f"5-7 business days (low stock — only {stock_count} left)", 6


async def handle_purchase_intent(state: ShopSenseState) -> dict:
    # Step 1 — Identify product from previous search sources
    sources = state.get("sources") or []
    product_id = sources[0] if sources else None

    if not product_id:
        return {"final_response": _NO_PRODUCT_MSG}

    # Step 1b — Fetch fresh price + stock from PostgreSQL
    db_row = None
    try:
        async with AsyncSessionLocal() as db:
            db_row = (
                await db.execute(_STOCK_SQL, {"product_id": product_id})
            ).mappings().first()
    except Exception as exc:
        log.warning("DB fetch failed for product %s: %s", product_id, exc)

    if db_row is None:
        return {"final_response": _NO_PRODUCT_MSG}

    stock_count = int(db_row["stock_count"])
    current_price = float(db_row["current_price"])
    display_name = f"{db_row['brand']} {db_row['name']}"

    # Step 2 — check_stock_status
    if stock_count == 0:
        return {"final_response": _OUT_OF_STOCK_MSG}

    # Step 3 — get_delivery_estimate (hardcoded until Day 14 MCP)
    delivery_str, delivery_days = _delivery_estimate(stock_count)

    # Step 4 — Build add_to_cart payload
    description = (
        f"add {display_name} (₹{current_price:,.0f}, "
        f"delivery in {delivery_str}) to your cart"
    )

    return {
        "pending_tool": "add_to_cart",
        "pending_tool_args": {
            "product_id": product_id,
            "product_name": display_name,
            "current_price": current_price,
            "quantity": 1,
            "delivery_estimate": delivery_str,
        },
        "pending_tool_description": description,
        "cart_summary": {
            "stock_count": stock_count,
            "stock_available": True,
            "delivery_days": delivery_days,
        },
        # TODO Day 14: get_frequently_bought_together cross-sell
        # TODO Day 14: payment flow via process_payment tool
    }
