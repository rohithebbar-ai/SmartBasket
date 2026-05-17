"""
Hybrid search — implement in Week 2 (Day 11).

Combines SQL filtering and vector ranking for queries that need both:
  Step 1: execute_query() (NL-to-SQL) → set of product_ids matching structured constraints
  Step 2: Qdrant semantic search with pre_filter_ids=sql_product_ids → ranks within SQL set
  Step 3: rerank() → top-10 by cross-encoder score

The correct architecture: SQL CONSTRAINS candidates, vector search RANKS within them.
This is not two separate result lists that need reconciling — one filters the other.

Public interface:
    hybrid_search(query: str, filters: FilterExtractionOutput) -> list[ProductResult]
"""

from app.schemas.llm import FilterExtractionOutput
from app.schemas.search import ProductResult


async def hybrid_search(query: str, filters: FilterExtractionOutput) -> list[ProductResult]:
    """
    Returns ProductResult list ranked by semantic relevance within SQL-filtered candidates.
    Accepts FilterExtractionOutput (not a raw dict) so the filter shape is validated before use.
    """
    raise NotImplementedError("Implement in Week 2 — hybrid search (Day 11)")
