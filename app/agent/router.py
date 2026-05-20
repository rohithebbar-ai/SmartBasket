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


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _stream_graph(
    message: str,
    session_id: str,
    user_id: str,
) -> AsyncGenerator[str, None]:
    config = {"configurable": {"thread_id": session_id}}

    # ── Check for pending interrupt (resume path) ─────────────────────────────
    existing = graph.get_state(config)
    is_resume = bool(
        existing
        and existing.tasks
        and any(getattr(t, "interrupts", None) for t in existing.tasks)
    )

    if is_resume:
        # Append the user's reply to state so await_confirmation can read it
        await graph.aupdate_state(
            config,
            {"messages": [{"role": "user", "content": message}]},
        )
        invoke_input = None
    else:
        invoke_input: ShopSenseState = {
            "messages": [{"role": "user", "content": message}],
            "session_id": session_id,
            "user_id": user_id,
        }

    final_response = ""
    sources: list[str] = []
    interrupted = False

    try:
        async for event in graph.astream(invoke_input, config, stream_mode="values"):
            new_response = event.get("final_response", "")
            if new_response and new_response != final_response:
                delta = new_response[len(final_response):]
                if delta:
                    yield _sse({"type": "token", "content": delta})
                final_response = new_response
                sources = event.get("sources") or []

    except GraphInterrupt as exc:
        interrupted = True
        interrupt_content = str(exc.args[0]) if exc.args else "Please confirm the action."
        yield _sse({"type": "interrupt", "content": interrupt_content})
        return

    except Exception as exc:
        log.error("Graph execution error for session %s: %s", session_id, exc)
        yield _sse({"type": "error", "content": "Something went wrong. Please try again."})
        return

    if not interrupted:
        yield _sse({"type": "done", "content": final_response, "sources": sources})


@router.post("")
async def chat(
    body: ChatRequest,
    current_user: User | None = Depends(get_optional_user),
) -> StreamingResponse:
    session_id = body.session_id or str(uuid.uuid4())
    user_id = str(current_user.id) if current_user else ""

    return StreamingResponse(
        _stream_graph(body.message, session_id, user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Session-Id": session_id,
        },
    )
