"""
save_history — final node before END (except for the refuse branch).

Appends the current turn (user message + assistant response) to the Redis
conversation history list at history:{session_id}.

Storage layout:
  key   : history:{session_id}          (Redis list)
  value : JSON-encoded list of dicts    [{"role": "user", "content": "..."}, ...]
  TTL   : 86400 seconds (24 h)

We store the full history list as a single JSON blob (not one list entry per
message) so load_context can read and trim it in one GET without LRANGE.
The blob is capped at _MAX_TURNS turns (20 messages) on every write so the
stored list never grows unbounded.

Writes to state: nothing (side-effect only node)
"""

import json
import logging

from app.agent.state import ShopSenseState
from app.redis_client import get_redis_client

log = logging.getLogger(__name__)

_HISTORY_KEY = "history:{session_id}"
_MAX_MESSAGES = 20   # 10 turns × 2 messages per turn
_TTL_SECONDS = 86400


async def save_history(state: ShopSenseState) -> dict:
    session_id = state.get("session_id", "")
    if not session_id:
        return {}

    messages: list[dict[str, str]] = state.get("messages", [])
    final_response = state.get("final_response", "")

    if not final_response:
        # Nothing was generated (e.g. early-exit branch) — skip the write.
        return {}

    # The last entry in messages is the user's current turn (set by the router
    # before graph.invoke). Append the assistant response as a new turn.
    current_user_message = messages[-1] if messages else None

    new_turns: list[dict[str, str]] = []
    if current_user_message and current_user_message.get("role") == "user":
        new_turns.append(current_user_message)
    new_turns.append({"role": "assistant", "content": final_response})

    redis = get_redis_client()
    key = f"history:{session_id}"

    try:
        raw = await redis.get(key)
        existing: list[dict[str, str]] = []
        if raw:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                existing = parsed

        updated = (existing + new_turns)[-_MAX_MESSAGES:]
        await redis.setex(key, _TTL_SECONDS, json.dumps(updated))
    except Exception as exc:
        # History write failure is non-fatal — the user still gets their response.
        log.warning("save_history failed for session %s: %s", session_id, exc)

    # Return the full updated messages list so LangSmith's Turns view shows the
    # complete conversation (user + assistant) rather than just the user message.
    return {"messages": (messages[:-1] if messages else []) + new_turns}
