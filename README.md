# ShopSense

**AI-native product discovery for consumer electronics.**

ShopSense is a production-grade e-commerce platform that replaces keyword search with genuine semantic understanding. A customer types *"laptop for video editing under ₹80K that is light for travel"* and receives a personalised, reasoned comparison — not a list of keyword matches. An admin types *"which brand has the highest average rating this month?"* and gets an answer drawn from live data, not a dashboard they have to navigate themselves.

**Built by Rohit Hebbar · May 2026 · Active Development**

---

## What ShopSense does well

**It understands what you mean, not just what you typed.**
Traditional search fails the moment a customer's words do not match the product title. ShopSense embeds every product — its name, specs, and the most useful things real reviewers said about it — into a semantic vector space. Queries are matched by meaning. A search for "something for creators who travel light" finds the right ultrabooks even if none of them are described as "for creators who travel light" in their listing.

**It knows the difference between a discovery question and a data question.**
Not every query benefits from semantic search. "Which brand has the highest average battery rating?" is a data question — it has a precise, deterministic answer in the database. Sending it through a vector search returns a ranked list of products when what the customer actually wanted was a single number. ShopSense classifies every query before retrieval and routes it to the right engine: vector search for intent-driven discovery, SQL for structured analytics, and a hybrid path — SQL constrains the candidate set, vectors rank within it — for queries that need both.

**It builds a picture of each user without asking them anything.**
Every product view, cart addition, and completed order flows through a Kafka event stream into a personalisation worker that continuously updates each user's preference profile — preferred brands, typical price range, feature priorities. The conversational agent reads this profile before generating any response. A user who has browsed Apple products twice and bought one sees different recommendations than a user who has only looked at budget Windows laptops. Neither user was asked to fill out a preference form.

**Prices respond to demand in real time.**
A background pricing engine reads a 24-hour demand counter maintained in Redis — incremented by every product view event from Kafka — and adjusts prices every two minutes according to configurable rules. High demand and low stock pushes a price up. High abandonment and surplus stock brings it down. Cart totals update automatically when a price changes, because the order module listens to the `price.updated` Kafka topic and recalculates.

**The admin can query the entire catalogue in plain English.**
The analytics module exposes an NL-to-SQL endpoint. An admin types a question, Bedrock Claude Haiku translates it into schema-aware SQL, the query runs against PostgreSQL, and the result comes back as structured data with a one-sentence interpretation. Every query is logged to an audit table that doubles as a fine-tuning dataset for improving SQL generation accuracy over time.

---

## How a customer uses it

A customer arrives at the storefront and sees a product grid — real laptops with real specs, real ratings, and real prices that may have changed minutes ago based on demand. They can browse and filter exactly as they would on any e-commerce site.

When they have something specific in mind, they use the search bar. They type in plain language — a use case, a budget, a constraint — and get semantically ranked results within a second. No keywords required. The results page shows why each product ranked where it did: a sentiment bar for battery life, display quality, build quality, and the other dimensions that matter.

When they want a conversation, they open the ShopSense chat widget. The agent already knows their browsing history from the current session. It classifies their intent — are they discovering, comparing, or ready to buy? — and routes to the right retrieval path. For a discovery question it searches semantically. For a comparison it fetches the specific products and explains the trade-offs. For a question like "is this a good time to buy?" it checks the price history table and tells the customer whether the current price is high or low relative to recent weeks.

When the customer decides, the agent handles the entire checkout without them leaving the conversation. It confirms the product and price, surfaces compatible accessories bought alongside it by other customers, checks their saved payment methods, presents an itemised bill, and waits for an explicit confirmation before processing the payment. After the order is placed it sends a receipt email and tells the customer when to expect delivery.

After delivery, the agent follows up. It asks for a quick rating and a few words about the product — making review collection a natural part of the conversation rather than a separate email campaign. Those reviews flow back into the sentiment pipeline and improve future recommendations.

---

## How the admin uses it

The admin interacts with ShopSense through two surfaces: a dashboard powered by NL-to-SQL, and the same conversational agent available to customers but with elevated permissions.

From the dashboard, the admin asks questions in plain English. Which products are running low on stock? What was the average order value last week? Which search queries returned zero results? The answers come from live data, not from a reporting tool that someone configured months ago and has not been updated since.

Through the agent, the admin takes actions. They can update stock counts, create time-limited discounts, adjust pricing rules, and query sales performance — all in natural language, all with a confirmation step before any write operation executes. The agent explains what it is about to do and waits for approval.

---

## Architecture

### High-Level System

![High Level System Architecture](assets/high_level_system_architecture.png)

### Retrieval Architecture

![Retrieval Architecture](assets/retrieval_architecture.png)

Every query is classified before retrieval:

* **SEMANTIC** → Jina v3 embeddings → Qdrant vector search → flashrank reranker
* **ANALYTICAL** → Bedrock Claude Haiku → schema-aware SQL → PostgreSQL
* **HYBRID** → SQL constrains the candidate set, vector search ranks within it

The query router (Bedrock Haiku, ~150ms) makes this decision. This is the correct architecture — vector search alone cannot answer "which brand has the highest average rating?", and SQL alone cannot capture "laptop that feels premium".

### Event-Driven Architecture

![Event Driven Architecture](assets/event_driven_architecture.png)

Five Kafka topics wire the system together:

| Topic               | Producer        | Consumers                                                    |
| ------------------- | --------------- | ------------------------------------------------------------ |
| `product.viewed`  | products module | search module (Redis demand counter), personalisation worker |
| `product.created` | products module | embedding worker                                             |
| `cart.updated`    | orders module   | personalisation worker                                       |
| `order.created`   | orders module   | personalisation worker (highest weight signal)               |
| `price.updated`   | pricing engine  | orders module (recalculates active cart totals)              |

---

## Tech Stack

| Layer         | Technology                                     | Why                                                                                         |
| ------------- | ---------------------------------------------- | ------------------------------------------------------------------------------------------- |
| API           | FastAPI + Python 3.11                          | Async, typed, fast                                                                          |
| LLM           | Amazon Bedrock (Claude Sonnet 4.5 / Haiku 4.5) | IAM auth, no key rotation, eu-north-1 inference profiles                                    |
| Embeddings    | Jina v3 (`jina-embeddings-v3`)               | 1024-dim, separate query/passage task modes, best retrieval quality in three-way smoke test |
| Vector DB     | Qdrant Cloud                                   | Cosine similarity with metadata payload filtering                                           |
| Database      | PostgreSQL via Supabase                        | Products, orders, users, reviews, price history, NL-to-SQL audit log                        |
| Cache         | Redis                                          | Cart state (7-day TTL), live price cache (10-min TTL), demand counters (24-hour TTL)        |
| Event bus     | Apache Kafka                                   | Decoupled demand signals, real-time price recalculation, personalisation updates            |
| ORM           | SQLAlchemy 2.0 async                           | Mapped columns, async session                                                               |
| Auth          | JWT HS256 + bcrypt                             | Stateless, role-aware (customer / admin)                                                    |
| Reranker      | flashrank                                      | Local cross-encoder, no API cost                                                            |
| Agent         | LangGraph                                      | Stateful multi-node graph, streaming SSE                                                    |
| Infra         | Terraform + AWS EC2                            | Reproducible, free-tier deployable                                                          |
| Observability | LangSmith                                      | Full agent trace per conversation                                                           |

---

## Data Pipeline

**21,173 real laptop products** sourced from Amazon product metadata and Kaggle datasets, deduplicated by name and enriched through a multi-stage pipeline.

**129,765 reviews** streamed from the McAuley Lab Amazon Reviews 2023 dataset and matched to products via fuzzy name matching. Unmatched products receive synthetic reviews generated with Faker.

**1,503 products sentiment-scored** via Bedrock Claude Haiku. Each product receives seven aspect sentiment scores — battery, display, build quality, value, performance, keyboard, thermal — plus a `top_complaint` and `top_praise` extracted from its reviews. Scores are stored on the products table and feed directly into the Qdrant payload, the recommendation logic, and the sentiment bars shown on product pages.

**1,503 products embedded** with Jina v3 at 1024 dimensions and upserted to Qdrant Cloud with full metadata payload. Remaining products are embedded on demand when first viewed, via a lazy scoring worker that queues the embedding job in Redis without blocking the product page response.

Provider selection rationale: three-way smoke test across Jina, NVIDIA, and Bedrock Titan Embeddings on ten representative queries. Jina was the only provider to rank both expected results in the top two for the "lightweight travel" query. Its separate `retrieval.query` and `retrieval.passage` task modes provide a structural advantage for asymmetric retrieval — short natural language queries against long product descriptions.

---

## Key Design Decisions

**Modular monolith over microservices.** One person, unstable domain boundaries, no scaling problem yet. Microservices would add two weeks of infrastructure overhead with no user-facing benefit at this stage. The modules have clean internal boundaries and can be extracted into independent services later when a specific scaling problem justifies it.

**Vectorless RAG for analytical queries.** The NL-to-SQL path is Vectorless RAG — the LLM decomposes the query into structured SQL filters, the database returns deterministic results, no embeddings involved. This is the right approach for questions where precision matters more than semantic similarity. Vector search is reserved for discovery queries where intent cannot be expressed as a structured filter.

**Bedrock over third-party LLM APIs.** IAM-based authentication means no API key rotation, no rate limit surprises that differ between environments, and automatic cross-region redundancy via inference profile IDs (`eu.anthropic.*`). The same IAM role that accesses EC2 accesses Bedrock — one authentication model for the entire system.

**JSONB for cart and order items.** Cart state lives in Redis, not a database table. Order items are JSONB snapshots — the price at checkout is captured permanently regardless of future schema migrations or price changes. This is preferable to a separate `order_items` table because the snapshot semantics are explicit in the data model.

**Human-in-the-loop before every write in the agent.** The checkout agent proposes every action — add to cart, apply coupon, process payment — and waits for an unambiguous confirmation before executing. Ambiguous responses trigger clarification. Only a clear affirmative triggers a write. This is an architectural constraint, not a safety feature bolted on after the fact.

---

## Getting Started

### Prerequisites

* Python 3.11+, Docker + Docker Compose, [`uv`](https://github.com/astral-sh/uv)
* AWS account with Bedrock access in eu-north-1
* Jina API key — [jina.ai](https://jina.ai/) (free tier)
* Supabase project — [supabase.com](https://supabase.com/) (free tier)
* Qdrant Cloud cluster — [cloud.qdrant.io](https://cloud.qdrant.io/) (free tier)

### Setup

```bash
git clone https://github.com/your-username/shopsense.git
cd shopsense

# Install dependencies
make install

# Configure environment
cp .env.example .env
# Fill in: DATABASE_URL, JINA_API_KEY, AWS_REGION, QDRANT_URL, QDRANT_API_KEY, APP_SECRET_KEY

# Start infrastructure
make dev
# PostgreSQL · Redis · Kafka · Kafka UI (localhost:8080) · Qdrant

# Apply migrations
supabase db push

# Run the data pipeline
make ingest

# Start the API
make run
# API:      http://localhost:8000
# Docs:     http://localhost:8000/docs
# Kafka UI: http://localhost:8080
```

### Environment Variables

```env
DATABASE_URL=postgresql+asyncpg://...
MIRROR_DATABASE_URL=postgresql+asyncpg://...   # Local Docker postgres, ingestion only
JINA_API_KEY=jina_...
AWS_REGION=eu-north-1
BEDROCK_GENERATION_MODEL_ID=eu.anthropic.claude-sonnet-4-5-20250929-v1:0
BEDROCK_FAST_MODEL_ID=eu.anthropic.claude-haiku-4-5-20251001-v1:0
QDRANT_URL=https://...cloud.qdrant.io
QDRANT_API_KEY=...
APP_SECRET_KEY=...    # openssl rand -hex 32
```

### Running Tests

```bash
make test                               # Full suite with coverage
make test-module module=orders          # Scope to one module
```

---

## Project Structure

```
shopsense/
├── app/
│   ├── auth/           # JWT, bcrypt, get_current_user, require_admin
│   ├── products/       # Catalogue CRUD, Kafka producer
│   ├── orders/         # Cart (Redis), orders (PostgreSQL), Kafka consumer
│   ├── users/          # UserPreferences — written by worker, read by agent
│   ├── search/         # Embedder, Qdrant, query router, NL-to-SQL, pricing engine
│   ├── agent/          # LangGraph graph, all nodes, streaming /chat endpoint
│   ├── analytics/      # Admin NL-to-SQL endpoints
│   ├── mcp/            # MCP server (port 8006), checkout tools
│   └── schemas/        # Shared Pydantic schemas at LLM boundaries
├── workers/
│   ├── pricing_engine.py       # 120-second cycle, demand → price adjustments
│   └── personalisation.py      # Kafka consumer → UserPreferences updates
├── data/ingestion/             # One-time data pipeline scripts
├── database/migrations/        # Numbered SQL migration files
├── tests/                      # pytest, mirrored module structure
├── terraform/                  # EC2, security groups, Elastic IP, S3 state backend
└── docker-compose.yml          # Full local stack
```

---

## API Reference

### Auth

```
POST /auth/register        Register a new account
POST /auth/login           Authenticate and return JWT
GET  /auth/me              Current authenticated user
```

### Products

```
GET  /api/products         Paginated catalogue with filters
GET  /api/products/{id}    Product detail, reviews, fires product.viewed event
POST /api/products         Admin: create product
```

### Orders

```
POST   /api/orders/cart/add          Add item — reads live price from Redis
DELETE /api/orders/cart/remove       Remove item
GET    /api/orders/cart/{user_id}    Current cart with live totals
POST   /api/orders/orders            Checkout — publishes order.created
GET    /api/orders/orders/{id}       Order detail
```

### Search and Agent

```
POST /api/search           Semantic · analytical · hybrid retrieval
POST /api/chat             Streaming conversational agent (SSE)
POST /api/analytics/query  Admin NL-to-SQL — plain English → live data
```

---

## License

MIT
