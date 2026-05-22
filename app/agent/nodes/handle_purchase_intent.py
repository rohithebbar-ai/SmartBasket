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
import re

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


_RESELLER_TAGS = {"amazon renewed", "amazon", "renewed"}
_STOPWORDS = {"the", "a", "an", "and", "or", "for", "with", "by", "to", "in", "of", "laptop", "computer"}


def _expand_token(token: str) -> list[str]:
    """Split hyphenated/comma/paren tokens: '15-inch,' → ['15-inch,', '15', 'inch']."""
    parts = re.split(r'[-,/()\.]', token)
    return [token] + [p for p in parts if p and p != token]


def _best_match_index(query: str, search_results: list[dict]) -> int:
    """Return the index of the result whose name/brand best matches the user's query.

    Key fix: uses exact q_words matching (set lookup) so short tokens like '15', '13'
    are scored correctly. Also expands hyphenated specs: '15-inch,' → '15', 'inch'.
    """
    if not search_results:
        return 0
    q = query.lower()
    q_words = set(q.split())

    best_idx = 0
    best_score = -1
    for i, r in enumerate(search_results):
        name = (r.get("name") or "").lower()
        brand = (r.get("brand") or "").lower()

        if brand in _RESELLER_TAGS:
            name_words = name.split()
            real_brand = name_words[0] if name_words else ""
        else:
            real_brand = brand

        # Expand all tokens (handle hyphenated specs like "15-inch,")
        raw = name.split() + real_brand.split()
        tokens: set[str] = set()
        for t in raw:
            tokens.update(_expand_token(t))
        tokens -= _STOPWORDS

        # Score: each token that appears as a whole word in the query (len ≥ 2)
        score = sum(1 for t in tokens if len(t) >= 2 and t in q_words)

        if real_brand and real_brand in q:
            score += 3

        score_with_tiebreak = score - i * 0.001
        if score_with_tiebreak > best_score:
            best_score = score_with_tiebreak
            best_idx = i
    return best_idx


async def handle_purchase_intent(state: ShopSenseState) -> dict:
    # Step 1 — Identify which product the user wants from their message
    sources = state.get("sources") or []
    search_results = state.get("search_results") or []
    messages = state.get("messages", [])
    user_query = messages[-1]["content"] if messages else ""

    # Match the user's words to the most relevant product in prior search results
    match_idx = _best_match_index(user_query, search_results) if len(sources) > 1 else 0
    product_id = sources[match_idx] if match_idx < len(sources) else (sources[0] if sources else None)

    if not product_id:
        return {"final_response": _NO_PRODUCT_MSG}

    # Step 1b — Fetch fresh price + stock from PostgreSQL (retry once on timeout)
    db_row = None
    for attempt in range(2):
        try:
            async with AsyncSessionLocal() as db:
                db_row = (
                    await db.execute(_STOCK_SQL, {"product_id": product_id})
                ).mappings().first()
            break
        except Exception as exc:
            log.warning("DB fetch attempt %d failed for product %s: %s", attempt + 1, product_id, exc)
            if attempt == 0:
                import asyncio
                await asyncio.sleep(1)  # brief pause before retry

    if db_row is None:
        return {
            "final_response": (
                "I had trouble looking up that product's details right now. "
                "Please try again in a moment — it might be a brief connection issue."
            )
        }

    stock_count = int(db_row["stock_count"])
    current_price = float(db_row["current_price"])
    brand = db_row["brand"] or ""
    name = db_row["name"] or ""
    # Avoid "Apple Apple MacBook..." when the product name already starts with the brand.
    brand_lower = brand.lower()
    if brand_lower in _RESELLER_TAGS or name.lower().startswith(brand_lower):
        display_name = name
    else:
        display_name = f"{brand} {name}"

    # Step 2 — check_stock_status; set recommend_alternatives_query so the graph
    # routes to recommend_alternatives instead of dropping straight to save_history
    if stock_count == 0:
        return {
            "final_response": _OUT_OF_STOCK_MSG,
            "recommend_alternatives_query": display_name,
        }

    # Step 3 — estimate delivery window based on stock level
    delivery_str, delivery_days = _delivery_estimate(stock_count)

    _USD_TO_INR = 83
    price_inr = current_price * _USD_TO_INR
    # Step 4 — Build add_to_cart payload
    description = (
        f"add {display_name} (₹{price_inr:,.0f}, "
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
