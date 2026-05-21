"""
handle_purchase_intent — entry point for the purchase flow.

Reads state["sources"][0], which is populated by whichever search node ran in
the same or a prior turn. Fetches fresh price and stock from PostgreSQL, checks
availability, computes a delivery estimate, and builds the add_to_cart payload.

Reads:  state.sources (product_id from the most recent search result)
Writes: state.pending_tool ("add_to_cart")
        state.pending_tool_args (product_id, product_name, current_price,
                                 quantity, delivery_estimate)
        state.pending_tool_description (human-readable summary for confirmation)
        state.cart_summary (stock_count, stock_available, delivery_days)
        state.final_response  ← error path only (product not found or out of stock)

Outgoing edges:
  → check_price_trend  (normal — pending_tool is set)
  → save_history       (error — product not found or out of stock)
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

    # Step 2 — check_stock_status; set recommend_alternatives_query so the graph
    # routes to recommend_alternatives instead of dropping straight to save_history
    if stock_count == 0:
        return {
            "final_response": _OUT_OF_STOCK_MSG,
            "recommend_alternatives_query": display_name,
        }

    # Step 3 — estimate delivery window based on stock level
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
        # Cross-sell and payment flow are handled by downstream MCP tools.
    }
