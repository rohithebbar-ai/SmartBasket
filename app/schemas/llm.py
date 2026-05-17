"""
Pydantic models for all LLM output boundaries.

Every response from Bedrock is parsed into one of these models immediately —
before the value touches any other part of the system. Pydantic's Literal types
catch LLM hallucinations at the boundary: if the model returns "SEMANTIC_SEARCH"
instead of "SEMANTIC", a ValidationError is raised and the retry loop fires,
rather than the bad value propagating silently through state.

Usage pattern in every node and service:
    raw = llm.invoke(prompt)
    output = QueryRouterOutput.model_validate_json(raw.content)
    # output.type is now guaranteed to be "SEMANTIC" | "ANALYTICAL" | "HYBRID"
"""

from typing import Literal

from pydantic import BaseModel, Field


class QueryRouterOutput(BaseModel):
    """Output of the query type router (QUERY_ROUTER_PROMPT, Haiku ~150ms)."""
    type: Literal["SEMANTIC", "ANALYTICAL", "HYBRID"]
    reasoning: str


class IntentOutput(BaseModel):
    """Output of the intent classifier (INTENT_CLASSIFICATION_PROMPT, Haiku ~200ms)."""
    intent: Literal["PRODUCT_SEARCH", "COMPARE", "EXPLAIN", "OUT_OF_SCOPE", "PURCHASE_INTENT"]
    reasoning: str


class FilterExtractionOutput(BaseModel):
    """
    Output of filter extraction for the SEMANTIC path (FILTER_EXTRACTION_PROMPT, Haiku ~300ms).
    All fields are optional — null means the filter was not mentioned in the query.
    """
    max_price: float | None = None
    min_price: float | None = None
    brand: str | None = None
    category: str | None = None
    use_case: str | None = None
    features: list[str] = Field(default_factory=list)
    rewritten_query: str   # Cleaned, expanded version of the query for embedding


class ConfirmationOutput(BaseModel):
    """
    Output of the confirmation classifier inside await_confirmation node.
    AMBIGUOUS must never be treated as CONFIRM — the node re-asks for clarification.
    """
    decision: Literal["CONFIRM", "DECLINE", "AMBIGUOUS"]
    reasoning: str


class AspectSentimentOutput(BaseModel):
    """
    Output of batch aspect sentiment extraction (ASPECT_SENTIMENT_PROMPT, Sonnet).
    Scores are 1.0–5.0. Used during data ingestion only — not at query time.
    Results are written to the reviews table sentiment columns.
    """
    battery_sentiment: float = Field(ge=1.0, le=5.0)
    display_sentiment: float = Field(ge=1.0, le=5.0)
    build_quality_sentiment: float = Field(ge=1.0, le=5.0)
    value_sentiment: float = Field(ge=1.0, le=5.0)
    performance_sentiment: float = Field(ge=1.0, le=5.0)
    top_complaint: str | None = None
    top_praise: str | None = None
