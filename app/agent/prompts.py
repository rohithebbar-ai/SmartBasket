# All LLM prompts centralised here — implement in Week 3 (Days 12–13).
# Version each prompt with a comment when modified; track alongside model version.
#
# Prompts to define (see platform plan Section 9 for full text):
#   INTENT_CLASSIFICATION_PROMPT   — Haiku; returns intent JSON
#   QUERY_ROUTER_PROMPT            — Haiku; returns {"type": "SEMANTIC|ANALYTICAL|HYBRID"}
#   FILTER_EXTRACTION_PROMPT       — Haiku; returns structured filter JSON from query
#   NL_TO_SQL_PROMPT               — Haiku; schema-aware, SELECT-only enforcement
#   RESPONSE_SYNTHESIS_PROMPT      — Sonnet; adapts tone to retrieval method
#   ASPECT_SENTIMENT_PROMPT        — Sonnet; batch ingestion only, returns five sentiment floats
