from app.agent.state import ShopSenseState


async def hybrid_search(state: ShopSenseState) -> ShopSenseState:
    """
    Runs the hybrid retrieval path for queries needing both structured filters
    and semantic ranking.

    Delegates to app.search.hybrid_search.hybrid_search().
    Uses RRF (Reciprocal Rank Fusion) to merge SQL and vector rankings —
    rrf_score = 1/(60 + sql_rank) + 1/(60 + vector_rank).

    Reads:  state.messages (last user message)
    Writes: state.search_results (RRF-merged results, sorted by rrf_score desc)

    Outgoing edge: → personalise
    """
    raise NotImplementedError("Implement in Week 3 — LangGraph agent phase (Days 12–13)")
