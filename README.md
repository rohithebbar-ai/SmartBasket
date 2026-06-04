# SmartBasket

**AI-native product discovery platform for fashion & electronics.**

SmartBasket is a production-grade e-commerce backend that replaces keyword search with genuine semantic understanding. A customer types *"something for a rooftop birthday party this weekend, budget ₹4000"* and receives three specific products with a sentence explaining why each was chosen — grounded entirely in the store's real catalogue, never hallucinated. They can upload a photo and get visually similar results instantly. The system handles the full commerce loop: discovery → comparison → checkout → post-purchase review collection, all through a stateful conversational AI agent.

**Built by Rohit Hebbar · May–June 2026**

---

## Architecture

### High-Level System

![High Level System Architecture](assets/high_level_system_architecture.png)

### Retrieval Architecture

![Retrieval Architecture](assets/retrieval_architecture.png)

### Event-Driven Architecture

![Event Driven Architecture](assets/event_driven_architecture.png)

---

## What SmartBasket Does

**Understands intent, not just keywords.**
Every query is classified before retrieval — SEMANTIC, ANALYTICAL, HYBRID, or VISUAL. A search for "something cute for brunch" goes through Jina v3 embeddings → Qdrant → flashrank reranker. A question like "which colour has the most options?" goes directly to PostgreSQL via NL-to-SQL. Hybrid queries (e.g. "well-reviewed blue dress under ₹3000") use SQL to constrain the candidate set, then vector search to rank within it.

**Visual search via CLIP — zero LLM cost.**
Upload a product photo. A separate CLIP microservice (ViT-B-32, hosted free on Hugging Face Spaces) classifies the image against real Redis attribute sets — colour, pattern, category — via zero-shot cosine similarity. The top labels become a `rewritten_query` that flows into the normal Qdrant search path. No Bedrock vision call, no per-image API cost, ~250ms end-to-end.

**Works for any catalogue — zero hardcoding.**
All domain knowledge lives in `catalogue_config.py`. Fashion and electronics catalogues each define their own filterable attributes, routing examples, sentiment fields, Qdrant collection, and synthesis tips. Every agent node reads from this config via `get_catalogue(state["catalogue"])`. Pointing at a new catalogue requires one config entry, not code changes.

**Builds a user model silently.**
Every product view, cart event, and completed order flows into a Kafka stream that updates each user's preference profile — preferred brands, colours, price range, occasion context. The agent reads this profile before generating any response. No preference forms required.

**Prices respond to live demand.**
A background pricing engine reads a 24-hour demand counter from Redis (incremented by every `product.viewed` event) and adjusts prices every two minutes. Cart totals recalculate automatically because the orders module listens to the `price.updated` Kafka topic.

**Full checkout loop inside the conversation.**
The LangGraph agent handles discovery → comparison → add-to-cart → checkout → payment in one thread. Every write operation goes through a `human-in-the-loop` confirmation step via `interrupt()` before execution.

**Closes the review loop automatically.**
Three days after delivery, the post-purchase worker schedules a review outreach. The agent nudges the customer in their next session, collects a star rating and review text, and upserts it into PostgreSQL.

**Budget-aware recommendations.**
When results fall below the user's stated budget, the agent also surfaces products just above their limit (up to 30% over) with the exact ₹ premium — the same proactive behaviour as Amazon Rufus.

---

## Tech Stack

| Layer         | Technology                                           | Why                                                                             |
|---------------|------------------------------------------------------|---------------------------------------------------------------------------------|
| API           | FastAPI + Python 3.11                                | Async-first, typed, production-ready                                            |
| Agent         | LangGraph                                            | Stateful graph, `interrupt()` for human-in-the-loop, SSE streaming              |
| LLM           | Amazon Bedrock (Claude Sonnet 4.5 / Haiku 4.5)       | IAM auth, no key rotation, inference profiles                                   |
| LLM (dev)     | Groq (`llama-3.1-8b-instant`) / Google Gemini        | Free-tier dev; switch via `LLM_PROVIDER` env var                                |
| Embeddings    | Jina v3 (`jina-embeddings-v3`, 1024-dim)             | Separate query/passage task modes                                               |
| Visual search | CLIP ViT-B-32 via `open-clip-torch`                  | Zero-shot image → attribute classification; hosted free on HF Spaces            |
| Vector DB     | Qdrant Cloud                                         | Cosine similarity with metadata payload filtering                               |
| Reranker      | flashrank                                            | Local cross-encoder, no API cost                                                |
| Database      | PostgreSQL via Supabase                              | Products, orders, users, reviews, price history, NL-to-SQL audit                |
| Cache         | Redis                                                | Cart, price cache, demand counters, attribute sets, conversation history         |
| Event bus     | Apache Kafka                                         | Demand signals, price recalculation, personalisation, post-purchase scheduling  |
| ORM           | SQLAlchemy 2.0 async                                 | Mapped columns, async session factory                                           |
| Auth          | JWT HS256 + bcrypt                                   | Stateless, role-aware (customer / admin)                                        |
| MCP           | FastAPI MCP server (`/mcp/tools/{name}`)             | Cart, payment, notification tools callable by the agent via httpx               |
| Payments      | Stripe (test mode)                                   | `process_payment` MCP tool                                                      |
| Email         | SendGrid                                             | Order confirmation, price drop alerts, review outreach                          |
| Infra         | Terraform + AWS EC2 + nginx                          | Reproducible, free-tier deployable                                              |
| Observability | LangSmith                                            | Full agent trace per conversation turn (auto-activates on `LANGCHAIN_TRACING_V2=true`) |

---

## LangGraph Agent

The conversational agent is a stateful `StateGraph` compiled with `MemorySaver`. Every turn: load context → classify intent → route → retrieve/act → synthesise → save history.

### Intent Routes

| Intent              | Route                                                                                     |
|---------------------|-------------------------------------------------------------------------------------------|
| `PRODUCT_SEARCH`    | route_query → semantic_search → personalise → synthesise                                 |
| `EXPLAIN`           | route_query → semantic_search → personalise → synthesise                                 |
| `COMPARE`           | compare_products → synthesise                                                            |
| `ANALYTICAL`        | route_query → nl_to_sql → synthesise                                                    |
| `HYBRID`            | route_query → hybrid_search → personalise → synthesise                                  |
| `REVIEW_SUMMARY`    | route_query → summarize_reviews → save_history                                          |
| `VISUAL`            | visual_search → (personalise → synthesise) or save_history                              |
| `PURCHASE_INTENT`   | handle_purchase_intent → price_intelligence → propose_tool_action → await_confirmation → execute_tool |
| `CHECKOUT`          | handle_checkout → await_confirmation → execute_tool                                     |
| `ORDER_STATUS`      | handle_order_status → save_history                                                       |
| `POST_PURCHASE`     | handle_post_purchase → (await_confirmation → execute_tool) or save_history              |
| `WISHLIST_ACTION`   | handle_wishlist → save_history                                                           |
| `ADMIN_ACTION`      | handle_admin → save_history                                                              |
| `OUT_OF_SCOPE`      | refuse → END                                                                             |

### Confirmation Loop

Every write tool call passes through `await_confirmation`, which calls `interrupt()` and suspends the graph. The SSE endpoint detects the paused state and sends `{"type": "interrupt"}` to the frontend. On the next request the client sends the user's reply; `await_confirmation` classifies it as `CONFIRM | DECLINE | AMBIGUOUS` before routing to `execute_tool` or `save_history`.

### MCP Tools (dispatched by `execute_tool`)

| Tool                           | Type  | What it does                                                          |
|--------------------------------|-------|-----------------------------------------------------------------------|
| `add_to_cart`                  | Write | Writes to Redis cart; publishes `cart.updated`                        |
| `process_payment`              | Write | Charges via Stripe, creates order in PostgreSQL, publishes `order.created` |
| `send_confirmation_email`      | Write | Auto-fired after payment success                                      |
| `set_price_alert`              | Write | Inserts into `price_alerts` table                                     |
| `submit_review`                | Write | UPSERTs `order_reviews`; recalculates `products.avg_rating`           |
| `get_saved_payment_methods`    | Read  | Fetches saved cards for checkout summary                              |
| `calculate_order_total`        | Read  | Live cart total (subtotal + GST + delivery)                           |
| `get_frequently_bought_together` | Read | Cross-sell after add_to_cart                                        |

### State Shape (`ShopSenseState`)

```
messages, session_id, user_id, user_email
catalogue                          # "fashion" | "electronics"
intent, query_type
search_results, sql_results, generated_sql
user_preferences, pending_review_products
visual_attributes                  # image_b64, clip_top, rewritten_query
occasion_context, style_preference
final_response, sources
pending_tool, pending_tool_args, pending_tool_description
user_decision, awaiting_confirmation
order_id, cart_summary, tool_result
price_trend_pct, price_insight_shown, price_alert_set
extracted_filters, budget_overrun_results
recommend_alternatives_query
```

---

## Kafka Topics

| Topic             | Producer        | Consumers                                                           |
|-------------------|-----------------|---------------------------------------------------------------------|
| `product.viewed`  | products module | search module (demand counter), personalisation worker              |
| `product.created` | products module | embedding worker (lazy Qdrant upsert)                               |
| `cart.updated`    | orders module   | personalisation worker                                              |
| `order.created`   | orders module   | personalisation worker (highest weight signal)                      |
| `order.delivered` | orders module   | post-purchase worker (schedules review outreach)                    |
| `price.updated`   | pricing engine  | orders module (recalculates active cart totals)                     |

---

## Background Workers

### Personalisation Worker

Consumes `product.viewed`, `cart.updated`, and `order.created` events. Scores each signal against a product's brand, category, price, colour, and occasion. Flushes updated preference scores to `users.user_preferences` every 50 events or 5 minutes.

### Post-Purchase Worker

Consumes `order.delivered` events. Schedules review outreach in a Redis sorted set at T+3 days. Three loops run concurrently: outreach (every 60s), price alert (every 600s), and Kafka consumer.

### Sentiment Worker

Batch-scores new products using Bedrock Claude Haiku — seven aspect sentiment scores (style, quality, fit, comfort, versatility, delivery, value). Scores feed into Qdrant payloads and agent comparison responses.

---

## Database Schema

| Migration | Table               | Purpose                                              |
|-----------|---------------------|------------------------------------------------------|
| 001       | `users`             | Auth, roles, hashed password                         |
| 002       | `products`          | Catalogue, attributes/specs (JSONB), sentiment scores|
| 003       | `order_reviews`     | Star ratings + text, ON CONFLICT UPSERT per order    |
| 004       | `orders`            | Order records, items (JSONB price snapshot), status  |
| 005       | `price_history`     | Daily price snapshots per product                    |
| 006       | `user_preferences`  | Per-user brand/category/price/feature scores (JSONB) |
| 007       | `nl_sql_audit`      | Every NL-to-SQL query + generated SQL                |
| 008       | `wishlists`         | User wishlist items                                  |
| 009       | `users.last_login`  | Session analytics column                            |
| 010       | `price_alerts`      | Target price alerts with `is_active`, `triggered_at` |
| 011       | `payment_methods`   | Saved Stripe payment method references               |
| 012       | `orders.delivered_at` | Delivery timestamp for post-purchase scheduling    |
| 014       | `user_item_interactions` | Click/view/purchase signals for recommender    |
| 015       | `policy_documents`  | Return/shipping policy chunks for RAG                |
| 016       | `admin_notifications` | Admin alert queue                                  |

---

## Data

**H&M Fashion catalogue** — 105,542 real products from the H&M Personalized Fashion Recommendations dataset (Kaggle). Each product includes name, category, colour, pattern, garment group, section, and a text description. Embedded with Jina v3 at 1024 dimensions into Qdrant Cloud (`hm_products` collection).

**Redis attribute sets** — After ingestion, `workers/etl/attribute_indexer.py` populates `attrs:fashion:{colour,pattern,category,...}` Redis Sets from live Supabase data. The CLIP service and constraint extractor both read from these sets, ensuring CLIP never classifies a colour that doesn't exist in the catalogue.

Run the attribute indexer after any schema change:

```bash
uv run python -m workers.etl.attribute_indexer
```

---

## Visual Search Architecture

The CLIP service is a **stateless FastAPI microservice** — it has no database, no Redis, no knowledge of catalogues. The main app fetches attribute candidates from its own Redis and sends them with the image in each request:

```
POST /classify
{
  "image_b64": "...",
  "candidates": {
    "colour":   ["Black", "Light Blue", "Dark Red", ...],  ← from Redis
    "category": ["Dress", "T-shirt", "Trousers", ...],
    "pattern":  ["Solid", "Floral", "Striped", ...]
  }
}
→ {"top": {"colour": "Light Blue", "category": "Dress"}, "scores": {...}}
```

CLIP returns top-1 per attribute (no confidence threshold — with 42 colour candidates softmax spreads to ~0.024 uniform; relative ranking is meaningful even when absolute scores are low). The main app builds `rewritten_query = "Light Blue Dress"` → Jina embed → Qdrant search.

**Local dev:** `clip-service` Docker container on port 8001 (`CLIP_SERVICE_URL=http://localhost:8001`).
**Production:** Hugging Face Spaces free tier (16GB RAM, ~$0/mo). `CLIP_SERVICE_URL=https://<username>-clip-service.hf.space`. Protected by `X-API-Key` header — end users never see the HF URL.

Model weights (~350MB) are cached in a named Docker volume (`clip_model_cache`) so they're only downloaded once.

---

## Key Design Decisions

**Catalogue-config-driven architecture.** All domain knowledge — routing examples, filterable attributes, synthesis tips, sentiment fields — lives in `catalogue_config.py`. Zero hardcoding in any agent node. Adding a new catalogue (e.g. "furniture") requires one `CatalogueConfig` entry.

**CLIP over Bedrock vision for image search.** Bedrock Sonnet vision costs ~$0.005–0.015 per image call. With $100 of AWS demo credits, that's a hard limit. CLIP zero-shot classification on a CPU container costs $0 per call and runs at ~50ms. The interface is identical — if quality is insufficient, swap back to Bedrock by changing one config field.

**Modular monolith over microservices.** Clean internal module boundaries with shared async infrastructure. Extractable to services when a specific scaling problem justifies it — not before. The CLIP service is the deliberate exception: PyTorch is 2GB+ and would bloat the main app image.

**Postgres and Qdrant on cloud, Kafka and Redis local (dev).** Supabase and Qdrant Cloud both have generous free tiers. Running them locally added no value during development and consumed EC2 resources. Kafka and Redis stay local because they hold ephemeral state (demand counters, conversation history) that doesn't need to survive across dev sessions.

**Human-in-the-loop before every write.** Every agent-triggered write calls `interrupt()` and waits for explicit user confirmation before executing. This is an architectural constraint, not a safety feature bolted on.

**Redis sorted set for review outreach.** `ZADD review_outreach_queue <unix_ts> <payload>` — naturally time-ordered, `ZRANGEBYSCORE` pops due entries atomically. No cron job needed.

---

## Project Structure

```
smartbasket/
├── app/
│   ├── auth/               # JWT, bcrypt, get_current_user, require_admin
│   ├── products/           # Catalogue CRUD, Kafka producer, embedding trigger
│   ├── orders/             # Cart (Redis), orders (PostgreSQL), Kafka consumer/producer
│   ├── users/              # UserPreferences — written by worker, read by agent
│   ├── search/
│   │   ├── catalogue_config.py   # CatalogueConfig dataclass — single source of domain truth
│   │   ├── embedder.py           # Jina v3 embed()
│   │   ├── qdrant_ops.py         # search(), ensure_catalogue_indexes()
│   │   ├── reranker.py           # flashrank cross-encoder
│   │   ├── constraint_extractor.py  # LLM → ConstraintOutput (filters + rewritten query)
│   │   ├── hybrid_search.py      # RRF merge of SQL + vector
│   │   └── pricing_engine.py     # Demand-based price adjustment loop
│   ├── analytics/          # Admin NL-to-SQL endpoints
│   ├── policies/           # Policy document ingestion + RAG retriever
│   ├── recommendations/    # ALS collaborative filter + content-based blending
│   ├── mcp/
│   │   ├── server.py       # FastAPI MCP server
│   │   ├── client.py       # Async httpx singleton
│   │   └── tools/          # checkout, orders, product_intel, wishlist, admin
│   └── agent/
│       ├── graph.py        # LangGraph StateGraph — intent routing + all edges
│       ├── state.py        # ShopSenseState TypedDict (total=False)
│       ├── prompts.py      # All LLM prompt templates (catalogue-aware placeholders)
│       ├── router.py       # SSE /chat endpoint + image_b64 support
│       └── nodes/
│           ├── load_context.py           # Redis history + Supabase user profile
│           ├── supervisor.py             # Intent classifier (forces VISUAL if image present)
│           ├── route_query.py            # SEMANTIC / ANALYTICAL / HYBRID / REVIEW_SUMMARY
│           ├── product_discovery.py      # Constraint extraction → Qdrant → flashrank
│           ├── hybrid_search.py          # RRF merge
│           ├── text2sql.py               # NL-to-SQL with SELECT-only guard
│           ├── comparison.py             # Named product lookup → comparison
│           ├── visual_search.py          # Redis candidates → CLIP → Qdrant
│           ├── personalise.py            # Preference-based score boosts
│           ├── synthesise.py             # LLM generation (catalogue-aware tips)
│           ├── summarize_reviews.py      # Aspect-aware review summary
│           ├── recommend_alternatives.py # OOS fallback
│           ├── handle_purchase_intent.py # Stock check → price intelligence
│           ├── price_intelligence.py     # 7-day avg + surge insight
│           ├── propose_action.py         # Formats confirmation prompt
│           ├── handle_checkout.py        # Card + cart fetch → payment payload
│           ├── handle_order_status.py    # DB query last 3 orders
│           ├── handle_post_purchase.py   # REVIEW / RETURN / OTHER classification
│           ├── await_confirmation.py     # interrupt() gate
│           ├── execute_tool.py           # MCP dispatch + cross-sell
│           ├── refuse.py                 # Static out-of-scope response
│           └── save_history.py           # Redis history:{session_id}
├── workers/
│   ├── etl/                       # Catalogue ingestion pipeline
│   │   ├── attribute_indexer.py   # Populates Redis attribute sets from Supabase
│   │   ├── pipeline.py            # Full ETL orchestration
│   │   └── connectors/            # CSV, JSON, Postgres, Shopify, HM dataset
│   ├── scheduled_agents/
│   │   ├── post_purchase.py       # Review outreach + price alerts
│   │   ├── catalogue_gap.py       # Detect catalogue gaps
│   │   ├── trend_intelligence.py  # Trending product signals
│   │   └── restock_prediction.py  # Low-stock early warning
│   ├── sentiment_worker.py        # Bedrock Haiku aspect sentiment scoring
│   └── run_workers.py             # Entry point
├── deploy/
│   └── hf_spaces/clip/            # CLIP microservice (HuggingFace Spaces)
│       ├── app.py                 # FastAPI: /classify + /health
│       ├── Dockerfile             # HF Spaces (port 7860, CPU torch)
│       └── Dockerfile.local       # Local dev (port 8001)
├── frontend/
│   ├── storefront/                # Customer-facing React app
│   └── admin/                     # Admin dashboard React app
├── tests/                         # pytest, mirrors app module structure
├── terraform/                     # EC2, security groups, Elastic IP
├── docker-compose.yml             # Redis + Kafka + clip-service (Postgres/Qdrant on cloud)
├── docker-compose.prod.yml        # Production overrides
└── pyproject.toml
```

---

## Getting Started

### Prerequisites

- Python 3.11, Docker + Docker Compose, [`uv`](https://github.com/astral-sh/uv)
- AWS account with Bedrock access (or use Groq/Gemini for dev)
- Jina API key — [jina.ai](https://jina.ai/) (free tier)
- Supabase project — [supabase.com](https://supabase.com/) (free tier)
- Qdrant Cloud cluster — [cloud.qdrant.io](https://cloud.qdrant.io/) (free tier)
- SendGrid API key — [sendgrid.com](https://sendgrid.com/) (free tier)
- Stripe account (test mode) — [stripe.com](https://stripe.com/)

### Setup

```bash
git clone https://github.com/rohithebbar-ai/SmartBasket.git
cd SmartBasket

# Install dependencies
uv sync --extra dev

# Configure environment
cp .env.example .env
# Fill in all required values (see Environment Variables below)

# Start local infrastructure (Redis · Kafka · CLIP service)
# Postgres and Qdrant are on cloud — no local containers needed
docker compose up -d redis kafka

# Apply database migrations
supabase db push

# Seed Redis attribute sets (run once after ingestion, or after docker reset)
uv run python -m workers.etl.attribute_indexer

# Start the API server
uv run uvicorn app.main:app --reload
# API:      http://localhost:8000
# Docs:     http://localhost:8000/docs
# Kafka UI: http://localhost:8080

# Start background workers (separate terminal)
uv run python -m workers.run_workers

# (Optional) Start CLIP service for visual search
docker compose up clip-service --build
# First start downloads ViT-B-32 weights (~350MB, cached after first run)
```

### Environment Variables

```env
# Database (Supabase cloud)
DATABASE_URL=postgresql+asyncpg://postgres:...@db.<ref>.supabase.co:5432/postgres
SUPABASE_URL=https://<ref>.supabase.co

# Vector DB (Qdrant Cloud)
QDRANT_URL=https://...cloud.qdrant.io
QDRANT_API_KEY=...

# Cache (local Docker)
REDIS_URL=redis://localhost:6380/0

# Kafka (local Docker)
KAFKA_BOOTSTRAP_SERVERS=localhost:9092

# LLM — Amazon Bedrock (production)
AWS_REGION=us-east-1
BEDROCK_GENERATION_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
BEDROCK_FAST_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0

# LLM — dev alternatives (set LLM_PROVIDER=groq or LLM_PROVIDER=gemini)
LLM_PROVIDER=groq
GROQ_KEY=gsk_...
GEMINI_KEY=...

# Embeddings
JINA_API_KEY=jina_...

# CLIP Visual Search
CLIP_SERVICE_URL=http://localhost:8001          # local dev
# CLIP_SERVICE_URL=https://<user>-clip-service.hf.space  # production (HF Spaces)
CLIP_SERVICE_API_KEY=...                        # shared secret — set same value in HF Space secrets

# Auth
APP_SECRET_KEY=...    # openssl rand -hex 32

# Payments
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Email
SENDGRID_API_KEY=SG....
SENDGRID_FROM_EMAIL=noreply@shopsense.app

# Observability (optional — enables LangSmith tracing)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls__...
LANGCHAIN_PROJECT=shopsense
```

---

## API Reference

### Auth

| Method | Path              | Auth     | Description                 |
|--------|-------------------|----------|-----------------------------|
| POST   | `/auth/register`  | Public   | Register a new account      |
| POST   | `/auth/login`     | Public   | Authenticate, return JWT    |
| GET    | `/auth/me`        | Required | Current authenticated user  |

### Products

| Method | Path                  | Auth     | Description                                       |
|--------|-----------------------|----------|---------------------------------------------------|
| GET    | `/api/products`       | Optional | Paginated catalogue with filters                  |
| GET    | `/api/products/{id}`  | Optional | Product detail + reviews; fires `product.viewed`  |
| POST   | `/api/products`       | Admin    | Create product                                    |
| PUT    | `/api/products/{id}`  | Admin    | Update product                                    |

### Orders

| Method | Path                          | Auth     | Description                              |
|--------|-------------------------------|----------|------------------------------------------|
| POST   | `/api/orders/cart/add`        | Required | Add item — reads live price from Redis   |
| DELETE | `/api/orders/cart/remove`     | Required | Remove item from cart                    |
| GET    | `/api/orders/cart/{user_id}`  | Required | Current cart with live totals            |
| POST   | `/api/orders`                 | Required | Checkout — publishes `order.created`     |
| GET    | `/api/orders/{id}`            | Required | Order detail                             |
| PUT    | `/api/orders/{id}/status`     | Admin    | Update order status; publishes event     |

### Search & Agent

| Method | Path                   | Auth     | Description                                             |
|--------|------------------------|----------|---------------------------------------------------------|
| POST   | `/api/search`          | Optional | Semantic · analytical · hybrid retrieval                |
| POST   | `/api/chat`            | Required | Streaming conversational agent (SSE); supports `image_b64` for visual search |
| POST   | `/api/analytics/query` | Admin    | NL-to-SQL — plain English → live data                   |

### Users

| Method | Path                         | Auth     | Description                       |
|--------|------------------------------|----------|-----------------------------------|
| GET    | `/api/users/me/preferences`  | Required | Current user preference profile   |

### System

| Method | Path      | Auth   | Description                       |
|--------|-----------|--------|-----------------------------------|
| GET    | `/health` | Public | Health check (API + Redis status) |
| GET    | `/docs`   | Public | Swagger UI (non-production only)  |

---

## Running Tests

```bash
uv run pytest                           # Full suite with coverage report
uv run pytest tests/orders/ -v          # Scope to one module
uv run pytest -k "not integration"      # Skip tests that hit live APIs
uv run pytest tests/agent/ -v           # Agent intent + tool calling tests
```

---

## Security Notes

- `hashed_password` is never returned in any API response schema
- `stripe_payment_method_id` is never returned to the client
- JWT payload contains only `user_id`, `role`, `exp` — no PII
- NL-to-SQL enforces SELECT-only (blocks DROP/DELETE/UPDATE/INSERT/ALTER/TRUNCATE)
- Dynamic pricing is bounded: never below `0.80×` or above `1.30×` base price
- CLIP service URL is never exposed to end users — it is a backend-to-backend call protected by `X-API-Key`
- All Kafka topic names come from `settings.kafka_topic_*` — no hardcoded strings
- No PII in any Kafka event payload

---

## License

MIT
