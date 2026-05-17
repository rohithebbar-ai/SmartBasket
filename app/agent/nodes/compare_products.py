from app.agent.state import ShopSenseState


async def compare_products(state: ShopSenseState) -> ShopSenseState:
    """
    Fetches 2–3 specific products and builds a structured comparison.

    Extracts product identifiers from the user message, fetches full specs and
    sentiment scores from PostgreSQL, produces a side-by-side comparison payload.

    Reads:  state.messages (last user message)
    Writes: state.search_results (2–3 product dicts with full spec comparison)

    Outgoing edge: → synthesise (bypasses personalise — comparison is deterministic)
    """
    raise NotImplementedError("Implement in Week 3 — LangGraph agent phase (Days 12–13)")
