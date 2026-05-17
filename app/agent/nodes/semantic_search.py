from app.agent.state import ShopSenseState
from app.schemas.llm import FilterExtractionOutput
from app.schemas.search import ProductResult


async def semantic_search(state: ShopSenseState) -> ShopSenseState:
    """
    Runs the semantic retrieval path for PRODUCT_SEARCH / EXPLAIN queries.

    Steps:
      1. Extract structured filters from query via Bedrock Haiku (FILTER_EXTRACTION_PROMPT)
         — LLM response parsed into FilterExtractionOutput immediately
      2. Embed the rewritten query (FilterExtractionOutput.rewritten_query) via app.search.embedder
      3. Search Qdrant with metadata filters (brand, category, max_price)
      4. Rerank top-20 candidates to top-10 via app.search.reranker

    Reads:  state.messages (last user message)
    Writes: state.search_results (list[ProductResult], ranked by relevance_score descending)

    Outgoing edge: → personalise
    """
    raise NotImplementedError("Implement in Week 3 — LangGraph agent phase (Days 12–13)")
