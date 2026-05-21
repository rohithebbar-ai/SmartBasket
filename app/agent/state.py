"""
ShopSense agent state — passed through every node in the LangGraph graph.

Design notes:
  - messages is List[Dict] with {"role": "user"|"assistant", "content": str} so the
    state serialises cleanly to Redis without LangChain BaseMessage overhead.
  - search_results is List[Dict] rather than List[ProductResult] so the state
    round-trips through JSON (LangGraph checkpointer) without custom serialisers.
  - total=False makes every field optional — nodes only write the fields they own;
    unset fields stay absent rather than holding None sentinels.
  - price_trend_pct, price_insight_shown, price_alert_set, user_decision are
    Price-intelligence fields — populated by check_price_trend and
    consumed by present_price_insight / the WAIT branch.
"""

from __future__ import annotations

from typing import Any
from typing_extensions import TypedDict


class ShopSenseState(TypedDict, total=False):
    # ── Conversation ──────────────────────────────────────────────────────────
    # Each dict: {"role": "user" | "assistant", "content": str}
    # Loaded from Redis history (last 10 turns) before the graph runs.
    messages: list[dict[str, str]]
    session_id: str
    user_id: str
    user_email: str                        # For confirmation emails / Stripe receipts

    # ── Routing ───────────────────────────────────────────────────────────────
    # classify_intent writes intent; route_query writes query_type.
    intent: str      # PRODUCT_SEARCH | COMPARE | EXPLAIN | PURCHASE_INTENT
                     # CHECKOUT | ORDER_STATUS | POST_PURCHASE
                     # WISHLIST_ACTION | ADMIN_ACTION | OUT_OF_SCOPE
    query_type: str  # SEMANTIC | ANALYTICAL | HYBRID

    # ── Retrieval results ─────────────────────────────────────────────────────
    # List[Dict] so the state round-trips cleanly through the JSON checkpointer.
    # Each dict mirrors ProductResult fields: product_id, name, brand, category,
    # current_price, avg_rating, relevance_score, stock_available, specs, etc.
    search_results: list[dict[str, Any]]

    # SQL results have arbitrary column names per query — list[dict] is correct.
    sql_results: list[dict[str, Any]]
    generated_sql: str                     # Logged to nl_sql_audit; shown in debug mode

    # ── Personalisation ───────────────────────────────────────────────────────
    # Read from users.user_preferences at load_context; never written by agent.
    user_preferences: dict[str, Any]

    # ── Output ────────────────────────────────────────────────────────────────
    final_response: str
    sources: list[str]     # product_id strings or table names cited in the response

    # ── Tool calling — checkout flow ──────────────────────────────────────────
    pending_tool: str                  # Name of the write tool awaiting user confirmation
    pending_tool_args: dict[str, Any]  # Arguments that will be passed to the tool
    pending_tool_description: str      # Human-readable description shown before confirmation
    tool_result: dict[str, Any]        # Result returned by the last executed MCP tool

    awaiting_confirmation: bool        # True when graph is paused at await_confirmation
    confirmation_context: str          # Context string shown alongside the confirm prompt

    order_id: str                      # Set after successful process_payment call
    cart_summary: dict[str, Any]       # Current cart state; passed as context to synthesise

    # ── Price intelligence — proactive insight ────────────────────────────────
    # Populated by price_intelligence node after PURCHASE_INTENT is detected.
    price_trend_pct: float             # % above/below recent price average (negative = below)
    price_insight_shown: bool          # True once the price insight has been surfaced
    price_alert_set: bool              # True if user asked to be alerted on price drop

    # ── Out-of-stock fallback ─────────────────────────────────────────────────
    # Set by handle_purchase_intent when a product is OOS. The recommend_alternatives
    # node reads this to find similar in-stock products.
    recommend_alternatives_query: str  # Display name of the OOS product

    # ── Search context for synthesis ──────────────────────────────────────────
    # extracted_filters: FilterExtractionOutput fields; gives synthesise access to
    #   max_price and use_case so it can mention budget and add domain-specific tips.
    # budget_overrun_results: products just above max_price (up to 30% over);
    #   synthesise surfaces these with an exact ₹ premium and asks if the user
    #   would consider stretching — the same proactive behaviour as Amazon Rufus.
    extracted_filters: dict[str, Any]
    budget_overrun_results: list[dict[str, Any]]

    # ── Human-in-the-loop decision ────────────────────────────────────────────
    # Written by await_confirmation after classifying the user's reply.
    user_decision: str                 # CONFIRM | DECLINE | AMBIGUOUS
