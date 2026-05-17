# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

ShopSense is an AI-native product discovery platform for consumer electronics — currently in active development (May 2026). The authoritative platform plan is `ShopSense_Platform_Plan_v4.md` at the repo root. The scaffold is complete; build begins Week 1 (2026-05-12).

## Build Commands

All commands use `uv`. Run `make install` once after cloning.

```bash
make install        # uv sync --extra dev
make dev            # docker compose up -d + uvicorn --reload
make stop           # docker compose down
make logs           # docker compose logs -f
make workers        # start background workers (pricing + personalisation)
make test           # pytest with coverage
make test-module module=search   # scope to one module
make lint           # ruff check
make format         # ruff format
make typecheck      # mypy
make ingest         # full data pipeline (run in order)
make tf-init        # terraform init
make tf-plan YOUR_IP=1.2.3.4
make deploy YOUR_IP=1.2.3.4
make clean          # docker compose down -v + remove caches
```

## Architecture

**Modular monolith** — single FastAPI app (`create_app()` factory in `app/main.py`), separate worker processes (not services) for the pricing engine and personalisation consumer. Workers live in `workers/` and share the same codebase.

### Module map (`app/`)

| Module | Responsibility |
|--------|---------------|
| `auth/` | JWT auth — `router.py`, `models.py` (User), `schemas.py`, `service.py`, `dependencies.py` (`get_current_user`, `require_admin`), `utils.py` (bcrypt + jose). Leaf module — imports nothing from other app modules. |
| `products/` | Catalogue CRUD, Kafka producer (`product.viewed`, `product.created`) |
| `orders/` | Cart (Redis hash), orders (PostgreSQL), consumes `price.updated` to recalculate cart totals |
| `users/` | UserPreferences table only — written by personalisation worker, read by agent. User model lives in `auth/`. |
| `schemas/` | Pydantic models for all LLM output boundaries (`llm.py`) and retrieval boundaries (`search.py`). Every LLM response is parsed into a schema immediately — never passed as a raw dict. |
| `search/` | Embedder (Jina/NVIDIA), Qdrant ops, query router, NL-to-SQL engine, hybrid search, flashrank reranker, pricing engine (120s cycle) |
| `agent/` | LangGraph graph, all nodes, streaming `/chat` SSE endpoint |
| `analytics/` | Admin-only NL-to-SQL BI endpoints; requires `require_admin` dependency |
| `mcp/` | MCP server stub (port 8006); Phase 1 checkout tool implementations |

### Auth dependency pattern

```python
# Public route — no import needed
# Customer route
from app.auth.dependencies import get_current_user
# Admin route
from app.auth.dependencies import require_admin
```

The auth module never imports from any other app module.

### Storage

- **PostgreSQL (Supabase):** `users`, `user_preferences`, `products`, `reviews`, `orders`, `price_history`, `nl_sql_audit`
- **Qdrant:** Product embeddings — **1024-dim** (Jina v3 or NVIDIA nv-embedqa-e5-v5), cosine, with metadata payload for pre-filtering
- **Redis:** `cart:{user_id}` (7d), `current_price:{product_id}` (10min), `views:{product_id}` (24h), `history:{session_id}` (1h), search/SQL cache (1h/30min)
- **Kafka:** 5 topics — names read from `settings.kafka_topic_*` fields, never hardcoded

### AI Layers

**LLM — Amazon Bedrock** (no API key; uses AWS profile or instance role):
- `bedrock_generation_model_id` (`claude-3-5-sonnet`) — response synthesis, sentiment, comparison
- `bedrock_fast_model_id` (`claude-3-haiku`) — intent classification, query routing, NL-to-SQL, filter extraction

**Embeddings** — runtime-selectable via `EMBEDDING_PROVIDER` env var:
- `JINA` → `jina-embeddings-v3` via Jina API (default; 1024-dim)
- `NVIDIA` → `nvidia/nv-embedqa-e5-v5` via NVIDIA NIM API (1024-dim)
- Changing provider after ingestion requires recreating the Qdrant collection

**Query routing:** every query → SEMANTIC | ANALYTICAL | HYBRID before retrieval:
- SEMANTIC → Qdrant vector search + flashrank reranker
- ANALYTICAL → NL-to-SQL → PostgreSQL
- HYBRID → SQL constrains candidate set, vector search ranks within it

### Key config field names (from `app/config.py`)

| `.env` variable | `settings.*` field |
|---|---|
| `BEDROCK_GENERATION_MODEL_ID` | `settings.bedrock_generation_model_id` |
| `BEDROCK_FAST_MODEL_ID` | `settings.bedrock_fast_model_id` |
| `QDRANT_COLLECTION_NAME` | `settings.qdrant_collection_name` |
| `KAFKA_TOPIC_PRODUCT_VIEWED` | `settings.kafka_topic_product_viewed` |
| `PRICING_ENGINE_INTERVAL_SECONDS` | `settings.pricing_engine_interval_seconds` |
| `PRICING_DEMAND_THRESHOLD` | `settings.pricing_demand_threshold` |

All Kafka topic names are read from `settings.kafka_topic_*` — never hardcode topic strings.

### Pydantic at LLM boundaries

Every LLM response is parsed into a typed schema immediately — never propagated as a raw dict or string:

| LLM call | Parse into |
|---|---|
| Intent classification | `IntentOutput` (`app.schemas.llm`) |
| Query routing | `QueryRouterOutput` (`app.schemas.llm`) |
| Filter extraction | `FilterExtractionOutput` (`app.schemas.llm`) |
| Purchase confirmation | `ConfirmationOutput` (`app.schemas.llm`) |
| Aspect sentiment | `AspectSentimentOutput` (`app.schemas.llm`) |
| Qdrant / reranker results | `ProductResult` (`app.schemas.search`) |
| Search endpoint response | `SearchResponse` (`app.schemas.search`) |
| Analytics endpoint response | `AnalyticsResponse` (`app.schemas.search`) |
| NL-to-SQL pipeline result | `NLToSQLResult` (`app.schemas.search`) |

`Literal` constraints on intent/type fields mean `ValidationError` fires at the parse boundary if the model hallucinates an unexpected value — callers retry rather than propagate garbage.

### Embedding connection pooling

`app/search/embedder.py` holds a module-level `requests.Session()` singleton (`_session`). The session is created once at startup with the provider API key in the `Authorization` header and reused for all embed calls. Do not create a new session per request — this defeats connection pooling and adds TLS handshake overhead during bulk ingestion.

## Critical Implementation Rules

**NL-to-SQL safety** (non-negotiable):
- Generated SQL must pass `sqlparse` validation before execution — rejects anything that is not SELECT
- Block `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE` keywords
- Maximum 2 retries on validation failure; log every attempt to `nl_sql_audit`
- Schema injection: only the four ShopSense tables — never full DB metadata
- Admin NL-to-SQL routes (`/api/analytics/`) require `require_admin` dependency

**Auth rules:**
- `APP_SECRET_KEY` must be min 32 chars (generate: `openssl rand -hex 32`)
- JWT payload: only `user_id`, `role`, `exp` — no sensitive fields
- `hashed_password` never appears in any Pydantic response schema
- `require_admin` is the only gate for admin routes — do not add ad-hoc role checks in service layer

**Dynamic pricing boundaries:**
- Never below `settings.pricing_min_multiplier` (0.80) of `base_price`
- Never above `settings.pricing_max_multiplier` (1.30) of `base_price`

**Kafka:**
- All topic name strings come from `settings.kafka_topic_*` — never inline strings
- No PII in event payloads (no email, no full name)
- `order.created` → personalisation worker (highest weight signal)

**Secrets** — `APP_SECRET_KEY`, `JINA_API_KEY`, `NVIDIA_API_KEY`, `STRIPE_SECRET_KEY`, `SENDGRID_API_KEY`, `DATABASE_URL`, `QDRANT_API_KEY` must never appear in committed code.

## Project-Local Skills

| Skill | When to use |
|-------|-------------|
| `code-reviewer` | Before any merge touching auth, SQL generation, agent tools, MCP checkout flow |
| `coder` | Implementing or extending features inside module boundaries |
| `deployment-agent` | Terraform/EC2, Docker, Nginx, health checks, rollback |

```bash
./skills/code-reviewer/scripts/review.py app/auth/      # JWT + password handling
./skills/code-reviewer/scripts/review.py app/search/    # NL-to-SQL safety
./skills/code-reviewer/scripts/review.py app/mcp/       # Tool registry
```

## Build Order

1. Docker Compose stack (Day 1)
2. `auth/` module — register, login, JWT, `get_current_user`, `require_admin` (Day 2)
3. `products/` module + seed data (Days 3–4)
4. `orders/` module + Kafka (Days 5–6)
5. `users/` module — UserPreferences only (Day 7)
6. Real data ingestion — Best Buy + Kaggle + sentiment (Day 8)
7. Semantic search + Qdrant (Day 9)
8. Query router (Day 10)
9. NL-to-SQL engine (Day 11)
10. Hybrid search (Day 12)
11. LangGraph agent + all nodes (Days 13–14)
12. Pricing engine + personalisation worker (Day 15)
13. React frontend + admin analytics dashboard (Days 16–17)
14. Terraform + EC2 deploy (Day 18)

## Performance Targets

| Component | Target |
|-----------|--------|
| Semantic search P95 | < 1s |
| NL-to-SQL generation + execution | < 800ms |
| Query router classification | < 200ms |
| Agent first token | < 2s |
| Kafka event processing lag | < 500ms |
