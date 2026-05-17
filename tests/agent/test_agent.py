# Implement tests in Week 3 (Days 12–13) alongside the LangGraph agent.
#
# Test coverage targets:
#   - Full graph: PRODUCT_SEARCH intent routes to route_query → semantic_search → synthesise
#   - Full graph: ANALYTICAL intent routes to nl_to_sql_search, bypasses personalise
#   - Full graph: OUT_OF_SCOPE routes to refuse, no LLM call made
#   - Streaming: response chunks arrive in order via SSE
#   - Conversation memory: second turn includes first turn context from Redis
#   - PURCHASE_INTENT: routes to handle_purchase_intent, sets awaiting_confirmation=True
#   - await_confirmation: CONFIRM executes tool; DECLINE clears pending_tool
