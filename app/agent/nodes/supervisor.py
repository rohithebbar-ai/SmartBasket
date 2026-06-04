"""
classify_intent — second node in the graph.

Reads the latest user message from state["messages"], formats up to 5 prior
turns as history context, and calls the intent classifier prompt via call_llm.

Validated against the 10 valid intent strings via IntentOutput. On any error
(LLM failure, parse error, unexpected value) defaults to PRODUCT_SEARCH rather
than crashing — the graph must never halt on a classification failure.

Writes to state: intent
"""

import logging

from app.agent.prompts import INTENT_CLASSIFIER_PROMPT
from app.agent.state import ShopSenseState
from app.llm import call_llm
from app.schemas.llm import IntentOutput
from app.search.catalogue_config import get_catalogue

log = logging.getLogger(__name__)

_DEFAULT_INTENT = "PRODUCT_SEARCH"
_VALID_INTENTS = set(IntentOutput.model_fields["intent"].annotation.__args__)

_HISTORY_WINDOW = 5


def _format_history(messages: list[dict[str, str]], exclude_last: int = 1) -> str:
    prior = messages[:-exclude_last] if exclude_last else messages
    window = prior[-_HISTORY_WINDOW:]
    if not window:
        return "(no prior conversation)"
    return "\n".join(f"{m['role'].capitalize()}: {m['content']}" for m in window)


async def classify_intent(state: ShopSenseState) -> dict:
    messages: list[dict[str, str]] = state.get("messages", [])

    if not messages:
        log.warning("classify_intent called with empty messages — defaulting to %s", _DEFAULT_INTENT)
        return {"intent": _DEFAULT_INTENT}

    # If image was uploaded, force VISUAL intent — no LLM needed
    if state.get("visual_attributes", {}).get("image_b64"):
        return {"intent": "VISUAL"}

    current_message = messages[-1].get("content", "")
    history = _format_history(messages, exclude_last=1)

    # Build domain-specific examples from catalogue routing_examples (SEMANTIC type = product discovery)
    try:
        config = get_catalogue(state.get("catalogue") or "fashion")
        store_name = config.display_name
        product_search_examples = "\n".join(
            f'  "{q}"'
            for q, qtype in config.routing_examples
            if qtype == "SEMANTIC"
        )
    except Exception:
        store_name = "ShopSense"
        product_search_examples = '  "show me products"\n  "find something for me"'

    prompt = INTENT_CLASSIFIER_PROMPT.format(
        history=history,
        message=current_message,
        store_name=store_name,
        product_search_examples=product_search_examples,
    )

    try:
        raw = await call_llm(prompt, tier="fast", max_tokens=150, temperature=0.0)
        output = IntentOutput.model_validate_json(raw)
        intent = output.intent
    except Exception as exc:
        log.warning("Intent classification failed (%s) — defaulting to %s", exc, _DEFAULT_INTENT)
        intent = _DEFAULT_INTENT

    if intent not in _VALID_INTENTS:
        log.warning("Unexpected intent %r — defaulting to %s", intent, _DEFAULT_INTENT)
        intent = _DEFAULT_INTENT

    return {"intent": intent}
