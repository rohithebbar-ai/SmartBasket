"""
handle_checkout — entry point for the CHECKOUT intent.

Fetches the user's saved payment methods and live cart total via MCP read tools,
then sets up the process_payment write tool payload for await_confirmation.

Reads:  state.user_id    — passed to every MCP read call
        state.user_email — surfaced in the confirmation message

Writes: state.pending_tool             ("process_payment")
        state.pending_tool_args        ({payment_method_id, user_id})
        state.pending_tool_description — formatted bill + card summary shown
                                         before the user confirms payment
        state.final_response           ← error path only (empty cart / no card)

Outgoing edges:
  → await_confirmation  (normal — pending_tool set)
  → save_history        (error — empty cart or no payment method on file)
"""

import logging

from app.agent.state import ShopSenseState
from app.mcp.client import mcp_client

log = logging.getLogger(__name__)

_NO_CARD_MSG = (
    "You don't have a saved payment method yet. "
    "Please add a card in your account settings and try again."
)
_EMPTY_CART_MSG = (
    "Your cart is empty. Find something you'd like and add it to your cart first."
)
_MCP_ERROR_MSG = (
    "Something went wrong while preparing your checkout. Please try again in a moment."
)


async def handle_checkout(state: ShopSenseState) -> dict:
    user_id = state.get("user_id", "")

    # Step 1 — fetch saved payment methods and live cart total in parallel
    import asyncio
    try:
        methods_resp, total_resp = await asyncio.gather(
            mcp_client.call_tool("get_saved_payment_methods", {"user_id": user_id}),
            mcp_client.call_tool("calculate_order_total", {"user_id": user_id}),
        )
    except Exception as exc:
        log.error("handle_checkout MCP fetch failed for user %s: %s", user_id, exc)
        return {"final_response": _MCP_ERROR_MSG}

    # Step 2 — validate payment method
    methods = methods_resp.get("methods") or []
    if not methods:
        return {"final_response": _NO_CARD_MSG}

    # Step 3 — validate cart
    items = total_resp.get("items") or []
    if not items:
        return {"final_response": _EMPTY_CART_MSG}

    # Step 4 — pick the default card (MCP returns default first)
    card = methods[0]
    payment_method_id: str = card["payment_method_id"]
    card_label = f"{card['type'].title()} ending in {card['last4']} (exp {card['expires']})"

    # Step 5 — format the confirmation message
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
