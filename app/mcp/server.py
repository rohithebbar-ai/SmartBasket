"""
MCP server — mounted inside the main FastAPI app at /mcp (no separate process).

Exposes:
  GET  /mcp/tools          — tool registry (name + type for every tool)
  POST /mcp/tools/<name>   — individual tool endpoints (see tool files)

Mounting in the main app avoids spawning a second process and its associated
RAM overhead. The MCPClient (app/mcp/client.py) calls localhost:8000/mcp/...
so from the agent's perspective the interface is identical to a remote server.
"""

from fastapi import APIRouter

from app.mcp.tools.checkout import router as cart_router
from app.mcp.tools.notification_tools import router as notification_router
from app.mcp.tools.payment_tools import router as payment_router

router = APIRouter()

# ── Tool registry ─────────────────────────────────────────────────────────────
# "read"  tools execute immediately — no await_confirmation gate.
# "write" tools always require an explicit user confirmation before execute_tool runs.

_TOOL_REGISTRY = [
    {"name": "check_stock_status",              "type": "read"},
    {"name": "get_delivery_estimate",           "type": "read"},
    {"name": "get_frequently_bought_together",  "type": "read"},
    {"name": "get_saved_payment_methods",       "type": "read"},
    {"name": "calculate_order_total",           "type": "read"},
    {"name": "add_to_cart",                     "type": "write"},
    {"name": "set_price_alert",                 "type": "write"},
    {"name": "process_payment",                 "type": "write"},
    {"name": "send_confirmation_email",         "type": "write"},  # auto-executes after payment
    {"name": "submit_review",                   "type": "write"},  # stub — Day 15
]


@router.get("/tools")
async def list_tools() -> list[dict]:
    """Returns the full tool registry. Used by MCPClient.list_tools()."""
    return _TOOL_REGISTRY


# ── Mount tool routers under /tools ──────────────────────────────────────────
router.include_router(cart_router,         prefix="/tools")
router.include_router(payment_router,      prefix="/tools")
router.include_router(notification_router, prefix="/tools")
