"""
handle_checkout — entry point for the CHECKOUT intent.

Fetches live cart total via MCP, then sets up the process_payment write tool
payload for await_confirmation.

In development mode (no STRIPE_SECRET_KEY set), skips the saved-card requirement
and uses a mock payment method so the flow can be tested end-to-end without Stripe.

Reads:  state.user_id    — passed to every MCP read call
        state.user_email — surfaced in the confirmation message

Writes: state.pending_tool             ("process_payment")
        state.pending_tool_args        ({payment_method_id, user_id})
        state.pending_tool_description — formatted bill + card summary shown
                                         before the user confirms payment
        state.final_response           ← error path only (guest / empty cart / no card)

Outgoing edges:
  → await_confirmation  (normal — pending_tool set)
  → save_history        (error — guest user, empty cart, or no payment method)
"""

import logging

from app.agent.state import ShopSenseState
from app.config import settings
from app.mcp.client import mcp_client

log = logging.getLogger(__name__)

_GUEST_MSG = (
    "Please sign in to complete your purchase! "
    "Your cart items are saved — click 'Sign In' at the top of the page, "
    "then come back and say 'checkout' to continue."
)
_NO_CARD_MSG = (
    "You don't have a saved payment method yet. "
    "Please add a card in your account settings and try again."
)
_EMPTY_CART_MSG = (
    "Your cart appears empty on my end. "
    "If you added items before signing in, those were saved locally but not to your account. "
    "Just tell me what you'd like — e.g. 'Add the HP Elitebook to my cart' — and I'll add it to your account so you can checkout."
)
_MCP_ERROR_MSG = (
    "Something went wrong while preparing your checkout. Please try again in a moment."
)


async def handle_checkout(state: ShopSenseState) -> dict:
    user_id = state.get("user_id", "")

    # Guest guard — cart and payment both require an authenticated user
    if not user_id:
        return {"final_response": _GUEST_MSG}

    dev_mode = not settings.stripe_secret_key

    # Fetch live cart total (always needed)
    try:
        total_resp = await mcp_client.call_tool("calculate_order_total", {"user_id": user_id})
    except Exception as exc:
        # 400 = cart is empty on the server (common when items were added as guest)
        exc_str = str(exc).lower()
        if "400" in exc_str or "cart is empty" in exc_str:
            return {"final_response": _EMPTY_CART_MSG}
        log.error("handle_checkout: calculate_order_total failed for user %s: %s", user_id, exc)
        return {"final_response": _MCP_ERROR_MSG}

    items = total_resp.get("items") or []
    if not items:
        return {"final_response": _EMPTY_CART_MSG}

    # Dev mode: skip saved-card requirement; process_payment will mock the charge
    if dev_mode:
        payment_method_id = "mock_pm_dev"
        card_label = "Test payment (development mode — no real charge)"
    else:
        try:
            methods_resp = await mcp_client.call_tool(
                "get_saved_payment_methods", {"user_id": user_id}
            )
        except Exception as exc:
            log.error("handle_checkout: get_saved_payment_methods failed: %s", exc)
            return {"final_response": _MCP_ERROR_MSG}

        methods = methods_resp.get("methods") or []
        if not methods:
            return {"final_response": _NO_CARD_MSG}

        card = methods[0]
        payment_method_id = card["payment_method_id"]
        card_label = f"{card['type'].title()} ending in {card['last4']} (exp {card['expires']})"

    total = total_resp.get("total", 0.0)
    subtotal = total_resp.get("subtotal", 0.0)
    gst = total_resp.get("gst", 0.0)
    delivery_fee = total_resp.get("delivery_fee", 0.0)

    item_lines = "\n".join(
        f"  • {it['name']} × {it['qty']}  ₹{it['subtotal']:,.0f}"
        for it in items
    )

    description = (
        f"Here's your order summary:\n\n"
        f"{item_lines}\n\n"
        f"  Subtotal:   ₹{subtotal:,.0f}\n"
        f"  GST (18%):  ₹{gst:,.0f}\n"
        f"  Delivery:   {'Free' if delivery_fee == 0 else f'₹{delivery_fee:,.0f}'}\n"
        f"  ─────────────────────\n"
        f"  Total:      ₹{total:,.0f}\n\n"
        f"Pay with: {card_label}\n\n"
        f"Confirm payment?"
    )

    return {
        "pending_tool": "process_payment",
        "pending_tool_args": {
            "payment_method_id": payment_method_id,
        },
        "pending_tool_description": description,
        "confirmation_context": description,
    }
