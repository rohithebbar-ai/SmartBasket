from app.agent.state import ShopSenseState


async def propose_tool_action(state: ShopSenseState) -> ShopSenseState:
    """
    Formats a write tool action as a human-readable description and presents it
    to the user before execution. The graph pauses here until the user responds.

    Example output for add_to_cart:
      "I'll add the Dell XPS 15 (₹78,750) to your cart. Shall I proceed?"

    Example output for process_payment:
      "Your total is ₹78,750 (incl. GST + ₹150 delivery). Charge your Visa ending in 4242?"

    Reads:  state.pending_tool, state.pending_tool_args, state.pending_tool_description
    Writes: state.final_response (the confirmation prompt shown to the user),
            state.awaiting_confirmation = True

    Outgoing edge: → await_confirmation
    """
    raise NotImplementedError("Implement in Phase 1 tool calling — Section 19.7")
