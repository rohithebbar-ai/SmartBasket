# ShopSense

**AI-native product discovery platform for consumer electronics.**

ShopSense is a production-grade e-commerce backend that replaces keyword search with genuine semantic understanding. A customer types *"laptop for video editing under ₹80K that's light for travel"* and receives a personalised, reasoned comparison — not a list of keyword matches. The system handles the full commerce loop: discovery → comparison → checkout → post-purchase review collection, all through a stateful conversational AI agent.

**Built by Rohit Hebbar · May 2026**

---

## Architecture

### High-Level System

![High Level System Architecture](assets/high_level_system_architecture.png)

### Retrieval Architecture

![Retrieval Architecture](assets/retrieval_architecture.png)

### Event-Driven Architecture

![Event Driven Architecture](assets/event_driven_architecture.png)

---

## What ShopSense Does

**Understands intent, not just keywords.**
Every query is classified before retrieval — SEMANTIC, ANALYTICAL, or HYBRID. A search for "something for creators who travel light" goes through Jina v3 embeddings → Qdrant → flashrank reranker. A question like "which brand has the highest average rating?" goes directly to PostgreSQL via NL-to-SQL. Hybrid queries (e.g. "best laptop under ₹60K") use SQL to constrain the candidate set, then vector search to rank within it.

**Builds a user model silently.**
Every product view, cart event, and completed order flows into a Kafka stream that updates each user's preference profile — preferred brands, price range, feature priorities. The agent reads this profile before generating any response. No preference forms required.

**Prices respond to live demand.**
A background pricing engine reads a 24-hour demand counter from Redis (incremented by every `product.viewed` event) and adjusts prices every two minutes. Cart totals recalculate automatically because the orders module listens to the `price.updated` Kafka topic.

**Full checkout loop inside the conversation.**
The LangGraph agent handles discovery → comparison → add-to-cart → checkout → payment in one thread. Every write operation — add to cart, place order, submit review — goes through a `human-in-the-loop` confirmation step via `interrupt()` before execution.

**Closes the review loop automatically.**
Three days after delivery, the post-purchase worker schedules a review outreach. The agent nudges the customer in their next session, collects a star rating and review text, and upserts it into PostgreSQL — which recalculates the product's average rating and flows back into Qdrant payloads for future recommendations.

**Surfaces proactive price insight.**
When a customer shows purchase intent, the agent checks 7-day price history. If the current price is significantly above recent average, it surfaces a "price is elevated right now — want a price drop alert?" moment before showing the add-to-cart confirmation.

**Budget-aware recommendations.**
When results fall below the user's stated budget, the agent also surfaces products just above their limit (up to 30% over) with the exact ₹ premium — the same proactive behaviour as Amazon Rufus.

---

## Tech Stack

| Layer         | Technology                                           | Why                                                                             |
|---------------|------------------------------------------------------|---------------------------------------------------------------------------------|
| API           | FastAPI + Python 3.11                                | Async-first, typed, production-ready                                            |
| Agent         | LangGraph                                            | 24-node stateful graph, `interrupt()` for human-in-the-loop, SSE streaming     |
| LLM           | Amazon Bedrock (Claude Sonnet 4.5 / Haiku 4.5)       | IAM auth, no key rotation, eu-north-1 inference profiles                        |
| LLM (dev)     | Groq (`llama-3.1-8b-instant`) / Google Gemini        | Free-tier dev; switch via `LLM_PROVIDER` env var                                |
| Embeddings    | Jina v3 (`jina-embeddings-v3`, 1024-dim)             | Separate query/passage task modes; won 3-way smoke test vs NVIDIA & Bedrock Titan |
| Vector DB     | Qdrant Cloud                                         | Cosine similarity with metadata payload filtering                               |
| Reranker      | flashrank                                            | Local cross-encoder, no API cost                                                |
| Database      | PostgreSQL via Supabase                              | Products, orders, users, reviews, price history, price alerts, NL-to-SQL audit  |
| Cache         | Redis                                                | Cart (7-day TTL), price cache (10-min), demand counters (24-hr), review outreach queue |
| Event bus     | Apache Kafka                                         | Demand signals, price recalculation, personalisation, post-purchase scheduling  |
| ORM           | SQLAlchemy 2.0 async                                 | Mapped columns, async session factory                                           |
| Auth          | JWT HS256 + bcrypt                                   | Stateless, role-aware (customer / admin)                                        |
| MCP           | FastAPI MCP server (`/mcp/tools/{name}`)             | Cart, payment, notification tools callable by the agent via httpx               |
| Payments      | Stripe (test mode)                                   | `process_payment` MCP tool; payment_method_id never returned to client          |
| Email         | SendGrid                                             | Order confirmation, price drop alerts, review outreach                          |
| Infra         | Terraform + AWS EC2 + nginx                          | Reproducible, free-tier deployable                                              |
| Observability | LangSmith                                            | Full agent trace per conversation turn (auto-activates on `LANGCHAIN_TRACING_V2=true`) |

---

## LangGraph Agent — 24-Node Graph

The conversational agent is a stateful `StateGraph` compiled with `MemorySaver` (swap to `RedisSaver` for production). Every turn: load context → classify intent → route → retrieve/act → synthesise → save history.

### Intent Routes

| Intent              | Route                                                                                     |
|---------------------|-------------------------------------------------------------------------------------------|
| `PRODUCT_SEARCH`    | route_query → semantic_search → personalise → synthesise                                 |
| `EXPLAIN`           | route_query → semantic_search → personalise → synthesise                                 |
| `COMPARE`           | compare_products → synthesise                                                            |
| `ANALYTICAL`        | route_query → nl_to_sql_search → synthesise                                             |
| `HYBRID`            | route_query → hybrid_search → personalise → synthesise                                  |
| `REVIEW_SUMMARY`    | route_query → summarize_reviews → save_history                                          |
| `PURCHASE_INTENT`   | handle_purchase_intent → price_intelligence → propose_tool_action → await_confirmation → execute_tool |
| `CHECKOUT`          | handle_checkout → await_confirmation → execute_tool                                     |
| `ORDER_STATUS`      | handle_order_status → save_history                                                       |
| `POST_PURCHASE`     | handle_post_purchase → (await_confirmation → execute_tool) or save_history              |
| `PRICE_INSIGHT`     | price_intelligence → synthesise                                                          |
| `RECOMMEND_ALT`     | recommend_alternatives → save_history                                                    |
| `WISHLIST_ACTION`   | handle_wishlist (stub) → save_history                                                    |
| `ADMIN_ACTION`      | handle_admin (stub) → save_history                                                       |
| `OUT_OF_SCOPE`      | refuse → END                                                                             |

### Confirmation Loop

Every write tool call passes through `await_confirmation`, which calls `interrupt()` and suspends the graph. The SSE endpoint catches `GraphInterrupt` and sends `{"type": "interrupt"}` to the frontend. On the next request the client sends the user's reply, the graph resumes, and `await_confirmation` classifies it as `CONFIRM | DECLINE | AMBIGUOUS` before routing to `execute_tool` or `save_history`.

### MCP Tools (dispatched by `execute_tool`)

| Tool                           | Type  | What it does                                                          |
|--------------------------------|-------|-----------------------------------------------------------------------|
| `add_to_cart`                  | Write | Writes to Redis cart; publishes `cart.updated`                        |
| `process_payment`              | Write | Charges via Stripe, creates order in PostgreSQL, publishes `order.created` |
| `send_confirmation_email`      | Write | Auto-fired after payment success — no separate confirmation gate      |
| `set_price_alert`              | Write | Inserts into `price_alerts` table                                     |
| `submit_review`                | Write | UPSERTs `order_reviews`; recalculates `products.avg_rating`           |
| `get_saved_payment_methods`    | Read  | Fetches saved cards for checkout summary                              |
| `calculate_order_total`        | Read  | Live cart total (subtotal + GST + delivery)                           |
| `get_frequently_bought_together` | Read | Cross-sell after add_to_cart — up to 2 products, appended to response |

### State Shape (`ShopSenseState`)

Key fields written across nodes:

```
messages, session_id, user_id, user_email
intent, query_type
search_results, sql_results, generated_sql
user_preferences, pending_review_products
final_response, sources
pending_tool, pending_tool_args, pending_tool_description, confirmation_context
user_decision, awaiting_confirmation
order_id, cart_summary, tool_result
price_trend_pct, price_insight_shown, price_alert_set
recommend_alternatives_query
extracted_filters, budget_overrun_results
```

---

## Kafka Topics

| Topic             | Producer        | Consumers                                                           |
|-------------------|-----------------|---------------------------------------------------------------------|
| `product.viewed`  | products module | search module (demand counter), personalisation worker              |
| `product.created` | products module | embedding worker (lazy Qdrant upsert)                               |
| `cart.updated`    | orders module   | personalisation worker                                              |
| `order.created`   | orders module   | personalisation worker (highest weight signal)                      |
| `order.delivered` | orders module   | post-purchase worker (schedules review outreach via Redis sorted set)|
| `price.updated`   | pricing engine  | orders module (recalculates active cart totals)                     |

---

## Background Workers

### Personalisation Worker (`workers/personalisation_worker.py`)

Consumes `product.viewed`, `cart.updated`, and `order.created` events. Scores each signal against a product's brand, category, price, and features. Flushes updated preference scores to `users.user_preferences` every 50 events or 5 minutes. The agent reads this profile from `load_context` before every turn.

### Post-Purchase Worker (`workers/post_purchase_worker.py`)

Consumes `order.delivered` events. Schedules review outreach in a Redis sorted set (`review_outreach_queue`) at T+3 days, plus a 30-second demo entry. Three loops run concurrently:

- **Outreach loop** (every 60s): pops due entries, sends a review request email via SendGrid, sets a `pending_review:{user_id}` Redis key (7-day TTL).
- **Price alert loop** (every 600s): joins `price_alerts` with `products`; when current price ≤ target, sends a price drop email and marks the alert `is_active=FALSE`.
- **Kafka consumer loop**: feeds the outreach queue on new `order.delivered` events.

Both workers run together via `workers/run_workers.py`.

---

## Database Schema (12 migrations)

| Migration | Table               | Purpose                                              |
|-----------|---------------------|------------------------------------------------------|
| 001       | `users`             | Auth, roles (customer/admin), hashed password        |
| 002       | `products`          | Catalogue, specs (JSONB), avg_rating, sentiment scores |
| 003       | `order_reviews`     | Star ratings + text, ON CONFLICT UPSERT per order    |
| 004       | `orders`            | Order records, items (JSONB price snapshot), status  |
| 005       | `price_history`     | Daily price snapshots per product                    |
| 006       | `user_preferences`  | Per-user brand/category/price/feature scores (JSONB) |
| 007       | `nl_sql_audit`      | Every NL-to-SQL query + generated SQL (fine-tune data)|
| 008       | `wishlists`         | User wishlist items                                  |
| 009       | `users.last_login`  | Added column for session analytics                   |
| 010       | `price_alerts`      | Target price alerts with `is_active`, `triggered_at` |
| 011       | `payment_methods`   | Saved Stripe payment method references               |
| 012       | `orders.delivered_at` | Column for delivery timestamp                      |

---

## Data Pipeline

**21,173 real laptop products** sourced from Amazon product metadata and Kaggle datasets, deduplicated by name.

**129,765 reviews** matched to products via fuzzy name matching from the McAuley Lab Amazon Reviews 2023 dataset. Unmatched products receive synthetic reviews generated with Faker.

**1,503 products sentiment-scored** via Bedrock Claude Haiku — seven aspect scores (battery, display, build quality, value, performance, keyboard, thermal) plus `top_complaint` and `top_praise`. Scores feed directly into Qdrant payloads and the agent's comparison responses.

**1,503 products embedded** with Jina v3 at 1024 dimensions and upserted to Qdrant Cloud with full metadata payload. Remaining products embed on demand via a Redis-queued lazy worker.

Run the pipeline in order:

```bash
make ingest
# runs: fetch_amazon_reviews → process_kaggle → seed_postgres → run_sentiment → generate_embeddings → verify_ingestion
```

---

## Key Design Decisions

**Modular monolith over microservices.** Clean internal module boundaries with shared async infrastructure. Extractable to services when a specific scaling problem justifies it — not before.

**Vectorless RAG for analytical queries.** NL-to-SQL for questions where precision matters. Vector search reserved for discovery queries that cannot be expressed as structured filters. Every NL-to-SQL query is audited to a PostgreSQL table that doubles as a fine-tuning dataset.

**JSONB snapshots for order items.** Cart lives in Redis. Order items are JSONB price snapshots at checkout time — permanent regardless of future price changes or schema migrations. Preferable to a separate `order_items` table because snapshot semantics are explicit in the data model.

**Human-in-the-loop before every write.** Architectural constraint, not a safety feature bolted on. Every agent-triggered write calls `interrupt()` and waits for explicit user confirmation before executing.

**Bedrock over third-party LLM APIs.** IAM authentication means no key rotation, no rate limit surprises, and automatic cross-region redundancy via inference profile IDs (`eu.anthropic.*`). Same IAM role that accesses EC2 accesses Bedrock.

**Redis sorted set for review outreach.** `ZADD review_outreach_queue <unix_ts> <payload>` — naturally time-ordered, `ZRANGEBYSCORE` pops due entries atomically. No cron job or separate scheduler needed.

---

## Project Structure

```
shopsense/
├── app/
│   ├── auth/               # JWT, bcrypt, get_current_user, require_admin
│   ├── products/           # Catalogue CRUD, Kafka producer, embedding trigger
│   ├── orders/             # Cart (Redis), orders (PostgreSQL), Kafka consumer/producer
│   ├── users/              # UserPreferences — written by worker, read by agent
│   ├── search/             # Embedder, Qdrant, query router, NL-to-SQL, pricing engine
│   ├── analytics/          # Admin NL-to-SQL endpoints
│   ├── mcp/
│   │   ├── server.py       # FastAPI MCP server (tools exposed to agent)
│   │   ├── client.py       # Async httpx singleton, closed in app lifespan
│   │   └── tools/
│   │       ├── cart_tools.py          # add_to_cart, remove_from_cart, get_cart, calculate_order_total
│   │       ├── payment_tools.py       # get_saved_payment_methods, process_payment, set_price_alert
│   │       └── notification_tools.py  # send_confirmation_email, submit_review, get_frequently_bought_together
│   ├── agent/
│   │   ├── graph.py        # 24-node LangGraph StateGraph (MemorySaver checkpointer)
│   │   ├── state.py        # ShopSenseState TypedDict (total=False)
│   │   ├── prompts.py      # All LLM prompt templates
│   │   ├── router.py       # SSE /chat endpoint, interrupt resume logic
│   │   └── nodes/
│   │       ├── load_context.py           # Redis history + PostgreSQL user profile + pending reviews
│   │       ├── classify_intent.py        # 10-intent classifier (Haiku fast tier)
│   │       ├── route_query.py            # SEMANTIC / ANALYTICAL / HYBRID / REVIEW_SUMMARY
│   │       ├── semantic_search.py        # Filter extraction → Jina embed → Qdrant → flashrank
│   │       ├── hybrid_search.py          # RRF merge of SQL + vector rankings
│   │       ├── nl_to_sql_search.py       # NL-to-SQL with SELECT-only guard + audit log
│   │       ├── compare_products.py       # Qdrant lookup by product name → comparison
│   │       ├── personalise.py            # Score boost by brand/category/price/feature preferences
│   │       ├── synthesise.py             # Bedrock Sonnet generation; review nudge prepend
│   │       ├── summarize_reviews.py      # Aspect-aware review summary
│   │       ├── recommend_alternatives.py # OOS fallback: similar in-stock products
│   │       ├── handle_purchase_intent.py # Stock check → delivery estimate → pending_tool payload
│   │       ├── price_intelligence.py     # 7-day avg + surge insight + price alert prompt
│   │       ├── propose_tool_action.py    # Formats add-to-cart confirmation prompt
│   │       ├── handle_checkout.py        # Parallel MCP fetch (card + cart) → process_payment payload
│   │       ├── handle_order_status.py    # DB query last 3 orders → formatted response (no LLM)
│   │       ├── handle_post_purchase.py   # LLM classifies REVIEW/RETURN/OTHER; routes review
│   │       ├── await_confirmation.py     # interrupt() gate; classifies CONFIRM/DECLINE/AMBIGUOUS
│   │       ├── execute_tool.py           # MCP dispatch + cross-sell + auto confirmation email
│   │       ├── refuse.py                 # Static out-of-scope response
│   │       └── save_history.py           # Appends turn to Redis history:{session_id}
│   ├── schemas/            # Shared Pydantic schemas at LLM boundaries
│   ├── config.py           # Pydantic settings, env var validation
│   ├── database.py         # AsyncSessionLocal, engine lifecycle
│   ├── llm.py              # Bedrock / Groq / Gemini abstraction (tier="fast"|"smart")
│   └── redis_client.py     # Shared async Redis pool
├── workers/
│   ├── personalisation_worker.py   # Kafka → preference scoring → PostgreSQL flush
│   ├── post_purchase_worker.py     # order.delivered → review outreach + price alert emails
│   └── run_workers.py              # Entry point: asyncio.gather(personalisation, post_purchase)
├── data/
│   └── ingestion/
│       ├── fetch_amazon_reviews.py     # McAuley Lab reviews download
│       ├── process_kaggle_laptops.py   # Kaggle dataset cleaning
│       ├── seed_postgres.py            # Bulk insert products + reviews
│       ├── run_sentiment.py            # Bedrock Haiku 7-aspect sentiment scoring
│       ├── generate_embeddings.py      # Jina v3 → Qdrant upsert
│       └── verify_ingestion.py        # Sanity check: counts, nulls, Qdrant sync
├── database/
│   └── migrations/                    # 12 numbered SQL migration files (Supabase CLI)
├── tests/                             # pytest, mirrors app module structure
│   ├── agent/
│   ├── analytics/
│   ├── auth/
│   ├── events/
│   ├── mcp/
│   ├── orders/
│   ├── products/
│   ├── search/
│   ├── users/
│   └── workers/
├── infra/
│   ├── terraform/          # EC2, security groups, Elastic IP, S3 state backend
│   └── nginx/              # Reverse proxy config
├── docker-compose.yml      # Full local stack
├── Makefile                # Dev, test, lint, ingest, deploy shortcuts
└── pyproject.toml          # Dependencies, ruff, mypy, pytest config
```

---

## Getting Started

### Prerequisites

- Python 3.11, Docker + Docker Compose, [`uv`](https://github.com/astral-sh/uv)
- AWS account with Bedrock access in `eu-north-1`
- Jina API key — [jina.ai](https://jina.ai/) (free tier)
- Supabase project — [supabase.com](https://supabase.com/) (free tier)
- Qdrant Cloud cluster — [cloud.qdrant.io](https://cloud.qdrant.io/) (free tier)
- SendGrid API key — [sendgrid.com](https://sendgrid.com/) (free tier, for emails)
- Stripe account (test mode) — [stripe.com](https://stripe.com/)

### Setup

```bash
git clone https://github.com/rohithebbar/shopsense.git
cd shopsense

# Install dependencies
uv sync --extra dev

# Configure environment
cp .env.example .env
# Fill in all required values (see Environment Variables below)

# Start local infrastructure (Postgres · Redis · Kafka · Qdrant)
docker compose up -d

# Apply database migrations
supabase db push

# Run the data pipeline (one-time, ~30 min)
make ingest

# Start the API server
uv run uvicorn app.main:app --reload
# API:      http://localhost:8000
# Docs:     http://localhost:8000/docs
# Kafka UI: http://localhost:8080

# Start background workers (separate terminal)
make workers
```

### Environment Variables

```env
# Database
DATABASE_URL=postgresql+asyncpg://...
MIRROR_DATABASE_URL=postgresql+asyncpg://...   # Local Docker postgres — ingestion only

# LLM (Amazon Bedrock — production)
AWS_REGION=eu-north-1
BEDROCK_GENERATION_MODEL_ID=eu.anthropic.claude-sonnet-4-5-20250929-v1:0
BEDROCK_FAST_MODEL_ID=eu.anthropic.claude-haiku-4-5-20251001-v1:0

# LLM (dev alternatives — set LLM_PROVIDER=groq or LLM_PROVIDER=gemini)
GROQ_API_KEY=gsk_...
GOOGLE_API_KEY=...

# Embeddings
JINA_API_KEY=jina_...

# Vector DB
QDRANT_URL=https://...cloud.qdrant.io
QDRANT_API_KEY=...

# Cache
REDIS_URL=redis://localhost:6379

# Kafka
KAFKA_BOOTSTRAP_SERVERS=localhost:9092

# Auth
APP_SECRET_KEY=...    # openssl rand -hex 32

# Payments
STRIPE_SECRET_KEY=sk_test_...

# Email
SENDGRID_API_KEY=SG....
SENDGRID_FROM_EMAIL=noreply@shopsense.app

# Observability (optional — enables LangSmith tracing)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls__...
LANGCHAIN_PROJECT=shopsense
```

### Make Commands

```bash
make dev          # Start docker compose + uvicorn with --reload
make stop         # docker compose down
make workers      # Start personalisation + post-purchase workers
make test         # Full pytest suite with coverage
make test-module module=orders   # Scope to one module
make lint         # ruff check
make format       # ruff format
make typecheck    # mypy
make ingest       # Full data pipeline (all 6 steps in order)
make db-push      # Apply Supabase migrations (remote)
make db-new name=add_xyz   # Create a new migration file
make db-reset     # Reset local DB
make deploy YOUR_IP=1.2.3.4   # terraform apply
make tf-plan YOUR_IP=1.2.3.4  # terraform plan
make clean        # Remove all docker volumes + cache dirs
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

| Method | Path                   | Auth     | Description                                 |
|--------|------------------------|----------|---------------------------------------------|
| POST   | `/api/search`          | Optional | Semantic · analytical · hybrid retrieval    |
| POST   | `/api/chat`            | Required | Streaming conversational agent (SSE)        |
| POST   | `/api/analytics/query` | Admin    | NL-to-SQL — plain English → live data       |

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
uv run pytest -k "not golden"           # Skip LLM golden tests (require Bedrock)
uv run pytest tests/workers/ -v         # Personalisation + post-purchase worker tests
```

Golden tests in `tests/search/test_query_router_golden.py` are auto-skipped unless `LLM_PROVIDER=bedrock` — they are calibrated to Bedrock Haiku's 85%+ routing accuracy.

---

## Security Notes

- `hashed_password` is never returned in any API response schema
- `stripe_payment_method_id` is never returned to the client
- JWT payload contains only `user_id`, `role`, `exp` — no PII
- NL-to-SQL enforces SELECT-only (blocks DROP/DELETE/UPDATE/INSERT/ALTER/TRUNCATE), max 2 retries, full audit log
- Dynamic pricing is bounded: never below `0.80×` or above `1.30×` base price
- All Kafka topic names come from `settings.kafka_topic_*` — no hardcoded strings
- No PII (email, full name) in any Kafka event payload

---

## License

MIT
