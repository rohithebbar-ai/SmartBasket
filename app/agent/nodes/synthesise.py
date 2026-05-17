from app.agent.state import ShopSenseState
from app.schemas.search import ProductResult


async def synthesise(state: ShopSenseState) -> ShopSenseState:
    """
    Generates the final streaming response using Bedrock Sonnet.

    Reads state.query_type and adapts tone accordingly:
      SEMANTIC    → warm, conversational product recommendation
      ANALYTICAL  → clear data presentation with a brief insight
      HYBRID      → leads with the data finding, then explains the products

    For SEMANTIC/HYBRID: reads state.search_results (list[ProductResult]).
    For ANALYTICAL: reads state.sql_results (list[dict]) and state.generated_sql.
    Sources written to state.sources are product_id strings from ProductResult.product_id.

    Streams tokens via FastAPI SSE. Full LangSmith trace on every call.

    Reads:  state.search_results (list[ProductResult]) | state.sql_results (list[dict]),
            state.query_type, state.messages, state.user_preferences
    Writes: state.final_response (str), state.sources (list[str])

    Outgoing edge: → save_history → END
    """
    raise NotImplementedError("Implement in Week 3 — LangGraph agent phase (Days 12–13)")
