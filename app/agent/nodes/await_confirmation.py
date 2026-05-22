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

Security rule:
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
    # interrupt() raises NodeInterrupt on first call, checkpoints state.
    # On resume via Command(resume=value), interrupt() RETURNS the resume value
    # instead of raising — execution continues from here.
    pending_description = state.get("pending_tool_description", "")
    user_reply: str = interrupt(pending_description)

    # ── Pass 2: classify the user's reply ────────────────────────────────────
    # user_reply is the string passed by Command(resume=message) in the router.
    # Fallback to messages[-1] in case an older resume path is used.
    if not isinstance(user_reply, str) or not user_reply.strip():
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
        # Re-ask once. Capture the return value so we can classify it.
        second_reply: str = interrupt(_AMBIGUOUS_REPROMPT)
        try:
            raw2 = await call_llm(
                CONFIRMATION_CLASSIFIER_PROMPT.format(
                    confirmation_context=confirmation_context,
                    message=second_reply,
                ),
                tier="fast", max_tokens=100, temperature=0.0,
            )
            out2 = ConfirmationOutput.model_validate_json(raw2)
            decision = out2.decision
        except Exception as exc:
            log.warning("Second confirmation classification failed (%s) — defaulting to DECLINE", exc)
            decision = "DECLINE"

        # If still ambiguous after a second chance, decline to avoid infinite loops.
        if decision == "AMBIGUOUS":
            decision = "DECLINE"

    if decision == "DECLINE":
        return {
            "user_decision": "DECLINE",
            "final_response": "No problem, I've cancelled that. What else can I help you with?",
        }

    return {"user_decision": decision}
