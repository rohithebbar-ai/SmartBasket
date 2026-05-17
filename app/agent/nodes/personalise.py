from app.agent.state import ShopSenseState
from app.schemas.search import ProductResult


async def personalise(state: ShopSenseState) -> ShopSenseState:
    """
    Re-ranks search results based on the user's stored preference profile.

    Reads state.user_preferences (preferred_brands, typical_price_range, feature_priorities)
    and boosts products that match the user's history. Does not call any LLM.

    state.search_results is list[ProductResult] — update relevance_score in place and
    re-sort descending. Never replace ProductResult objects; mutate scores only.

    Reads:  state.search_results (list[ProductResult]), state.user_preferences
    Writes: state.search_results (list[ProductResult], re-ranked by boosted relevance_score)

    Outgoing edge: → synthesise
    """
    raise NotImplementedError("Implement in Week 3 — LangGraph agent phase (Days 12–13)")
