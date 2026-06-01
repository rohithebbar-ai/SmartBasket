"""
ShopSense LangGraph agent graph.

Node inventory
──────────────
Active nodes:
  load_context              — loads Redis history + PostgreSQL user profile
  classify_intent           — 10-intent classifier via call_llm (fast tier)
  route_query               — SEMANTIC | ANALYTICAL | HYBRID | REVIEW_SUMMARY router
  refuse                    — static out-of-scope response (sync, no LLM)
  save_history              — writes turn to Redis history:{session_id}
  await_confirmation        — interrupt()-based human-in-the-loop pause
  semantic_search           — filter extraction → embed → Qdrant → flashrank rerank
  hybrid_search             — RRF merge of SQL + vector rankings
  nl_to_sql_search          — NL-to-SQL via run_nl_to_sql(); validates before execute
  compare_products          — Qdrant lookup of named products → synthesise comparison
  personalise               — score boost by preferred_brands/categories/price/features
  synthesise                — Bedrock Sonnet generation tier; adapts to query_type
  handle_purchase_intent    — DB stock check → delivery estimate → pending_tool payload
  handle_checkout           — fetches saved card + live cart total → process_payment payload
  handle_order_status       — DB query for last 3 orders; formats status + items inline
  handle_post_purchase      — LLM detects REVIEW/RETURN; routes review to await_confirmation
  price_intelligence        — 7-day avg query + elevated-price insight in one pass
  propose_tool_action       — formats confirmation prompt; sets pending_tool_description
  execute_tool              — dispatches confirmed MCP tool; handles cross-sell + email
  recommend_alternatives    — OOS fallback: semantic search + alternatives response
  summarize_reviews         — aspect-aware review summary from real customer data

Remaining stubs (wishlist, admin chat — future):
  handle_wishlist, handle_admin

Checkpointer
────────────
MemorySaver for local dev. Switch to RedisSaver before production:
  from langgraph.checkpoint.redis import RedisSaver
  checkpointer = RedisSaver(redis_url=settings.redis_url)

LangSmith tracing activates automatically when LANGCHAIN_TRACING_V2=true
is set in the environment — no code changes needed.
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.nodes.await_confirmation import await_confirmation
from app.agent.nodes.supervisor import classify_intent
from app.agent.nodes.comparison import compare_products
from app.agent.nodes.execute_tool import execute_tool
from app.agent.nodes.handle_checkout import handle_checkout
from app.agent.nodes.handle_order_status import handle_order_status
from app.agent.nodes.handle_post_purchase import handle_post_purchase
from app.agent.nodes.handle_purchase_intent import handle_purchase_intent
from app.agent.nodes.hybrid_search import hybrid_search
from app.agent.nodes.load_context import load_context
from app.agent.nodes.text2sql import nl_to_sql_search
from app.agent.nodes.personalise import personalise
from app.agent.nodes.price_intelligence import price_intelligence
from app.agent.nodes.propose_action import propose_tool_action
from app.agent.nodes.recommend_alternatives import recommend_alternatives
from app.agent.nodes.refuse import refuse
from app.agent.nodes.route_query import route_query
from app.agent.nodes.save_history import save_history
from app.agent.nodes.product_discovery import semantic_search
from app.agent.nodes.summarize_reviews import summarize_reviews
from app.agent.nodes.synthesise import synthesise
from app.agent.nodes.visual_search import visual_search
from app.agent.state import ShopSenseState

# ── Remaining stubs (handle_wishlist, handle_admin — not yet implemented) ─────

async def _mock_handle_wishlist(_state: ShopSenseState) -> dict:
    return {"final_response": "Wishlist support is coming soon — stay tuned!"}

async def _mock_handle_admin(_state: ShopSenseState) -> dict:
    return {"final_response": "Admin analytics are available at /api/analytics/. Chat-based admin queries coming soon."}


# ── Routing functions (read state; return the node name to jump to) ───────────

def _route_intent(state: ShopSenseState) -> str:
    """Maps state["intent"] to the next node name."""
    intent = state.get("intent", "out_of_scope").lower()
    routes = {
        "product_search":   "route_query",
        "explain":          "route_query",
        "compare":          "compare_products",
        "purchase_intent":  "handle_purchase_intent",
        "checkout":         "handle_checkout",
        "order_status":     "handle_order_status",
        "post_purchase":    "handle_post_purchase",
        "wishlist_action":  "handle_wishlist",
        "admin_action":     "handle_admin",
        "visual":           "visual_search",
        "out_of_scope":     "refuse",
    }
    return routes.get(intent, "refuse")


def _route_query_type(state: ShopSenseState) -> str:
    """Maps state["query_type"] to the retrieval node."""
    qtype = state.get("query_type", "semantic").lower()
    routes = {
        "semantic":       "semantic_search",
        "analytical":     "nl_to_sql_search",
        "hybrid":         "hybrid_search",
        "review_summary": "summarize_reviews",
    }
    return routes.get(qtype, "semantic_search")


def _route_confirmation(state: ShopSenseState) -> str:
    """Maps state["user_decision"] to the post-confirmation node."""
    decision = state.get("user_decision", "ambiguous").lower()
    routes = {
        "confirm":   "execute_tool",
        "decline":   "save_history",
        "ambiguous": "await_confirmation",
    }
    return routes.get(decision, "await_confirmation")


# ── Graph construction ────────────────────────────────────────────────────────

def _build_graph() -> StateGraph:
    builder = StateGraph(ShopSenseState)

    # ── Real nodes ────────────────────────────────────────────────────────────
    builder.add_node("load_context",      load_context)
    builder.add_node("classify_intent",   classify_intent)
    builder.add_node("route_query",       route_query)
    builder.add_node("refuse",            refuse)
    builder.add_node("save_history",      save_history)
    builder.add_node("await_confirmation", await_confirmation)

    # ── Retrieval + synthesis nodes ───────────────────────────────────────────
    builder.add_node("semantic_search",         semantic_search)
    builder.add_node("nl_to_sql_search",        nl_to_sql_search)
    builder.add_node("hybrid_search",           hybrid_search)
    builder.add_node("personalise",             personalise)
    builder.add_node("synthesise",              synthesise)
    builder.add_node("compare_products",        compare_products)
    builder.add_node("summarize_reviews",       summarize_reviews)
    builder.add_node("recommend_alternatives",  recommend_alternatives)
    builder.add_node("visual_search",           visual_search)

    # ── Purchase intent + checkout + price intelligence nodes ─────────────────
    builder.add_node("handle_purchase_intent", handle_purchase_intent)
    builder.add_node("handle_checkout",        handle_checkout)
    builder.add_node("price_intelligence",     price_intelligence)
    builder.add_node("propose_tool_action",    propose_tool_action)   # sync node — fine in LangGraph

    # ── Execute tool (real) ───────────────────────────────────────────────────
    builder.add_node("execute_tool",          execute_tool)

    # ── Real nodes (order status + post-purchase) ─────────────────────────────
    builder.add_node("handle_order_status",   handle_order_status)
    builder.add_node("handle_post_purchase",  handle_post_purchase)

    # ── Remaining stubs (wishlist, admin) ─────────────────────────────────────
    builder.add_node("handle_wishlist",       _mock_handle_wishlist)
    builder.add_node("handle_admin",          _mock_handle_admin)

    # ── Entry point ───────────────────────────────────────────────────────────
    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "classify_intent")

    # ── Intent routing ────────────────────────────────────────────────────────
    builder.add_conditional_edges(
        "classify_intent",
        _route_intent,
        {
            "route_query":            "route_query",
            "compare_products":       "compare_products",
            "handle_purchase_intent": "handle_purchase_intent",
            "handle_checkout":        "handle_checkout",
            "handle_order_status":    "handle_order_status",
            "handle_post_purchase":   "handle_post_purchase",
            "handle_wishlist":        "handle_wishlist",
            "handle_admin":           "handle_admin",
            "visual_search":          "visual_search",
            "refuse":                 "refuse",
        },
    )

    # ── Query type routing ────────────────────────────────────────────────────
    builder.add_conditional_edges(
        "route_query",
        _route_query_type,
        {
            "semantic_search":   "semantic_search",
            "nl_to_sql_search":  "nl_to_sql_search",
            "hybrid_search":     "hybrid_search",
            "summarize_reviews": "summarize_reviews",
        },
    )

    # ── Retrieval → personalise / synthesise → save_history ──────────────────
    builder.add_edge("semantic_search",  "personalise")
    builder.add_edge("hybrid_search",    "personalise")
    builder.add_edge("personalise",      "synthesise")
    builder.add_edge("nl_to_sql_search", "synthesise")
    builder.add_edge("compare_products", "synthesise")  # bypasses personalise — deterministic
    builder.add_edge("synthesise",       "save_history")

    # ── Purchase intent flow ──────────────────────────────────────────────────
    # handle_purchase_intent has three paths:
    #   normal:    pending_tool set → price_intelligence → ...
    #   OOS:       recommend_alternatives_query set → recommend_alternatives → save_history
    #   not found: final_response set (no product_id) → save_history
    builder.add_conditional_edges(
        "handle_purchase_intent",
        lambda s: (
            "price_intelligence" if s.get("pending_tool")
            else "recommend_alternatives" if s.get("recommend_alternatives_query")
            else "save_history"
        ),
        {
            "price_intelligence":      "price_intelligence",
            "recommend_alternatives":  "recommend_alternatives",
            "save_history":            "save_history",
        },
    )

    # handle_checkout: pending_tool set → await_confirmation; error → save_history
    builder.add_conditional_edges(
        "handle_checkout",
        lambda s: "await_confirmation" if s.get("pending_tool") else "save_history",
        {"await_confirmation": "await_confirmation", "save_history": "save_history"},
    )

    # price_intelligence: surge shown → await_confirmation; normal price → propose_tool_action
    builder.add_conditional_edges(
        "price_intelligence",
        lambda s: "await_confirmation" if s.get("price_insight_shown") else "propose_tool_action",
        {"await_confirmation": "await_confirmation", "propose_tool_action": "propose_tool_action"},
    )
    builder.add_edge("propose_tool_action", "await_confirmation")

    # ── Direct-to-save_history paths ──────────────────────────────────────────
    builder.add_edge("handle_order_status",    "save_history")
    builder.add_edge("handle_wishlist",        "save_history")
    builder.add_edge("recommend_alternatives", "save_history")
    builder.add_edge("summarize_reviews",      "save_history")
    builder.add_edge("visual_search",          "save_history")

    # ── Confirmation flow ─────────────────────────────────────────────────────
    # handle_post_purchase: review with rating → await_confirmation;
    # return / no-rating / fallback → save_history (final_response already set).
    builder.add_conditional_edges(
        "handle_post_purchase",
        lambda s: "await_confirmation" if s.get("pending_tool") else "save_history",
        {"await_confirmation": "await_confirmation", "save_history": "save_history"},
    )
    # handle_admin stub always sets final_response → save_history
    builder.add_edge("handle_admin", "save_history")

    builder.add_conditional_edges(
        "await_confirmation",
        _route_confirmation,
        {
            "execute_tool":      "execute_tool",
            "save_history":      "save_history",
            "await_confirmation": "await_confirmation",
        },
    )

    builder.add_edge("execute_tool", "save_history")

    # ── Terminal edges ────────────────────────────────────────────────────────
    builder.add_edge("save_history", END)
    builder.add_edge("refuse",       END)

    return builder


# ── Compiled graph (module-level singleton) ───────────────────────────────────
# Import this in app/agent/router.py:
#   from app.agent.graph import graph

_checkpointer = MemorySaver()
graph = _build_graph().compile(checkpointer=_checkpointer)
