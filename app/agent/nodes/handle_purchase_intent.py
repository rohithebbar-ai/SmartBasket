from app.agent.state import ShopSenseState


async def handle_purchase_intent(state: ShopSenseState) -> ShopSenseState:
    """
    Entry point for the checkout tool-calling flow (Phase 1, Section 19).

    Orchestrates the full checkout sequence:
      1. check_stock_status tool (read — executes immediately)
      2. get_delivery_estimate tool (read — executes immediately)
      3. Presents stock + delivery info → proposes add_to_cart
      4. On confirm: add_to_cart tool (write — requires await_confirmation)
      5. get_frequently_bought_together tool (read — cross-sell opportunity)
      6. Routes to payment flow or loops on cross-sell

    Reads:  state.messages (purchase intent message), state.user_id
    Writes: state.pending_tool, state.pending_tool_args,
            state.pending_tool_description, state.awaiting_confirmation,
            state.cart_summary

    Outgoing edges:
      → propose_tool_action (when a write tool needs confirmation)
      → synthesise (when cross-sell response is ready)
    """
    raise NotImplementedError("Implement in Phase 1 tool calling — Section 19.7")
