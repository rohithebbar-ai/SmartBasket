"""
refuse — terminal node for OUT_OF_SCOPE queries.

No LLM call. Sets a static response and returns immediately.
The graph routes directly to END after this node — history is not saved
because out-of-scope turns are not useful context for future retrieval.

Writes to state: final_response
"""

from app.agent.state import ShopSenseState

_REFUSAL_MESSAGE = (
    "I can help you find electronics — laptops, headphones, phones and more. "
    "What are you looking for?"
)


def refuse(state: ShopSenseState) -> dict:
    return {"final_response": _REFUSAL_MESSAGE}
