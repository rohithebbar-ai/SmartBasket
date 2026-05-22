"""
execute_tool — dispatches the confirmed MCP tool and builds the final response.

Reads:  state.pending_tool          — tool name confirmed by the user
        state.pending_tool_args     — args built by handle_purchase_intent / handle_checkout
        state.user_id               — injected into every tool call server-side
        state.user_email            — used for process_payment email receipt

Writes: state.tool_result           — raw JSON response from the MCP tool
        state.final_response        — human-readable outcome shown to the user
        state.order_id              — set on successful process_payment
        state.cart_summary          — updated on successful add_to_cart
        state.price_alert_set       — True on successful set_price_alert

Cross-sell: after a successful add_to_cart, calls get_frequently_bought_together
inline and appends up to 2 product names to the response. Failures are silenced
(non-critical path).

Confirmation email: after a successful process_payment, calls send_confirmation_email
automatically — no separate user confirmation gate for this write tool.
"""

import logging
import uuid

from app.agent.state import ShopSenseState
from app.database import AsyncSessionLocal
from app.mcp.client import mcp_client
from app.orders import service as order_service
from app.redis_client import get_redis_client

log = logging.getLogger(__name__)


async def execute_tool(state: ShopSenseState) -> dict:
    tool = state.get("pending_tool", "")
    args = {**state.get("pending_tool_args", {}), "user_id": state.get("user_id", "")}

    # add_to_cart: guest → localStorage-only response; authenticated → MCP first,
    # then direct Redis write if MCP fails (so checkout can always find items in Redis).
    if tool == "add_to_cart":
        if not args.get("user_id"):
            return _handle_guest_add_to_cart(state)
        try:
            result = await mcp_client.call_tool(tool, args)
            return await _handle_add_to_cart(result, args)
        except Exception as exc:
            log.warning("add_to_cart MCP failed (%s) — writing directly to Redis", exc)
            return await _handle_auth_cart_fallback(state, args)

    try:
        result = await mcp_client.call_tool(tool, args)
    except Exception as exc:
        log.error("execute_tool: MCP call failed for tool=%s: %s", tool, exc)
        return {
            "tool_result": {"error": str(exc)},
            "final_response": "Something went wrong. Please try again.",
        }

    if tool == "process_payment":
        return await _handle_process_payment(result, state)

    if tool == "set_price_alert":
        return _handle_set_price_alert(result, state)

    if tool == "submit_review":
        return _handle_submit_review(result)

    # Fallback — any other confirmed tool (future-proofing)
    return {
        "tool_result": result,
        "final_response": result.get("message", "Done."),
    }


_USD_TO_INR = 83


def _cart_action_payload(tool_args: dict) -> dict:
    """Build the cart_action dict that the SSE router forwards to the frontend."""
    return {
        "id": tool_args.get("product_id", ""),
        "name": tool_args.get("product_name", ""),
        "brand": "",
        "current_price": round(float(tool_args.get("current_price", 0)) * _USD_TO_INR),
        "quantity": int(tool_args.get("quantity", 1)),
    }


async def _handle_auth_cart_fallback(state: ShopSenseState, args: dict) -> dict:
    """Authenticated add_to_cart when MCP fails: write directly to Redis + Postgres."""
    tool_args = state.get("pending_tool_args", {})
    product_name = tool_args.get("product_name", "Item")
    price_inr = round(float(tool_args.get("current_price", 0)) * _USD_TO_INR)
    delivery_str = tool_args.get("delivery_estimate", "3–5 business days")
    user_id_str = args.get("user_id", "")
    product_id_str = tool_args.get("product_id", "")

    cart_total = price_inr
    try:
        redis = get_redis_client()
        async with AsyncSessionLocal() as db:
            cart = await order_service.add_to_cart(
                redis, db,
                user_id=uuid.UUID(user_id_str),
                product_id=uuid.UUID(product_id_str),
                qty=int(tool_args.get("quantity", 1)),
            )
        cart_total = round(float(cart.total) * _USD_TO_INR)
        log.info("Direct Redis cart write succeeded for user %s", user_id_str)
    except Exception as exc:
        log.warning("Direct Redis cart write also failed (%s) — item only in localStorage", exc)

    cross_sell = await _fetch_cross_sell(product_id_str)
    return {
        "tool_result": {"success": True, "fallback": True},
        "cart_summary": {"success": True},
        "cart_action": _cart_action_payload(tool_args),
        "cross_sell_products": cross_sell,
        "final_response": (
            f"{product_name} (₹{price_inr:,.0f}) added to your cart! "
            f"Cart total: ₹{cart_total:,.0f}. "
            f"Estimated delivery: {delivery_str}. "
            f"Ready to checkout?"
        ),
    }


def _handle_guest_add_to_cart(state: ShopSenseState) -> dict:
    """Handle add_to_cart for unauthenticated (guest) users.
    The actual cart is managed in the frontend's localStorage; we just return
    the item payload so the SSE router can signal the frontend to add it."""
    tool_args = state.get("pending_tool_args", {})
    product_name = tool_args.get("product_name", "Item")
    price_inr = round(float(tool_args.get("current_price", 0)) * _USD_TO_INR)
    delivery_str = tool_args.get("delivery_estimate", "3–5 business days")
    return {
        "tool_result": {"success": True, "guest": True},
        "cart_summary": {"success": True},
        "cart_action": _cart_action_payload(tool_args),
        "final_response": (
            f"{product_name} (₹{price_inr:,.0f}) added to your cart! "
            f"Estimated delivery: {delivery_str}. "
            f"Ready to checkout?"
        ),
    }


# ── Per-tool handlers ─────────────────────────────────────────────────────────

async def _handle_process_payment(result: dict, state: ShopSenseState) -> dict:
    if not result.get("success"):
        return {
            "tool_result": result,
            "final_response": "Payment could not be processed. Please try again.",
        }

    order_id: str = result["order_id"]
    user_email: str = state.get("user_email", "")

    # Auto-send confirmation email — classified as write tool but runs automatically
    # after a successful payment (no additional confirmation gate needed).
    try:
        await mcp_client.call_tool(
            "send_confirmation_email",
            {"order_id": order_id, "user_email": user_email},
        )
    except Exception as exc:
        log.warning("Confirmation email failed for order %s: %s", order_id, exc)

    return {
        "tool_result": result,
        "order_id": order_id,
        "cart_cleared": True,
        # Reset search context so the next purchase intent starts fresh instead
        # of reusing the just-bought product's sources/filters.
        "sources": [],
        "search_results": [],
        "extracted_filters": {},
        "budget_overrun_results": [],
        "cross_sell_products": [],
        "final_response": (
            f"Payment successful! Order #{order_id[:8].upper()} placed. "
            f"Confirmation sent to {user_email or 'your email'}."
        ),
    }


async def _handle_add_to_cart(result: dict, args: dict) -> dict:
    if not result.get("success"):
        return {
            "tool_result": result,
            "final_response": "Couldn't add that item to your cart. Please try again.",
        }

    item_name = result.get("item_added") or args.get("product_name", "Item")
    cart_total = result.get("cart_total", 0)

    cross_sell = await _fetch_cross_sell(args.get("product_id", ""))

    return {
        "tool_result": result,
        "cart_summary": result,
        "cart_action": _cart_action_payload(args),
        "cross_sell_products": cross_sell,
        "final_response": (
            f"{item_name} added to your cart. "
            f"Cart total: ₹{cart_total:,.0f}. "
            f"Ready to checkout?"
        ),
    }


def _handle_set_price_alert(result: dict, state: ShopSenseState) -> dict:
    if not result.get("alert_set"):
        return {
            "tool_result": result,
            "final_response": "Couldn't set the price alert. Please try again.",
        }

    notify_at = result.get("notify_at") or state.get("user_email", "you")
    target_price = result.get("target_price", 0)

    return {
        "tool_result": result,
        "price_alert_set": True,
        "final_response": (
            f"Alert set! I'll email {notify_at} "
            f"when the price drops to ₹{target_price:,.0f} or below."
        ),
    }


# ── Cross-sell helper ─────────────────────────────────────────────────────────

def _handle_submit_review(result: dict) -> dict:
    if not result.get("saved"):
        return {
            "tool_result": result,
            "final_response": "Something went wrong submitting your review. Please try again.",
        }
    review_id = result.get("review_id", "")
    short_id = review_id[:8].upper() if review_id else ""
    return {
        "tool_result": result,
        "final_response": (
            f"Your review has been submitted — thank you! "
            + (f"(Reference: #{short_id})" if short_id else "")
        ),
    }


async def _fetch_cross_sell(product_id: str) -> list[dict]:
    """Returns list of cross-sell product dicts for frontend cards, empty list on failure."""
    if not product_id:
        return []
    try:
        fbt = await mcp_client.call_tool(
            "get_frequently_bought_together",
            {"product_id": product_id, "limit": 2},
        )
        products = fbt.get("products") or []
        return [
            {
                "product_id": p.get("product_id", ""),
                "name": p.get("name", ""),
                "current_price": round(float(p.get("current_price", 0)) * _USD_TO_INR),
                "avg_rating": float(p.get("avg_rating", 0)),
            }
            for p in products[:2]
            if p.get("name")
        ]
    except Exception as exc:
        log.debug("Cross-sell fetch skipped: %s", exc)
        return []
