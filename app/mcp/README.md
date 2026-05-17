# app/mcp/ — Phase 1 Tool Calling

MCP (Model Context Protocol) server for ShopSense agentic tool calling.

See **Section 19** of `ShopSense_Platform_Plan_v3.md` for full architecture.

## Planned structure

```
app/mcp/
├── server.py          # MCP server process, port 8006; exposes tool list via JSON-RPC
└── tools/
    ├── checkout.py    # Phase 1: 8 checkout flow tools (add_to_cart, process_payment, …)
    ├── products.py    # Phase 2: product intelligence tools
    ├── wishlist.py    # Phase 2: wishlist tools
    ├── orders.py      # Phase 3: tracking and post-purchase tools
    └── admin.py       # Phase 3: admin and analytics tools
```

## Build order

Phase 1 (Week 3, after LangGraph agent):
1. `server.py` — MCP server with list_tools endpoint
2. `tools/checkout.py` — 8 tools for the checkout flow
3. Wire into `app/agent/nodes/handle_purchase_intent.py`

## Tool classification

Every tool is either a **read** tool (executes immediately) or a **write** tool (requires
explicit user confirmation via `await_confirmation` node before execution).

`process_payment` is the most critical write tool. It only executes after an unambiguous
affirmative ("yes", "confirm", "place it") in the immediately preceding user message.
