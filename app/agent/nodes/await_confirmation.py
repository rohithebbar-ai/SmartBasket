"""
await_confirmation — human-in-the-loop node using LangGraph interrupt().

Flow (two-pass per confirmation):

  Pass 1 — graph reaches this node for the first time:
    interrupt(pending_tool_description) is called.
    LangGraph serialises the full graph state to the checkpointer and
    returns control to the caller (the SSE endpoint).
    The description string is sent to the frontend as the interrupt payload.

  Pass 2 — frontend calls graph.invoke() again with the same thread_id:
    LangGraph resumes execution here. The user's reply is now the last
    message in state["messages"].
    We classify it with CONFIRMATION_CLASSIFIER_PROMPT (Haiku, ~100ms).
    - CONFIRM   → return {"user_decision": "CONFIRM"}
                  graph routes to handle_purchase_intent to execute the tool
    - DECLINE   → return {"user_decision": "DECLINE"}
                  graph routes to synthesise with a cancellation message
    - AMBIGUOUS → set final_response to the re-ask prompt, then interrupt()
                  again — the user must answer clearly before we proceed

Security rule (from CLAUDE.md / Section 19):
  AMBIGUOUS must NEVER be treated as CONFIRM. The node always re-asks.
  Only a clear affirmative in the latest user message counts as CONFIRM.

Writes to state: user_decision, (conditionally) final_response
"""

import logging

from langgraph.types import interrupt

from app.agent.prompts import CONFIRMATION_CLASSIFIER_PROMPT
from app.agent.state import ShopSenseState
from app.llm import call_llm
from app.schemas.llm import ConfirmationOutput

log = logging.getLogger(__name__)

_AMBIGUOUS_REPROMPT = (
    "I need a clear yes or no — shall I proceed?"
)


async def await_confirmation(state: ShopSenseState) -> dict:
    # ── Pass 1: pause and surface the pending action description ─────────────
    # interrupt() raises an internal LangGraph exception that serialises state
    # and returns the value to the caller. Execution resumes here on the next
    # graph.invoke() call with the same thread_id.
    pending_description = state.get("pending_tool_description", "")
    interrupt(pending_description)

    # ── Pass 2: classify the user's reply ────────────────────────────────────
    messages: list[dict[str, str]] = state.get("messages", [])
    user_reply = messages[-1].get("content", "") if messages else ""
    confirmation_context = state.get("confirmation_context", pending_description)

    prompt = CONFIRMATION_CLASSIFIER_PROMPT.format(
        confirmation_context=confirmation_context,
        message=user_reply,
    )

    decision = "AMBIGUOUS"
    try:
        raw = await call_llm(prompt, tier="fast", max_tokens=100, temperature=0.0)
        output = ConfirmationOutput.model_validate_json(raw)
        decision = output.decision
    except Exception as exc:
        log.warning(
            "Confirmation classification failed (%s) — treating as AMBIGUOUS", exc
        )

    if decision == "AMBIGUOUS":
        # Re-ask and pause again. Execution resumes after this line on the next invoke().
        interrupt(_AMBIGUOUS_REPROMPT)
        # If the user is STILL ambiguous after the re-ask, the conditional edge routes
        # back here for a fresh node call. Update pending_tool_description so that
        # fresh call interrupts with the re-ask message rather than the original prompt.
        return {
            "user_decision": "AMBIGUOUS",
            "final_response": _AMBIGUOUS_REPROMPT,
            "pending_tool_description": _AMBIGUOUS_REPROMPT,
        }

    return {"user_decision": decision}
