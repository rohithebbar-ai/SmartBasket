"""
All LLM prompts for the ShopSense agent, centralised here.

Versioning convention (in comments above each prompt):
  v<N> — <date> — <model tier> — <what changed>

Template variables use single braces: {variable_name}
JSON examples inside prompts use double braces: {{"key": "value"}} to escape formatting.

Prompts in this file:
  QUERY_ROUTER_PROMPT          — used by app/search/query_router.py (stateless /search path)
  INTENT_CLASSIFIER_PROMPT     — 10-intent classifier used by classify_intent node
  QUERY_TYPE_ROUTER_PROMPT     — history-aware query type router used by route_query node
  CONFIRMATION_CLASSIFIER_PROMPT — CONFIRM/DECLINE/AMBIGUOUS for await_confirmation node
  PRICE_INSIGHT_PROMPT         — proactive price surge explanation (Section 22.4)
"""

# ── Query Router (stateless — used by /api/search directly) ──────────────────
# v1 — 2026-05-18 — fast tier; ~150ms; returns {"type": "...", "reasoning": "..."}

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


# ── Intent Classifier ─────────────────────────────────────────────────────────
# v1 — 2026-05-20 — fast tier; ~200ms
# Classifies the user's message into one of 10 intents.
# Returns: {"intent": "<INTENT>", "reasoning": "<one sentence>"}

INTENT_CLASSIFIER_PROMPT = """You are ShopSense, an AI assistant for a consumer electronics store.
Classify the user's latest message into exactly one intent.

Recent conversation (for context only — classify the LATEST message):
{history}

Latest message: {message}

Intents and examples
--------------------
PRODUCT_SEARCH — user wants to discover or find products
  "show me gaming laptops under 80k"
  "what's a good laptop for college students"

COMPARE — user wants a side-by-side comparison of specific products
  "compare Dell XPS 15 vs HP Spectre x360"
  "which is better, MacBook Air or Lenovo ThinkPad X1?"

EXPLAIN — user wants to understand a feature, spec, or term
  "what does OLED display mean for everyday use"
  "explain why NVMe SSD is faster than a regular hard drive"

PURCHASE_INTENT — user wants to buy a specific product or add it to cart
  "I want to buy the Dell XPS 15"
  "add the HP Pavilion 15 to my cart"

CHECKOUT — user wants to review cart, confirm order, or complete payment
  "proceed to checkout"
  "show me my cart and place the order"

ORDER_STATUS — user wants to track an existing order or delivery
  "where is my order #12345"
  "has my laptop shipped yet"

POST_PURCHASE — user wants help after receiving an order (return, refund, review)
  "I want to return the laptop I bought last week"
  "how do I get a refund for my recent order"

WISHLIST_ACTION — user wants to save a product for later
  "save the Asus ZenBook to my wishlist"
  "add this to my saved items for later"

ADMIN_ACTION — user is asking for business analytics or inventory data
  "show me the revenue breakdown by brand this month"
  "which products have the lowest stock right now"

OUT_OF_SCOPE — message is not related to shopping, products, or orders
  "what is the weather in Bangalore today"
  "tell me a joke"

Rules:
- Use conversation history only to understand references ("that one", "it", "the second option").
- PURCHASE_INTENT is for specific product selection. CHECKOUT is for completing a transaction.
- If the message mentions an order number or delivery tracking, use ORDER_STATUS.
- When genuinely ambiguous, prefer PRODUCT_SEARCH over OUT_OF_SCOPE.

Respond with JSON only — no markdown, no explanation outside the JSON:
{{"intent": "PRODUCT_SEARCH", "reasoning": "user wants to discover laptops matching criteria"}}"""


# ── Query Type Router (history-aware — used inside the agent graph) ───────────
# v1 — 2026-05-20 — fast tier; ~150ms
# Different from QUERY_ROUTER_PROMPT: uses conversation history so references like
# "compare them" or "what's the cheapest one" resolve correctly in context.
# Returns: {"type": "SEMANTIC|ANALYTICAL|HYBRID", "reasoning": "<one sentence>"}

QUERY_TYPE_ROUTER_PROMPT = """Determine the best retrieval strategy for this shopping query.

Recent conversation (for resolving context — "them", "it", "the cheapest one"):
{history}

Current message: {message}

Retrieval strategies:
- SEMANTIC — discovery or recommendation query; needs meaning, not numbers.
  Examples: "laptop for video editing", "something lightweight for travel",
  "what do developers usually prefer"

- ANALYTICAL — structured data question; needs exact counts, averages, or rankings.
  Examples: "which brand has the highest average rating",
  "how many products are under 50k", "show out-of-stock items"

- HYBRID — needs both: semantic understanding of what the user wants AND
  structured filters (price cap, brand, rating threshold, stock check).
  Examples: "best reviewed Dell laptop under 80k with good battery",
  "top rated options for video editing under 1 lakh",
  "highly rated gaming laptops that are in stock"

Rules:
- A price filter alone does not make a query HYBRID — it must also need semantic ranking.
- ANALYTICAL queries ask for aggregate data (counts, averages, rankings across products).
- If unsure between SEMANTIC and HYBRID, choose HYBRID when a hard filter is present.

Respond with JSON only — no markdown, no explanation outside the JSON:
{{"type": "HYBRID", "reasoning": "semantic ranking needed alongside price and brand filter"}}"""


# ── Confirmation Classifier ───────────────────────────────────────────────────
# v1 — 2026-05-20 — fast tier; ~100ms
# Classifies the user's reply to a proposed action as CONFIRM, DECLINE, or AMBIGUOUS.
# AMBIGUOUS must never be treated as CONFIRM — the node re-asks for clarification.
# Returns: {"decision": "CONFIRM|DECLINE|AMBIGUOUS", "reasoning": "<one sentence>"}

CONFIRMATION_CLASSIFIER_PROMPT = """The ShopSense assistant proposed the following action:

Action: {confirmation_context}

The user replied: {message}

Classify the user's reply:
- CONFIRM  — clear, unambiguous agreement to proceed.
  Phrases that count: "yes", "go ahead", "confirm", "do it", "place it", "sure", "ok",
  "proceed", "that's fine", "sounds good", "yes please".

- DECLINE  — clear refusal or cancellation.
  Phrases that count: "no", "cancel", "don't", "stop", "nevermind", "forget it",
  "don't do it", "abort", "nope", "not now".

- AMBIGUOUS — anything that is not a clear yes or no. This includes:
  questions ("how much will it cost?"), conditions ("only if it ships today"),
  partial agreement ("maybe, but…"), silence, or unrelated messages.

Rules:
- Only a clear, direct affirmative in the user's reply counts as CONFIRM.
- "I think so" or "probably yes" is AMBIGUOUS — not CONFIRM.
- A question about the action is always AMBIGUOUS — the user wants more info first.
- Err toward AMBIGUOUS when unsure. Never guess CONFIRM.

Respond with JSON only — no markdown, no explanation outside the JSON:
{{"decision": "CONFIRM", "reasoning": "user said 'go ahead' — unambiguous agreement"}}"""


# ── Filter Extraction ─────────────────────────────────────────────────────────
# v1 — 2026-05-20 — fast tier; ~300ms
# Extracts structured filters from the raw user query and rewrites it for embedding.
# Returns: FilterExtractionOutput — all filter fields optional; rewritten_query always set.

FILTER_EXTRACTION_PROMPT = """Extract structured filters from this shopping query and rewrite it for semantic search.

Query: {query}

Return JSON only with these exact fields:
- rewritten_query: cleaned, expanded version of the query optimized for dense vector search
- max_price: maximum price as a number in rupees (null if not mentioned)
- min_price: minimum price as a number in rupees (null if not mentioned)
- brand: exact brand name like "Dell", "Apple", "Samsung" (null if not mentioned)
- category: product category like "laptop", "phone", "headphones", "tablet" (null if not mentioned)
- use_case: specific use case like "gaming", "video editing", "college", "travel" (null if not mentioned)
- features: list of specific features like ["4K display", "16GB RAM"] (empty list if none)

Rules:
- rewritten_query must always be present — expand abbreviations, add context words for better retrieval
- Price constraints like "under 80k" → max_price: 80000
- If no filter applies, set the field to null (not missing)
- Keep brand names exactly as they appear in the market

Respond with JSON only — no markdown, no explanation:
{{"rewritten_query": "gaming laptop with dedicated graphics card", "max_price": 80000, "min_price": null, "brand": null, "category": "laptop", "use_case": "gaming", "features": ["dedicated GPU"]}}"""


# ── Response Synthesis ────────────────────────────────────────────────────────
# v1 — 2026-05-20 — generation tier; ~500ms
# Generates the final user-facing response. Adapts tone to query type.
# Called by synthesise node for SEMANTIC, ANALYTICAL, and HYBRID paths.

SYNTHESIS_PROMPT = """You are ShopSense, a helpful AI shopping assistant for a consumer electronics store.

User question: {question}
Query type: {query_type}

{context_block}

User preferences (use to personalise your response, do not mention explicitly):
{user_preferences}

Response guidelines by query type:
- SEMANTIC: Warm, conversational recommendation. Highlight 2-3 top picks with key specs, price, and rating. Explain why each fits the user's need.
- HYBRID: Lead with the structural finding (price range, rating threshold met), then explain the semantic fit. Recommend 2-3 products.
- ANALYTICAL: Clear, data-driven answer. Start with the direct answer, then supporting numbers. No product pitching.
- COMPARE: Side-by-side comparison. Name each product, list key differences, give a clear recommendation for different user types.

Constraints:
- Keep response under 200 words (ANALYTICAL may go to 150 words for data clarity).
- Reference only data provided above — never invent specs or prices.
- If no results were found, apologise briefly and suggest rephrasing the query.
- Do not use the phrase "Based on the data provided"."""


# ── Compare Products — Name Extraction ───────────────────────────────────────
# v1 — 2026-05-20 — fast tier; ~150ms
# Extracts 2-3 product names from a comparison request for Qdrant lookup.
# Returns a JSON array of name strings.

COMPARE_EXTRACTION_PROMPT = """Extract the exact product names the user wants to compare.

Message: {message}

Return a JSON array of product name strings (2-3 names). Use the names exactly as mentioned.
If you cannot identify specific products, return an empty array.

Respond with JSON only — no markdown:
["Dell XPS 15", "HP Spectre x360"]"""


# ── Price Insight ─────────────────────────────────────────────────────────────
# v1 — 2026-05-20 — generation tier; ~300ms
# Generates a 3-4 sentence message explaining a price surge and asking the user
# whether to wait or proceed. Called by present_price_insight node (Section 22.4).
# Tone: informative and helpful, not alarmist. Always ends with the wait/proceed choice.

PRICE_INSIGHT_PROMPT = """You are ShopSense, a helpful shopping assistant.

The user is about to purchase: {product_name}
Current price: ₹{current_price:,.0f}
Price vs 7-day average: {trend_pct:+.1f}% ({trend_direction})
Pricing reason on record: {reason}

Write a 3-4 sentence message that:
1. Mentions the current price and notes it is {trend_pct:.1f}% {trend_direction} the recent average.
2. Briefly explains why prices are elevated right now, based on the reason: {reason}.
3. Reassures the user this is normal for high-demand electronics.
4. Ends by asking whether they want to set a price-drop alert and wait, or proceed now.

Tone: warm, informative, never alarmist. Do not use the word "surge" or "spike".
Write in plain conversational English — no bullet points, no headers.
Keep it under 80 words."""
