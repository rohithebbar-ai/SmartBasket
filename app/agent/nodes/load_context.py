"""
load_context — first node in every graph run.

Reads two external sources before the rest of the graph executes:
  1. Redis  → history:{session_id}  — last N turns of conversation
  2. PostgreSQL → users + user_preferences tables — email and preference profile

Both reads are best-effort: if Redis or the DB is unavailable the graph continues
with empty context rather than crashing. Missing context degrades quality, not
correctness — the downstream nodes are written to handle empty messages/prefs.

Writes to state: messages, user_email, user_preferences
"""

import json
import logging
import uuid

from sqlalchemy import select

from app.agent.state import ShopSenseState
from app.auth.models import User
from app.database import AsyncSessionLocal
from app.redis_client import get_redis_client
from app.users.models import UserPreferences

log = logging.getLogger(__name__)

# Keep at most this many messages in state (each turn = 1 user + 1 assistant message).
_MAX_HISTORY_MESSAGES = 20  # 10 turns


async def load_context(state: ShopSenseState) -> dict:
    """
    Reads Redis history and PostgreSQL user context, merges with the current
    incoming message, and returns the three fields it owns.

    The caller (router endpoint) sets state["messages"] = [current_user_message]
    before invoking the graph. This node prepends the stored history to it.
    """
    session_id = state.get("session_id", "")
    user_id = state.get("user_id", "")

    # The current incoming message — placed in state by the router before graph.invoke()
    incoming: list[dict[str, str]] = state.get("messages", [])

    # ── 1. Load conversation history from Redis ───────────────────────────────
    history: list[dict[str, str]] = []
    if session_id:
        try:
            redis = get_redis_client()
            raw = await redis.get(f"history:{session_id}")
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    # Trim to the most recent N messages before merging
                    history = parsed[-_MAX_HISTORY_MESSAGES:]
        except Exception as exc:
            log.warning("Redis history load failed for session %s: %s", session_id, exc)

    # Merge: stored history + current incoming message.
    # incoming is [current_user_message]; history already excludes it.
    messages = history + incoming

    # ── 2. Load user profile from PostgreSQL ──────────────────────────────────
    user_email = ""
    user_preferences: dict = {}

    if user_id:
        try:
            uid = uuid.UUID(user_id)
            async with AsyncSessionLocal() as db:
                # Email from the users table
                user = await db.scalar(select(User).where(User.id == uid))
                if user:
                    user_email = user.email

                # Preference profile written by the personalisation worker
                prefs = await db.scalar(
                    select(UserPreferences).where(UserPreferences.user_id == uid)
                )
                if prefs is not None:
                    user_preferences = {
                        "preferred_brands": prefs.preferred_brands or [],
                        "preferred_categories": prefs.preferred_categories or [],
                        "feature_priorities": prefs.feature_priorities or {},
                        "typical_price_min": (
                            float(prefs.typical_price_min)
                            if prefs.typical_price_min is not None else None
                        ),
                        "typical_price_max": (
                            float(prefs.typical_price_max)
                            if prefs.typical_price_max is not None else None
                        ),
                    }
        except Exception as exc:
            log.warning("DB context load failed for user_id %s: %s", user_id, exc)

    return {
        "messages": messages,
        "user_email": user_email,
        "user_preferences": user_preferences,
    }
