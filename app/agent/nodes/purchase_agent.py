# TODO: Unified purchase sub-agent (will absorb handle_purchase_intent + handle_checkout)
# Handles the full intent → stock check → checkout → confirmation flow
# For now, handle_purchase_intent and handle_checkout remain as separate nodes
async def purchase_agent(state):
    raise NotImplementedError
