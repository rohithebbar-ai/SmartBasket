# LangGraph graph definition — implement in Week 3 (Days 12–13):
#
# Graph structure:
#   START → load_context → classify_intent
#   classify_intent → [PRODUCT_SEARCH/EXPLAIN] → route_query
#   classify_intent → [COMPARE]                → compare_products
#   classify_intent → [OUT_OF_SCOPE]            → refuse → END
#   classify_intent → [PURCHASE_INTENT]         → handle_purchase_intent
#   route_query     → [SEMANTIC]                → semantic_search → personalise → synthesise
#   route_query     → [ANALYTICAL]              → nl_to_sql_search              → synthesise
#   route_query     → [HYBRID]                  → hybrid_search   → personalise → synthesise
#   synthesise      → save_history → END
#   handle_purchase_intent → propose_tool_action → await_confirmation → ...
#
# All nodes traced via LangSmith automatically when LANGCHAIN_TRACING_V2=true.
