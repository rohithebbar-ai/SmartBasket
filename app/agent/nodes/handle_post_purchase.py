"""
handle_post_purchase — handles review submission and return requests.

Uses a fast LLM call to classify the user's intent as REVIEW, RETURN, or OTHER,
and to extract a numeric rating and review text when present.

REVIEW + rating present:
  Sets pending_tool = "submit_review" with product_id, order_id, rating, review_text.
  Graph routes to await_confirmation → execute_tool.

REVIEW + no rating yet:
  Returns a response asking the user for their rating (1–5) and feedback.
  Routes to save_history.

RETURN:
  Returns a polite support message. Routes to save_history.

OTHER / fallback:
  Returns a general help message. Routes to save_history.

Reads:  state.user_id, state.messages[-1], state.pending_review_products
Writes: state.pending_tool, state.pending_tool_args, state.pending_tool_description
        OR state.final_response (non-review paths)

Outgoing edges (conditional on pending_tool):
  pending_tool set  → await_confirmation
  pending_tool empty → save_history
"""

import json
import logging

from sqlalchemy import text

from app.agent.nodes.handle_order_status import _STATUS_LABEL  # reuse label map
from app.agent.prompts import POST_PURCHASE_PROMPT
from app.agent.state import ShopSenseState
from app.database import AsyncSessionLocal
from app.llm import call_llm

log = logging.getLogger(__name__)

_RETURN_RESPONSE = (
    "I've noted your return request. Our support team will reach out to your "
    "registered email within 24 hours with return instructions and a prepaid "
    "shipping label.\n\n"
    "You can also track your return at support.shopsense.app."
)

_NO_RATING_RESPONSE = (
    "Happy to submit a review for you! Please share:\n"
    "  1. Your rating (1–5 stars)\n"
    "  2. A few words about your experience\n\n"
    "I'll post it as soon as you give the go-ahead."
)

_FALLBACK_RESPONSE = (
    "I can help you with returns, refunds, or submitting a review for a recent "
    "purchase. What would you like to do?"
)

_NO_ORDER_RESPONSE = (
    "I couldn't find a recent delivered order to attach your review to. "
    "Please check your order history and try again."
)

# Finds the most recent delivered order that contains a specific product.
_ORDER_WITH_PRODUCT_SQL = text("""
    SELECT o.id::text
    FROM orders o
    WHERE o.user_id = :uid
      AND o.status = 'delivered'
      AND o.items @> jsonb_build_array(jsonb_build_object('product_id', :pid))
    ORDER BY o.created_at DESC
    LIMIT 1
""")

# Fallback: most recent delivered order for this user (any product).
_LATEST_DELIVERED_SQL = text("""
    SELECT id::text, items
    FROM orders
    WHERE user_id = :uid AND status = 'delivered'
    ORDER BY created_at DESC
    LIMIT 1
""")


async def _find_order_for_review(
    user_id: str, preferred_product_id: str | None
) -> tuple[str | None, str | None]:
    """
    Returns (order_id, product_id) for the most relevant delivered order.
    Prefers an order that contains preferred_product_id; falls back to the
    most recent delivered order and takes its first item's product_id.
    """
    try:
        async with AsyncSessionLocal() as db:
            if preferred_product_id:
                row = (
                    await db.execute(
                        _ORDER_WITH_PRODUCT_SQL,
                        {"uid": user_id, "pid": preferred_product_id},
                    )
                ).mappings().first()
                if row:
                    return row["id"], preferred_product_id

            row = (
                await db.execute(_LATEST_DELIVERED_SQL, {"uid": user_id})
            ).mappings().first()
            if row:
                items = row["items"] or []
                first_pid = items[0].get("product_id") if items else None
                return row["id"], first_pid

            return None, None
    except Exception as exc:
        log.warning("Order lookup failed for user %s: %s", user_id, exc)
        return None, None


async def handle_post_purchase(state: ShopSenseState) -> dict:
    user_id  = state.get("user_id", "")
    messages = state.get("messages", [])
    message  = messages[-1].get("content", "") if messages else ""

    if not user_id:
        return {"final_response": "Please log in to manage your orders."}

    # ── Classify intent + extract rating via fast LLM ─────────────────────────
    try:
        raw = await call_llm(
            POST_PURCHASE_PROMPT.format(message=message),
            tier="fast",
            max_tokens=120,
            temperature=0.0,
        )
        parsed = json.loads(raw)
    except Exception as exc:
        log.warning("Post-purchase LLM classification failed: %s", exc)
        return {"final_response": _FALLBACK_RESPONSE}

    action      = parsed.get("action", "OTHER")
    rating      = parsed.get("rating")        # int 1–5 or None
    review_text = parsed.get("review_text", "")

    # ── RETURN path ───────────────────────────────────────────────────────────
    if action == "RETURN":
        return {"final_response": _RETURN_RESPONSE}

    # ── REVIEW path ───────────────────────────────────────────────────────────
    if action == "REVIEW":
        if not rating:
            return {"final_response": _NO_RATING_RESPONSE}

        # Find the order and product to review
        pending    = state.get("pending_review_products") or []
        product_id = pending[0] if pending else None

        order_id, resolved_product_id = await _find_order_for_review(user_id, product_id)
        if not order_id:
            return {"final_response": _NO_ORDER_RESPONSE}

        # Build the confirmation prompt
        excerpt = (
            f': "{review_text[:60]}..."' if len(review_text) > 60
            else f': "{review_text}"'     if review_text
            else ""
        )
        description = f"submit your {rating}-star review{excerpt}"

        return {
            "pending_tool": "submit_review",
            "pending_tool_args": {
                "product_id":  resolved_product_id or "",
                "order_id":    order_id,
                "rating":      rating,
                "review_text": review_text,
            },
            "pending_tool_description": description,
            "confirmation_context": description,
        }

    # ── OTHER / fallback ──────────────────────────────────────────────────────
    return {"final_response": _FALLBACK_RESPONSE}
