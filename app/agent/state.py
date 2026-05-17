from typing import Any
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage

from app.schemas.search import ProductResult


class ShopSenseState(TypedDict):
    # ── Conversation ──────────────────────────────────────────────────────────
    messages: list[BaseMessage]       # Full conversation history (last 10 turns from Redis)
    session_id: str
    user_id: str

    # ── Routing ───────────────────────────────────────────────────────────────
    intent: str       # PRODUCT_SEARCH | COMPARE | EXPLAIN | OUT_OF_SCOPE | PURCHASE_INTENT
    query_type: str   # SEMANTIC | ANALYTICAL | HYBRID

    # ── Retrieval results ─────────────────────────────────────────────────────
    # Typed as ProductResult so Pydantic catches any schema mismatch at the
    # retrieval boundary — not silently passed as a raw dict to synthesis.
    search_results: list[ProductResult]

    # SQL results have arbitrary column names per query — list[dict] is correct here.
    sql_results: list[dict[str, Any]]
    generated_sql: str                     # For audit/debugging; logged to nl_sql_audit

    # ── Personalisation ───────────────────────────────────────────────────────
    user_preferences: dict[str, Any]       # From users module; read-only inside agent

    # ── Output ────────────────────────────────────────────────────────────────
    final_response: str
    sources: list[str]   # Product IDs or table names cited in the response

    # ── Tool calling (Phase 1 — checkout flow, Section 19) ────────────────────
    pending_tool: str                 # Name of the write tool awaiting confirmation
    pending_tool_args: dict[str, Any] # Arguments for the pending tool
    pending_tool_description: str     # Human-readable description shown to the user before confirmation
    tool_result: dict[str, Any]       # Result returned by the last executed tool
    awaiting_confirmation: bool       # True when graph is paused at await_confirmation node
    confirmation_context: str         # What the confirmation is for (displayed to user)
    order_id: str                     # Set after successful process_payment tool call
    cart_summary: dict[str, Any]      # Current cart state; passed as context to synthesis
