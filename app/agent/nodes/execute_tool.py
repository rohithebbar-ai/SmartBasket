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

from app.agent.state import ShopSenseState
from app.mcp.client import mcp_client

log = logging.getLogger(__name__)


async def execute_tool(state: ShopSenseState) -> dict:
    tool = state.get("pending_tool", "")
    args = {**state.get("pending_tool_args", {}), "user_id": state.get("user_id", "")}

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

    if tool == "add_to_cart":
        return await _handle_add_to_cart(result, args)

    if tool == "set_price_alert":
        return _handle_set_price_alert(result, state)

    if tool == "submit_review":
        return _handle_submit_review(result)

    # Fallback — any other confirmed tool (future-proofing)
    return {
        "tool_result": result,
        "final_response": result.get("message", "Done."),
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

    cross_sell_text = await _fetch_cross_sell(args.get("product_id", ""))

    return {
        "tool_result": result,
        "cart_summary": result,
        "final_response": (
            f"{item_name} added to your cart. "
            f"Cart total: ₹{cart_total:,.0f}. "
            f"Ready to checkout?{cross_sell_text}"
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


async def _fetch_cross_sell(product_id: str) -> str:
    """Returns a formatted cross-sell sentence, or empty string on any failure."""
    if not product_id:
        return ""
    try:
        fbt = await mcp_client.call_tool(
            "get_frequently_bought_together",
            {"product_id": product_id, "limit": 2},
        )
        products = fbt.get("products") or []
        if not products:
            return ""
        names = ", ".join(p["name"] for p in products[:2])
        return f" Customers who bought this also got: {names}. Want to add any?"
    except Exception as exc:
        log.debug("Cross-sell fetch skipped: %s", exc)
        return ""
