"""
POST /api/chat — ShopSense agent SSE endpoint.

Request body:
  {
    "message": "laptop for video editing under 80k",
    "session_id": "abc123"          # optional; generated if omitted
  }

Response: text/event-stream
  Each SSE event is a JSON object.  Three event types:
    data: {"type": "token",    "content": "<partial text>"}
    data: {"type": "done",     "content": "<full response>", "sources": [...]}
    data: {"type": "interrupt","content": "<confirmation prompt>"}
    data: {"type": "error",    "content": "<message>"}

Auth:
  - Authenticated users (Bearer token) get personalised results.
  - Unauthenticated / guest users work without a token; user_id stays "".

Resume flow (when graph is paused at await_confirmation):
  - Client sends a follow-up POST with the same session_id.
  - Router detects a pending interrupt via graph.get_state().
  - Appends the new user message via graph.aupdate_state().
  - Resumes via graph.ainvoke(None, config).

Thread / config:
  - thread_id = session_id so MemorySaver (or RedisSaver) checkpoints per session.
"""

import json
import logging
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from langgraph.errors import GraphInterrupt
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.agent.graph import graph
from app.agent.state import ShopSenseState
from app.auth.dependencies import get_optional_user
from app.auth.models import User

log = logging.getLogger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str = Field(default="", description="Reuse across turns; generated if empty")
    catalogue: str = Field(default="fashion", description="Catalogue ID. Valid: fashion, electronics")
    image_b64: str = Field(default="", description="Base64-encoded image for visual search; empty for text-only queries")


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _stream_graph(
    message: str,
    session_id: str,
    user_id: str,
    catalogue: str = "fashion",
    image_b64: str = "",
) -> AsyncGenerator[str, None]:
    config = {"configurable": {"thread_id": session_id}}

    # ── Check for pending interrupt (resume path) ─────────────────────────────
    # existing.next is non-empty when the graph is paused mid-execution
    # (e.g. after interrupt() in await_confirmation). Checking .next is more
    # reliable than inspecting .tasks.interrupts across LangGraph versions.
    existing = graph.get_state(config)
    is_resume = bool(existing and existing.next)

    if is_resume:
        # Use Command(resume=message) — the correct way to resolve a LangGraph interrupt().
        # aupdate_state + astream(None) does NOT clear the interrupt flag, so interrupt()
        # fires again on the next node call, causing the confirmation loop.
        invoke_input = Command(resume=message)
    else:
        invoke_input: ShopSenseState = {
            "messages": [{"role": "user", "content": message}],
            "session_id": session_id,
            "user_id": user_id,
            "catalogue": catalogue,
            "visual_attributes": {"image_b64": image_b64} if image_b64 else {},
        }

    # ── Checkout context shortcut ─────────────────────────────────────────────
    # If the last assistant response ended with "Ready to checkout?" and the user
    # sends a bare yes/no, intercept BEFORE the intent classifier can misroute it.
    # Intent classifier (fast LLM) is unreliable for bare affirmations in a
    # shopping context — it sometimes picks PURCHASE_INTENT over CHECKOUT.
    if not is_resume:
        _pre = graph.get_state(config)
        _last_resp = (_pre.values.get("final_response") or "") if (_pre and _pre.values) else ""
        if "ready to checkout" in _last_resp.lower():
            _words = set(message.lower().strip().split())
            _yes_words = {"yes", "y", "yep", "yeah", "sure", "ok", "okay", "checkout",
                          "proceed", "buy", "confirm", "place", "ready"}
            _no_words  = {"no", "n", "nope", "nah", "cancel", "later", "skip", "not"}
            if _words & _yes_words:
                # Any yes-word in the message → rewrite to unambiguous checkout intent
                invoke_input = {
                    "messages": [{"role": "user", "content": "proceed to checkout please"}],
                    "session_id": session_id,
                    "user_id": user_id,
                }
            elif _words & _no_words:
                yield _sse({
                    "type": "done",
                    "content": "No problem! Your item is saved in the cart. Let me know if you'd like to add anything else or continue browsing.",
                    "sources": [],
                    "products": [],
                    "cart_action": None,
                })
                return

    # Snapshot pre-run checkpoint values to avoid streaming stale data from prior turns.
    initial_result_ids: set[str] = set()
    initial_final_response: str = ""
    initial_cross_sell: list = []
    pre_snap = graph.get_state(config)
    if pre_snap and pre_snap.values:
        initial_final_response = pre_snap.values.get("final_response", "") or ""
        initial_cross_sell = pre_snap.values.get("cross_sell_products") or []
        for r in (pre_snap.values.get("search_results") or []):
            rid = r.get("id") or r.get("product_id", "")
            if rid:
                initial_result_ids.add(str(rid))

    final_response = ""
    sources: list[str] = []
    product_previews: list[dict] = []
    cart_action: dict | None = None
    cart_cleared = False
    cross_sell_products: list[dict] = []
    search_ran_this_turn = False
    interrupted = False

    try:
        async for event in graph.astream(invoke_input, config, stream_mode="values"):
            new_response = event.get("final_response", "")
            # Skip if empty, unchanged, or matches the stale pre-run checkpoint value.
            # The frontend's done-event fallback handles the case where the new response
            # happens to equal initial_final_response (empty bubble fix in ChatPanel).
            if new_response and new_response != final_response and new_response != initial_final_response:
                delta = new_response[len(final_response):]
                if delta:
                    yield _sse({"type": "token", "content": delta})
                final_response = new_response
                sources = event.get("sources") or []
            if not cart_action and event.get("cart_action"):
                cart_action = event.get("cart_action")
            if not cart_cleared and event.get("cart_cleared"):
                cart_cleared = True
            if not cross_sell_products:
                new_cs = event.get("cross_sell_products") or []
                if new_cs and new_cs != initial_cross_sell:
                    cross_sell_products = new_cs

            # Only capture product cards if search_results actually changed this turn
            if not search_ran_this_turn:
                results = event.get("search_results") or []
                if results:
                    current_ids = {
                        str(r.get("id") or r.get("product_id", ""))
                        for r in results if r.get("id") or r.get("product_id")
                    }
                    if current_ids != initial_result_ids:
                        search_ran_this_turn = True
                        product_previews = [
                            {
                                "id": str(r.get("id") or r.get("product_id", "")),
                                "name": r.get("name", ""),
                                "brand": r.get("brand", ""),
                                "current_price": float(r.get("current_price", 0)) * 83,
                                "avg_rating": float(r.get("avg_rating", 0)),
                            }
                            for r in results[:5]
                            if r.get("id") or r.get("product_id")
                        ]

    except GraphInterrupt as exc:
        # Raised by graph.ainvoke() — not by astream(), but kept as a safety net.
        interrupted = True
        interrupt_content = str(exc.args[0]) if exc.args else "Please confirm the action."
        yield _sse({"type": "interrupt", "content": interrupt_content})
        return

    except Exception as exc:
        log.error("Graph execution error for session %s: %s", session_id, exc)
        yield _sse({"type": "error", "content": "Something went wrong. Please try again."})
        return

    # astream() does NOT raise GraphInterrupt — when interrupt() is called inside a node,
    # the stream simply ends and the graph is checkpointed. Detect this by checking whether
    # the graph is still waiting at await_confirmation after the loop.
    if not interrupted:
        post_state = graph.get_state(config)
        if post_state and post_state.next and "await_confirmation" in post_state.next:
            interrupted = True
            # Prefer the actual interrupt value stored in tasks (set by interrupt(description)
            # in await_confirmation). Fall back to final_response from propose_tool_action,
            # then to a generic prompt. This covers both checkout (no final_response set by
            # handle_checkout) and add-to-cart (propose_tool_action sets final_response).
            interrupt_content = "Please confirm the action."
            try:
                for task in (post_state.tasks or []):
                    for iv in (getattr(task, "interrupts", None) or []):
                        val = getattr(iv, "value", None)
                        if val and isinstance(val, str):
                            interrupt_content = val
                            break
            except Exception:
                pass
            interrupt_content = interrupt_content or final_response or "Please confirm the action."
            yield _sse({"type": "interrupt", "content": interrupt_content})
            return

    if not interrupted:
        yield _sse({"type": "done", "content": final_response, "sources": sources, "products": product_previews, "cart_action": cart_action, "cart_cleared": cart_cleared, "cross_sell": cross_sell_products})


@router.post("")
async def chat(
    body: ChatRequest,
    current_user: User | None = Depends(get_optional_user),
) -> StreamingResponse:
    session_id = body.session_id or str(uuid.uuid4())
    user_id = str(current_user.id) if current_user else ""

    return StreamingResponse(
        _stream_graph(body.message, session_id, user_id, body.catalogue, body.image_b64),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Session-Id": session_id,
        },
    )
