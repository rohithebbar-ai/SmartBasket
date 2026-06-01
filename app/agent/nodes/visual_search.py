"""
visual_search — VISUAL intent path (image-based product discovery).

Future flow: image bytes in state.visual_attributes → Bedrock Claude Sonnet vision
→ extract colour/pattern/style attributes → embed description → Qdrant search.

Currently a graceful stub: returns a prompt asking the user to describe what they
want while visual search is not yet live. Outgoing edge: → save_history.
"""

from app.agent.state import ShopSenseState


async def visual_search(state: ShopSenseState) -> dict:
    return {
        "final_response": (
            "Visual search is coming soon! In the meantime, describe what you're looking for "
            "— colour, style, occasion — and I'll find the best matches for you."
        )
    }
