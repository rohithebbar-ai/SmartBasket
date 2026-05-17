from app.agent.state import ShopSenseState
from app.schemas.llm import QueryRouterOutput


async def route_query(state: ShopSenseState) -> ShopSenseState:
    """
    Classifies the query into a retrieval strategy.

    Delegates to app.search.query_router.classify_query() — the same classifier
    used by the direct /search endpoint, keeping routing logic in one place.
    classify_query() returns QueryRouterOutput; this node writes only the .type field
    to state.query_type.

    Model: Bedrock Haiku (~150ms).
    Reads:  state.messages (last user message), state.intent
    Writes: state.query_type (str — one of SEMANTIC | ANALYTICAL | HYBRID)

    Query type values and outgoing edges:
      SEMANTIC    → semantic_search
      ANALYTICAL  → nl_to_sql_search
      HYBRID      → hybrid_search
    """
    raise NotImplementedError("Implement in Week 3 — LangGraph agent phase (Days 12–13)")
