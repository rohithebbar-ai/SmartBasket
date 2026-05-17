from app.agent.state import ShopSenseState
from app.schemas.llm import IntentOutput


async def classify_intent(state: ShopSenseState) -> ShopSenseState:
    """
    Classifies the user's latest message into one of five intents.

    Model: Bedrock Haiku (~200ms). Reads INTENT_CLASSIFICATION_PROMPT from prompts.py.
    LLM response is parsed immediately into IntentOutput — ValidationError fires at the
    boundary if the model returns an unexpected intent string.

    Reads:  state.messages (last user message)
    Writes: state.intent (str — the .intent field from IntentOutput)

    Intent values and outgoing edges:
      PRODUCT_SEARCH  → route_query
      EXPLAIN         → route_query
      COMPARE         → compare_products
      OUT_OF_SCOPE    → refuse
      PURCHASE_INTENT → handle_purchase_intent (Phase 1, Section 19)
    """
    raise NotImplementedError("Implement in Week 3 — LangGraph agent phase (Days 12–13)")
