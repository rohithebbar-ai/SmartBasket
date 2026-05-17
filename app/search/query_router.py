"""
Query type router — implement in Week 2 (Day 9).

Classifies every incoming query as SEMANTIC, ANALYTICAL, or HYBRID before
routing to the correct retrieval path.

Public interface:
    classify_query(query: str) -> QueryRouterOutput

Uses Bedrock Haiku (~150ms) with QUERY_ROUTER_PROMPT from agent/prompts.py.
The LLM response is parsed immediately into QueryRouterOutput — if the model
returns an unexpected type string, Pydantic raises ValidationError at the
boundary rather than propagating a bad value through state.

Called by:
  - app/search/router.py  (direct /api/search endpoint)
  - app/agent/nodes/route_query.py  (inside LangGraph)
"""

from app.schemas.llm import QueryRouterOutput


async def classify_query(query: str) -> QueryRouterOutput:
    """
    Returns QueryRouterOutput with type SEMANTIC | ANALYTICAL | HYBRID.
    Raises ValidationError if LLM returns an unexpected value — caller retries.
    """
    raise NotImplementedError("Implement in Week 2 — query router (Day 9)")
