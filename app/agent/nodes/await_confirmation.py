from app.agent.state import ShopSenseState


async def await_confirmation(state: ShopSenseState) -> ShopSenseState:
    """
    Classifies the user's response to a pending tool action as CONFIRM, DECLINE,
    or AMBIGUOUS. The graph never executes a write tool on an ambiguous response.

    CONFIRM  → execute the pending tool (routes to handle_purchase_intent to continue flow)
    DECLINE  → cancel; clear pending_tool state; route to synthesise with cancellation message
    AMBIGUOUS → route back to propose_tool_action to re-ask for clarification

    Only a clear affirmative in the immediately preceding message counts as CONFIRM:
    "yes", "confirm", "place it", "go ahead", "do it" — not silence, not partial agreement.

    Reads:  state.messages (user's latest response), state.pending_tool,
            state.awaiting_confirmation
    Writes: state.awaiting_confirmation = False on CONFIRM or DECLINE,
            state.pending_tool = "" on DECLINE

    Outgoing edges:
      CONFIRM   → handle_purchase_intent (continues checkout flow)
      DECLINE   → synthesise (cancellation message)
      AMBIGUOUS → propose_tool_action (re-asks)
    """
    raise NotImplementedError("Implement in Phase 1 tool calling — Section 19.7")
