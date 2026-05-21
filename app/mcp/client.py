"""
MCP client — thin async HTTP client for calling MCP tool endpoints.

The execute_tool node uses this to call tools via HTTP rather than importing
tool functions directly. This keeps the tool-calling interface consistent
whether the MCP server is co-located (same process, different router) or
moved to a separate service later.

Usage:
    from app.mcp.client import mcp_client
    result = await mcp_client.call_tool("add_to_cart", {"user_id": ..., ...})
    tools  = await mcp_client.list_tools()
"""

import logging

import httpx

from app.config import settings

log = logging.getLogger(__name__)

# Timeout for tool calls — process_payment may take up to 8s (Stripe roundtrip)
_DEFAULT_TIMEOUT = 10.0
_PAYMENT_TIMEOUT = 15.0

_SLOW_TOOLS = {"process_payment"}


class MCPClient:
    def __init__(self) -> None:
        self._base_url = settings.mcp_server_url  # http://localhost:8000/mcp
        self._client = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)

    async def call_tool(self, tool_name: str, args: dict) -> dict:
        """
        POST to /tools/{tool_name} with args as the JSON body.
        Returns the parsed JSON response.
        Raises httpx.HTTPStatusError on 4xx/5xx from the tool endpoint.
        """
        timeout = _PAYMENT_TIMEOUT if tool_name in _SLOW_TOOLS else _DEFAULT_TIMEOUT
        url = f"{self._base_url}/tools/{tool_name}"

        try:
            response = await self._client.post(url, json=args, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            log.error(
                "MCP tool %s returned %s: %s",
                tool_name, exc.response.status_code, exc.response.text[:200],
            )
            raise
        except httpx.RequestError as exc:
            log.error("MCP tool %s network error: %s", tool_name, exc)
            raise

    async def list_tools(self) -> list[dict]:
        """GET /tools — returns the tool registry."""
        response = await self._client.get(f"{self._base_url}/tools")
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        await self._client.aclose()


# Module-level singleton — import this everywhere.
mcp_client = MCPClient()
