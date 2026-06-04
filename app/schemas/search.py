"""
Pydantic models for search and retrieval results.

These replace list[dict] at all module boundaries so that:
- The agent state carries typed ProductResult objects, not raw dicts
- Analytics responses have a guaranteed shape before reaching the frontend
- Reranker and hybrid search inputs/outputs are type-checked at call sites
"""

from pydantic import BaseModel, Field


class ProductResult(BaseModel):
    """
    A single product returned by semantic search, NL-to-SQL, or hybrid search.
    Populated from Qdrant payload + PostgreSQL current_price overlay.
    Passed into state.search_results — never a raw dict.
    """
    product_id: str
    name: str
    brand: str
    category: str
    current_price: float
    avg_rating: float
    relevance_score: float = 0.0
    stock_available: bool = True
    image_url: str | None = None
    description: str = ""
    attributes: dict = Field(default_factory=dict)   # colour, pattern, garment_group, etc.
    sentiment_scores: dict = Field(default_factory=dict)
    top_praise: str | None = None
    top_complaint: str | None = None
    use_cases: list[str] = Field(default_factory=list)
    specs: dict = Field(default_factory=dict)        # legacy — kept for backwards compat


class SearchResponse(BaseModel):
    """Response shape for POST /api/search — returned to the React frontend."""
    query: str
    query_type: str                  # SEMANTIC | ANALYTICAL | HYBRID
    results: list[ProductResult]
    total: int


class AnalyticsResponse(BaseModel):
    """
    Response shape for POST /api/analytics/query — admin NL-to-SQL endpoint.
    sql is included so the admin dashboard can show the generated query in the audit log.
    results rows have arbitrary column names (varies per NL query) so list[dict] is correct here.
    """
    question: str
    sql: str
    results: list[dict]             # Raw SQL rows — column names vary per query
    insight: str                    # Bedrock Sonnet synthesis of the result set
    rows_returned: int


class NLToSQLResult(BaseModel):
    """
    Internal result of the NL-to-SQL engine — passed between nl_to_sql.py functions.
    Logged to nl_sql_audit table after every execution attempt.
    """
    natural_language_query: str
    generated_sql: str
    rows_returned: int = 0
    validation_passed: bool = False
    retry_count: int = 0
    rows: list[dict] = Field(default_factory=list)
