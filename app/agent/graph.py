"""
ShopSense LangGraph agent graph.

Node inventory
──────────────
Real nodes (fully implemented):
  load_context        — loads Redis history + PostgreSQL user profile
  classify_intent     — 10-intent classifier via call_llm (fast tier)
  route_query         — SEMANTIC | ANALYTICAL | HYBRID via classify_query()
  refuse              — static out-of-scope response (sync, no LLM)
  save_history        — writes turn to Redis history:{session_id}
  await_confirmation  — interrupt()-based human-in-the-loop pause

Mock stubs (return placeholder final_response; replace in later days):
  semantic_search, nl_to_sql_search, hybrid_search,
  compare_products, handle_purchase_intent,
  handle_order_status, handle_post_purchase,
  handle_wishlist, handle_admin,
  personalise, synthesise, execute_tool

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
from app.agent.nodes.classify_intent import classify_intent
from app.agent.nodes.load_context import load_context
from app.agent.nodes.refuse import refuse
from app.agent.nodes.route_query import route_query
from app.agent.nodes.save_history import save_history
from app.agent.state import ShopSenseState

# ── Mock stubs ────────────────────────────────────────────────────────────────
# Each returns a placeholder final_response. Replace with real implementations
# as the corresponding day's work is completed.

async def _mock_semantic_search(state: ShopSenseState) -> dict:
    return {"final_response": "[semantic_search] stub — not yet implemented"}

async def _mock_nl_to_sql_search(state: ShopSenseState) -> dict:
    return {"final_response": "[nl_to_sql_search] stub — not yet implemented"}

async def _mock_hybrid_search(state: ShopSenseState) -> dict:
    return {"final_response": "[hybrid_search] stub — not yet implemented"}

async def _mock_personalise(state: ShopSenseState) -> dict:
    # Passthrough — search_results already in state; synthesise will read them.
    return {}

async def _mock_synthesise(state: ShopSenseState) -> dict:
    return {"final_response": "[synthesise] stub — not yet implemented"}

async def _mock_compare_products(state: ShopSenseState) -> dict:
    return {"final_response": "[compare_products] stub — not yet implemented"}

async def _mock_handle_purchase_intent(state: ShopSenseState) -> dict:
    return {"final_response": "[handle_purchase_intent] stub — not yet implemented"}

async def _mock_handle_order_status(state: ShopSenseState) -> dict:
    return {"final_response": "[handle_order_status] stub — not yet implemented"}

async def _mock_handle_post_purchase(state: ShopSenseState) -> dict:
    # Must set pending_tool_description so await_confirmation has something to interrupt with.
    return {
        "pending_tool_description": "[handle_post_purchase] stub — action pending confirmation",
        "confirmation_context": "post_purchase action",
    }

async def _mock_handle_wishlist(state: ShopSenseState) -> dict:
    return {"final_response": "[handle_wishlist] stub — not yet implemented"}

async def _mock_handle_admin(state: ShopSenseState) -> dict:
    # Must set pending_tool_description so await_confirmation has something to interrupt with.
    return {
        "pending_tool_description": "[handle_admin] stub — action pending confirmation",
        "confirmation_context": "admin action",
    }

async def _mock_execute_tool(state: ShopSenseState) -> dict:
    return {"final_response": "[execute_tool] stub — tool executed (mock)"}


# ── Routing functions (read state; return the node name to jump to) ───────────

def _route_intent(state: ShopSenseState) -> str:
    """Maps state["intent"] to the next node name."""
    intent = state.get("intent", "out_of_scope").lower()
    routes = {
        "product_search":   "route_query",
        "explain":          "route_query",
        "compare":          "compare_products",
        "purchase_intent":  "handle_purchase_intent",
        "checkout":         "await_confirmation",
        "order_status":     "handle_order_status",
        "post_purchase":    "handle_post_purchase",
        "wishlist_action":  "handle_wishlist",
        "admin_action":     "handle_admin",
        "out_of_scope":     "refuse",
    }
    return routes.get(intent, "refuse")


def _route_query_type(state: ShopSenseState) -> str:
    """Maps state["query_type"] to the retrieval node."""
    qtype = state.get("query_type", "semantic").lower()
    routes = {
        "semantic":    "semantic_search",
        "analytical":  "nl_to_sql_search",
        "hybrid":      "hybrid_search",
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

    # ── Mock nodes ────────────────────────────────────────────────────────────
    builder.add_node("semantic_search",       _mock_semantic_search)
    builder.add_node("nl_to_sql_search",      _mock_nl_to_sql_search)
    builder.add_node("hybrid_search",         _mock_hybrid_search)
    builder.add_node("personalise",           _mock_personalise)
    builder.add_node("synthesise",            _mock_synthesise)
    builder.add_node("compare_products",      _mock_compare_products)
    builder.add_node("handle_purchase_intent", _mock_handle_purchase_intent)
    builder.add_node("handle_order_status",   _mock_handle_order_status)
    builder.add_node("handle_post_purchase",  _mock_handle_post_purchase)
    builder.add_node("handle_wishlist",       _mock_handle_wishlist)
    builder.add_node("handle_admin",          _mock_handle_admin)
    builder.add_node("execute_tool",          _mock_execute_tool)

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
            "await_confirmation":     "await_confirmation",
            "handle_order_status":    "handle_order_status",
            "handle_post_purchase":   "handle_post_purchase",
            "handle_wishlist":        "handle_wishlist",
            "handle_admin":           "handle_admin",
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
        },
    )

    # ── Retrieval → personalise / synthesise → save_history ──────────────────
    builder.add_edge("semantic_search",  "personalise")
    builder.add_edge("hybrid_search",    "personalise")
    builder.add_edge("personalise",      "synthesise")
    builder.add_edge("nl_to_sql_search", "synthesise")
    builder.add_edge("synthesise",       "save_history")

    # ── Direct-to-save_history paths ──────────────────────────────────────────
    builder.add_edge("compare_products",       "save_history")
    builder.add_edge("handle_purchase_intent", "save_history")
    builder.add_edge("handle_order_status",    "save_history")
    builder.add_edge("handle_wishlist",        "save_history")

    # ── Confirmation flow ─────────────────────────────────────────────────────
    # handle_post_purchase and handle_admin set up a pending tool action, then
    # await_confirmation pauses for the user's reply.
    builder.add_edge("handle_post_purchase", "await_confirmation")
    builder.add_edge("handle_admin",         "await_confirmation")

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
