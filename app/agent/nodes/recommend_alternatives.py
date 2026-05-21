"""
recommend_alternatives — fires when handle_purchase_intent detects an out-of-stock product.

Performs a semantic search using the OOS product's display name as the query,
then generates a warm response suggesting in-stock alternatives. If the search
returns no results or the LLM call fails, the node returns an empty dict so the
graph falls through to save_history with the original OOS message intact.

Reads:  state.recommend_alternatives_query (OOS product display name)
Writes: state.final_response    (alternatives message, replaces generic OOS text)
        state.search_results    (top alternatives, for context)
        state.sources           (product_id list of alternatives shown)

Outgoing edge: → save_history
"""

import logging

from app.agent.prompts import RECOMMEND_ALTERNATIVES_PROMPT
from app.agent.state import ShopSenseState
from app.llm import call_llm
from app.search.embedder import embed
from app.search.qdrant_ops import search as qdrant_search

log = logging.getLogger(__name__)

_TOP_K = 5   # fetch 5; show top 3 in the prompt to keep response tight


async def recommend_alternatives(state: ShopSenseState) -> dict:
    product_name: str = state.get("recommend_alternatives_query") or ""
    if not product_name:
        return {}

    # ── Semantic search for similar products ──────────────────────────────────
    try:
        vector = await embed(product_name)
        results = await qdrant_search(vector, top_k=_TOP_K)
    except Exception as exc:
        log.warning("recommend_alternatives search failed for '%s': %s", product_name, exc)
        return {}

    # Filter to in-stock only and drop the OOS product itself (name match)
    alternatives = [
        r for r in results
        if r.stock_available and r.name.lower() not in product_name.lower()
    ][:3]

    if not alternatives:
        return {}

    alternatives_block = "\n".join(
        f"- {r.brand} {r.name}: ₹{r.current_price:,.0f}, rated {r.avg_rating}/5"
        for r in alternatives
    )

    prompt = RECOMMEND_ALTERNATIVES_PROMPT.format(
        product_name=product_name,
        alternatives=alternatives_block,
    )

    try:
        response = await call_llm(prompt, tier="generation", max_tokens=200, temperature=0.3)
    except Exception as exc:
        log.warning("recommend_alternatives LLM call failed: %s", exc)
        return {}

    return {
        "final_response": response,
        "search_results": [r.model_dump() for r in alternatives],
        "sources": [str(r.product_id) for r in alternatives],
    }
