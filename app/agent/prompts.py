# All LLM prompts centralised here.
# Version each prompt with a comment when modified; track alongside model version.

# ── Query Router ──────────────────────────────────────────────────────────────
# v1 — 2026-05-18 — Haiku; ~150ms; returns {"type": "SEMANTIC|ANALYTICAL|HYBRID", "reasoning": "..."}

QUERY_ROUTER_PROMPT = """Classify this shopping query into exactly one category.

Categories:
- SEMANTIC: Discovery query, exploratory, needs meaning not structure.
  Examples: "laptop for video editing", "something portable for travel",
  "what do you recommend for a developer", "good gaming laptop"

- ANALYTICAL: Structured data question, needs exact numbers or aggregations.
  Examples: "which brand has highest ratings", "show out of stock products",
  "average price of Dell laptops", "products with most price changes this week",
  "how many laptops are under 50k"

- HYBRID: Needs both semantic understanding AND structured filters.
  Examples: "best reviewed laptop under 80k with good battery",
  "top rated Dell products for video editing",
  "affordable options with high display ratings"

Query: {query}

Respond with JSON only — no markdown, no explanation outside the JSON:
{{"type": "SEMANTIC", "reasoning": "exploratory discovery, no structured constraints"}}"""
