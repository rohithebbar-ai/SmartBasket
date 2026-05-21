"""
route_query — third node in the graph (runs after classify_intent).

Delegates to the existing classify_query() function from app/search/query_router
so routing logic lives in exactly one place. The agent graph uses the
history-aware QUERY_TYPE_ROUTER_PROMPT; the stateless /search endpoint uses
QUERY_ROUTER_PROMPT. classify_query() accepts an optional history string to
switch between the two.

Only runs for PRODUCT_SEARCH and EXPLAIN intents — other intents skip this node
via the conditional edge in graph.py.

Defaults to SEMANTIC on any error — safe fallback (vector search can handle
most queries; it just won't use SQL).

Writes to state: query_type
"""

import logging

from app.agent.state import ShopSenseState
from app.search.query_router import classify_query

log = logging.getLogger(__name__)

_DEFAULT_QUERY_TYPE = "SEMANTIC"

# Keywords that signal the user wants a review summary rather than product search.
# Checked before the LLM router so no extra API call is needed for clear cases.
_REVIEW_KEYWORDS = {
    "review", "reviews", "what do people think", "what do customers",
    "what do users", "customer opinion", "customer feedback", "user feedback",
    "pros and cons", "complaints about", "is it worth", "worth buying",
    "is it good", "would you recommend", "what are people saying",
    "how good is", "thoughts on", "honest opinion",
}


def _is_review_query(message: str) -> bool:
    msg = message.lower()
    return any(kw in msg for kw in _REVIEW_KEYWORDS)


async def route_query(state: ShopSenseState) -> dict:
    messages: list[dict[str, str]] = state.get("messages", [])

    if not messages:
        return {"query_type": _DEFAULT_QUERY_TYPE}

    current_message = messages[-1].get("content", "")

    # Review-summary queries are intercepted before the LLM router —
    # keyword matching is fast and accurate enough for this specific pattern.
    if _is_review_query(current_message):
        log.info("Route query: review summary detected — skipping LLM router")
        return {"query_type": "REVIEW_SUMMARY"}

    # Build a short history string from the prior 4 messages (2 turns).
    prior = messages[:-1][-4:]
    history = (
        "\n".join(f"{m['role'].capitalize()}: {m['content']}" for m in prior)
        if prior
        else ""
    )

    try:
        result = await classify_query(current_message, history=history)
        query_type = result.type
    except Exception as exc:
        log.warning("Query type routing failed (%s) — defaulting to %s", exc, _DEFAULT_QUERY_TYPE)
        query_type = _DEFAULT_QUERY_TYPE

    return {"query_type": query_type}
