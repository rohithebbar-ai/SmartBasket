"""
propose_tool_action — formats a write tool as a human-readable confirmation prompt.

Reads state.pending_tool and state.pending_tool_args to build the message.
Sets state.final_response (shown in the chat) and state.pending_tool_description
(used by await_confirmation's interrupt() call so the pause payload matches
what the user saw).

Supported tools:
  add_to_cart       — product name + price
  process_payment   — total + card last4
  set_price_alert   — email + target price
  cancel_order      — order_id prefix

Unknown tools get a generic "shall I proceed with {tool}?" fallback.

Sync — no LLM, no DB, no await needed.

Reads:  state.pending_tool, state.pending_tool_args
Writes: state.final_response (str — confirmation question shown to user)
        state.pending_tool_description (str — interrupt payload for await_confirmation)
        state.awaiting_confirmation (bool — True)

Outgoing edge: → await_confirmation
"""

from app.agent.state import ShopSenseState

_USD_TO_INR = 83


def propose_tool_action(state: ShopSenseState) -> dict:
    tool = state.get("pending_tool", "")
    args = state.get("pending_tool_args", {})

    if tool == "add_to_cart":
        product_name = args.get("product_name", "this product")
        price_inr = round(float(args.get("current_price", 0)) * _USD_TO_INR)
        msg = (
            f"I'll add {product_name} (₹{price_inr:,.0f}) to your cart. Shall I proceed?"
        )

    elif tool == "process_payment":
        total = args.get("total", 0)
        delivery = args.get("delivery_fee", 0)
        last4 = args.get("card_last4", "****")
        msg = (
            f"Your total is ₹{total:,.0f} (incl. GST + ₹{delivery:,.0f} delivery). "
            f"Charge your Visa ending in {last4}?"
        )

    elif tool == "set_price_alert":
        email = args.get("user_email") or state.get("user_email") or "your registered email"
        target = args.get("target_price", 0)
        msg = (
            f"I'll notify you at {email} when the price drops "
            f"to ₹{target:,.0f} or below. Shall I set that up?"
        )

    elif tool == "cancel_order":
        order_prefix = str(args.get("order_id", ""))[:8].upper()
        msg = f"Are you sure you want to cancel order #{order_prefix}?"

    else:
        desc = state.get("pending_tool_description") or f"proceed with {tool}"
        msg = f"Shall I {desc}?"

    return {
        "final_response": msg,
        "pending_tool_description": msg,   # await_confirmation interrupts with this
        "confirmation_context": msg,       # shown alongside the confirm prompt
        "awaiting_confirmation": True,
    }
