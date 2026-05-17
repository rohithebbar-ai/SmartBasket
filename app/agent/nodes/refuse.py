from app.agent.state import ShopSenseState


async def refuse(state: ShopSenseState) -> ShopSenseState:
    """
    Returns a polite refusal for OUT_OF_SCOPE queries.

    No LLM call — response is a static template. Exits immediately.

    Reads:  state.intent (must be OUT_OF_SCOPE)
    Writes: state.final_response

    Outgoing edge: → END (does not save to history)
    """
    raise NotImplementedError("Implement in Week 3 — LangGraph agent phase (Days 12–13)")
