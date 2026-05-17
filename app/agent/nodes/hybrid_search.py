from app.agent.state import ShopSenseState


async def hybrid_search(state: ShopSenseState) -> ShopSenseState:
    """
    Runs the hybrid retrieval path for queries needing both structured filters
    and semantic ranking.

    Delegates to app.search.hybrid_search.hybrid_search().
    SQL constrains the candidate set; vector search ranks within it.

    Reads:  state.messages (last user message)
    Writes: state.search_results (filtered by SQL, ranked by vector similarity)

    Outgoing edge: → personalise
    """
    raise NotImplementedError("Implement in Week 3 — LangGraph agent phase (Days 12–13)")
