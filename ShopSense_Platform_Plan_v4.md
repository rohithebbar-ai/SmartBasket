# ShopSense — AI-Native Product Discovery Platform

### Architecture, Build Plan & Technical Specification

**Version:** 4.0 | **Date:** May 2026 | **Author:** Rohit Hebbar | **Status:** Active Development

> **v4.0 changes:** Added Section 20 — complete scaffold decisions (Q1–Q12), full `.env.example` specification, auth module design, Kafka topic env vars, Bedrock + embedding provider config, JWT auth flow. Replaced Groq with Amazon Bedrock. Replaced all-MiniLM-L6-v2 with Jina / NVIDIA embeddings (provider selected at runtime). v3.0 added tool calling and MCP. v2.0 added monolith, NL-to-SQL, Terraform.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Monolith vs Microservices — The Decision](#2-monolith-vs-microservices--the-decision)
3. [High-Level Architecture Diagram](#3-high-level-architecture-diagram)
4. [Module Specifications](#4-module-specifications)
5. [NL-to-SQL Hybrid Retrieval Layer](#5-nl-to-sql-hybrid-retrieval-layer)
6. [LangGraph Agent — Updated Flow](#6-langgraph-agent--updated-flow)
7. [Kafka Event Architecture](#7-kafka-event-architecture)
8. [Database Schema](#8-database-schema)
9. [LLM Schema &amp; Prompts](#9-llm-schema--prompts)
10. [End-to-End Product Lifecycle](#10-end-to-end-product-lifecycle)
11. [AI Layers — Implementation Details](#11-ai-layers--implementation-details)
12. [Data Strategy](#12-data-strategy)
13. [Repository Structure](#13-repository-structure)
14. [Terraform Deployment Guide](#14-terraform-deployment-guide)
15. [Cost Analysis](#15-cost-analysis)
16. [Build Roadmap](#16-build-roadmap)
17. [GenAI Learning Outcomes](#17-genai-learning-outcomes)
18. [Success Criteria &amp; Evaluation](#18-success-criteria--evaluation)
19. [Agentic Tool Calling — MCP Server &amp; Full Tool Registry](#19-agentic-tool-calling--shopsense-as-an-action-taking-agent)
20. [Scaffold Decisions, Environment Config &amp; Auth Design](#20-scaffold-decisions-environment-config--auth-design)

---

## 1. Project Overview

### What is ShopSense?

ShopSense is an AI-native product discovery platform for consumer electronics. It replaces keyword search with semantic understanding, adds a conversational discovery agent, and uses real-time demand signals to adjust prices. A customer types _"laptop for video editing under ₹80K that is light for travel"_ and receives a personalised comparison — the same capability Amazon built internally as Rufus, built as an open platform any retailer can embed.

### Core Problems Solved

| Problem                           | Before                                   | After                                                        |
| --------------------------------- | ---------------------------------------- | ------------------------------------------------------------ |
| **Keyword mismatch**        | "laptop for video editing" → 0 results  | Semantic search understands intent                           |
| **No structured analytics** | Admin cannot query data in plain English | NL-to-SQL answers "which brand has highest ratings?"         |
| **No reasoning**            | Star ratings hide what is actually wrong | Aspect-based sentiment extracts feature signals              |
| **No personalisation**      | Same results for everyone                | Kafka event stream builds real-time user preference profiles |
| **Static pricing**          | Price set once, never adjusts            | Dynamic pricing engine reads demand signals every 2 minutes  |

---

## 2. Monolith vs Microservices — The Decision

### Decision: Modular Monolith

ShopSense v2.0 is built as a **modular monolith**, not microservices. This is a deliberate engineering decision, not a shortcut.

```mermaid
graph LR
    subgraph Monolith["Modular Monolith — ShopSense Choice"]
        A[Single FastAPI App] --> B[products/ module]
        A --> C[orders/ module]
        A --> D[users/ module]
        A --> E[search/ module]
        A --> F[agent/ module]
        A --> G[analytics/ module]
    end

    subgraph Microservices["Microservices — Too Early"]
        H[product-service :8001]
        I[order-service :8002]
        J[user-service :8003]
        K[search-service :8004]
        L[agent-service :8005]
        H -.->|HTTP call| K
        K -.->|HTTP call| L
    end
```

### Why Monolith is the Right Call Here

**You are one person.** Microservices exist to let independent teams deploy independently without stepping on each other. Five separate Docker containers, five deployment units, inter-service HTTP calls, and distributed tracing across services adds two weeks of infrastructure overhead with zero user-facing benefit.

**The domain is not yet stable.** Getting service boundaries wrong in a microservices system creates a distributed monolith — the worst of both worlds. A modular monolith lets you refactor module boundaries cheaply.

**One genuine exception:** the AI agent runs as a **separate worker process** (not a separate service) because LangGraph workflows are slow, stateful, and should not block the FastAPI web server thread. This is a process separation, not a service separation — same codebase, same deployment, different process.

### What Monolith Means in Practice

- Single `main.py` FastAPI application
- Modules in separate folders: `app/products/`, `app/orders/`, `app/search/`, `app/agent/`, `app/analytics/`
- Each module has its own router, models, schemas, and services — clean separation of concerns
- Kafka still runs as a Docker container — the monolith produces and consumes events
- Single Docker image, single EC2 deployment, single `terraform apply`

### When to Extract to Microservices

Extract a module into a service only when a specific, measurable scaling problem demands it:

- Search module gets 100x the traffic of order module → extract search
- Agent module needs a GPU while the rest runs on CPU → extract agent
- Different teams own different modules → extract for deployment independence

---

## 3. High-Level Architecture Diagram

```mermaid
graph TB
    subgraph Client["Client Layer"]
        WEB[React Storefront\nVite + TypeScript\nVercel]
    end

    subgraph Gateway["Gateway"]
        NGINX[Nginx\nPort 80/443\nJWT validation + routing]
    end

    subgraph App["Modular Monolith — Single FastAPI App on EC2"]
        direction TB
        PRODUCTS[products module\nCatalogue CRUD\nKafka producer]
        ORDERS[orders module\nCart + Orders\nKafka consumer]
        USERS[users module\nProfiles + Preferences]
        SEARCH[search module\nSemantic search\nNL-to-SQL router\nPricing engine]
        AGENT[agent module\nLangGraph orchestrator\nStreaming responses]
        ANALYTICS[analytics module\nAdmin dashboard queries\nNL-to-SQL endpoint]
    end

    subgraph AILayer["AI Layer"]
        ROUTER[Query Router\nSEMANTIC vs ANALYTICAL\nvs HYBRID]
        BEDROCK["Amazon Bedrock\nClaude 3.5 Sonnet (generation)\nClaude 3 Haiku (fast tasks)"]
        EMBEDDER[Embedding Service\nJina or NVIDIA\nProvider set by env var]
        RERANKER[flashrank\nCross-encoder reranker\nLocal]
        NLSQL[NL-to-SQL Engine\nSchema-aware generation\nValidation + retry loop]
    end

    subgraph Storage["Storage"]
        PG[(PostgreSQL\nSupabase\nProducts, Orders, Users)]
        QDRANT[(Qdrant\nVector DB\nProduct Embeddings)]
        REDIS[(Redis\nSessions, Cache\nDemand Counters)]
    end

    subgraph Events["Event Bus"]
        KAFKA[Apache Kafka\nDocker container\n4 topics]
        KAFKAUI[Kafka UI\nPort 8080]
    end

    subgraph Workers["Background Workers\nSeparate processes, same codebase"]
        PRICING[Pricing Engine\nRuns every 2 min]
        PERSONALI[Personalisation Worker\nKafka consumer]
    end

    subgraph Observability["Observability"]
        LANGSMITH[LangSmith\nAgent traces]
        PROMETHEUS[Prometheus\nMetrics]
        GRAFANA[Grafana\nDashboards]
    end

    subgraph Infra["AWS Infrastructure — Managed by Terraform"]
        EC2[EC2 t2.micro\nFree tier 12 months]
        SG[Security Groups\nPort 80/443 open\nPort 22 restricted]
        EIP[Elastic IP\nStatic public address]
        S3_TF[S3 Bucket\nTerraform state file]
    end

    WEB --> NGINX
    NGINX --> App
    AGENT --> ROUTER
    ROUTER --> EMBEDDER
    ROUTER --> NLSQL
    ROUTER --> GROQ
    EMBEDDER --> QDRANT
    NLSQL --> PG
    GROQ --> RERANKER
    PRODUCTS --> PG
    ORDERS --> PG
    USERS --> PG
    ORDERS --> REDIS
    SEARCH --> REDIS
    PRODUCTS --> KAFKA
    ORDERS --> KAFKA
    KAFKA --> PRICING
    KAFKA --> PERSONALI
    KAFKA --> KAFKAUI
    PRICING --> REDIS
    PERSONALI --> PG
    AGENT --> LANGSMITH
    App --> PROMETHEUS
    PROMETHEUS --> GRAFANA
    App --> EC2
    EC2 --> SG
    EC2 --> EIP
```

---

## 4. Module Specifications

### 4.1 products module — `app/products/`

The source of truth for the product catalogue. Every other module references product IDs from here.

**Key files:** `router.py` (FastAPI routes), `models.py` (SQLAlchemy), `schemas.py` (Pydantic), `kafka.py` (event producer), `service.py` (business logic)

**Endpoints:**

| Method   | Path                       | Auth     | Description                                                                 |
| -------- | -------------------------- | -------- | --------------------------------------------------------------------------- |
| `GET`  | `/products`              | Public   | Paginated list with filters. Reads `current_price` from Redis cache first |
| `GET`  | `/products/{id}`         | Public   | Full detail + reviews. Publishes `product.viewed` to Kafka                |
| `POST` | `/products`              | Admin    | Create product. Triggers async embedding generation                         |
| `PUT`  | `/products/{id}/price`   | Internal | Called by pricing engine only                                               |
| `GET`  | `/products/{id}/reviews` | Public   | Reviews with aspect sentiment scores                                        |

**Kafka events published:** `product.viewed`, `product.created`

---

### 4.2 orders module — `app/orders/`

Cart lifecycle and order processing. Cart state lives in Redis (fast, temporary). Orders live in PostgreSQL (permanent, queryable).

**Key design:** When adding to cart, reads `current_price:{product_id}` from Redis so cart always shows the live dynamic price. The Kafka consumer for `price.updated` automatically recalculates active cart totals.

**Kafka events published:** `cart.updated`, `order.created`
**Kafka topics consumed:** `price.updated`

---

### 4.3 users module — `app/users/`

User accounts and preference profiles. The preference profile is the personalisation data the AI agent reads before generating recommendations.

The profile is **written** by the personalisation worker (based on Kafka event history) and **read** by the agent module. It stores: preferred brands, preferred categories, typical price range, and feature priorities (battery, portability, display quality — inferred from which products the user engaged with most).

---

### 4.4 search module — `app/search/`

The AI search layer. Contains three sub-components that work together:

**Semantic search:** Generates query embeddings with Jina or NVIDIA embeddings (provider set by EMBEDDING_PROVIDER env var), searches Qdrant with metadata filters, reranks with flashrank. Used for discovery queries.

**NL-to-SQL:** Schema-aware SQL generation for analytical queries. Uses Bedrock Claude Haiku to generate SQL from natural language, validates it with `sqlparse`, executes against PostgreSQL. Used for structured data questions.

**Query router:** Classifies every incoming query as SEMANTIC, ANALYTICAL, or HYBRID before routing to the right retrieval path. This is the key architectural decision explained in full in Section 5.

**Pricing engine:** Background task running every 120 seconds, reads demand counters from Redis, adjusts prices, publishes `price.updated` events.

**Kafka topics consumed:** `product.viewed` → increments `views:{product_id}` in Redis

---

### 4.5 agent module — `app/agent/`

The ShopSense conversational AI. Runs as a separate process from the web server using FastAPI's background process support, so LangGraph workflows do not block web requests.

LangGraph orchestrates: load context → classify intent → route to retrieval (semantic, NL-to-SQL, or hybrid) → personalise results → synthesise response → stream back.

Conversation history is stored in Redis per session (last 10 turns). Full LangSmith tracing on every interaction.

---

### 4.6 analytics module — `app/analytics/`

Admin-only endpoints that expose NL-to-SQL for business intelligence queries. The store admin asks questions in plain English and gets structured data back.

**Example queries this module handles:**

- "Which brands have the highest average rating?" → SQL aggregation
- "Show me products that are out of stock" → SQL filter
- "What is the average price per category?" → SQL GROUP BY
- "Which products have had the most price changes this week?" → SQL join with price_history

---

## 5. NL-to-SQL Hybrid Retrieval Layer

### 5.1 The Core Insight — Two Fundamentally Different Query Types

ShopSense has two types of user queries that need completely different retrieval approaches:

```mermaid
graph TD
    QUERY[User Query] --> ROUTER{Query Router\nClassify intent\nBedrock Claude Haiku\n~200ms}

    ROUTER -->|Discovery intent\n'laptop for video editing'\n'something good for gaming'| SEMANTIC[Semantic Path\nQdrant vector search\nflashrank reranker\nReturns: ranked products]

    ROUTER -->|Analytical intent\n'which brand has best ratings'\n'show out of stock items'| SQL[Analytical Path\nNL-to-SQL generation\nPostgreSQL query\nReturns: structured data]

    ROUTER -->|Hybrid intent\n'best rated laptops\nunder 80K with good battery'| HYBRID[Hybrid Path\nSQL for price + rating filters\nVector search for battery sentiment\nMerge and rerank results]

    SEMANTIC --> SYNTH[Response Synthesis\nBedrock Claude Sonnet]
    SQL --> SYNTH
    HYBRID --> SYNTH

    SYNTH --> STREAM[Streaming Response\nto customer]
```

**Why vector search alone is not enough:** "Which brand has the highest average rating?" is a pure aggregation query. Vector search returns semantically similar products — it cannot answer an aggregation question. SQL trivially answers it in under 10ms.

**Why SQL alone is not enough:** "Laptop for video editing" has no SQL expression. No column is named `good_for_video_editing`. Only semantic similarity over product descriptions and review text can capture this intent.

**Why you need both:** "Best rated Dell laptops under ₹80K with good battery reviews" needs SQL for `brand = 'Dell' AND avg_rating > 4.0 AND current_price < 80000` AND vector search for the `good battery reviews` part.

---

### 5.2 The Query Router

The router is a single LangGraph node that runs before every query. It calls Bedrock Claude Haiku with a short classification prompt and returns the query type in under 150ms.

```python
QUERY_ROUTER_PROMPT = """
Classify this shopping query into exactly one category.

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

Respond with JSON only:
{"type": "SEMANTIC", "reasoning": "exploratory discovery, no structured constraints"}
"""
```

---

### 5.3 The NL-to-SQL Engine

For ANALYTICAL and HYBRID queries, the NL-to-SQL engine generates safe, validated SQL against the ShopSense PostgreSQL schema.

**Schema injection:** The full table definitions are injected into every prompt so the model knows the exact column names, types, and JSONB access patterns.

```python
NL_TO_SQL_PROMPT = """
You are a SQL expert for the ShopSense e-commerce platform.
Database: PostgreSQL (Supabase)

Tables and columns:
  products(id UUID, name VARCHAR, brand VARCHAR, category VARCHAR,
           base_price DECIMAL, current_price DECIMAL, specs JSONB,
           stock_count INTEGER, avg_rating FLOAT, is_active BOOLEAN,
           created_at TIMESTAMP)

  reviews(id UUID, product_id UUID FK→products.id, rating INTEGER 1-5,
          review_text TEXT, battery_sentiment FLOAT, display_sentiment FLOAT,
          build_quality_sentiment FLOAT, value_sentiment FLOAT,
          performance_sentiment FLOAT, created_at TIMESTAMP)

  orders(id UUID, user_id UUID, items JSONB, total_amount DECIMAL,
         status VARCHAR, created_at TIMESTAMP)

  price_history(id UUID, product_id UUID FK→products.id, old_price DECIMAL,
                new_price DECIMAL, change_percentage FLOAT,
                reason VARCHAR, changed_at TIMESTAMP)

JSONB access syntax: specs->>'ram_gb', specs->>'weight_kg'
Cast JSONB to numeric: (specs->>'ram_gb')::NUMERIC

Rules:
  1. Generate SELECT queries ONLY. Never UPDATE, DELETE, DROP, INSERT.
  2. Always add LIMIT 50 unless user explicitly asks for all.
  3. Use parameterised-style queries — no user input interpolated directly.
  4. For spec comparisons use JSONB operators correctly.
  5. Always filter is_active = true for product queries.

Question: {question}

Return SQL only, no explanation, no markdown:
"""
```

**Validation loop:** Generated SQL is validated with `sqlparse` before execution. If it contains mutating keywords or fails to parse as SELECT, it is sent back to the LLM with the error for correction. Maximum 2 retries.

```python
def validate_sql(sql: str) -> tuple[bool, str]:
    """Validate SQL is safe SELECT before executing."""
    parsed = sqlparse.parse(sql)
    if not parsed:
        return False, "Could not parse SQL"

    statement = parsed[0]
    if statement.get_type() != 'SELECT':
        return False, f"Expected SELECT, got {statement.get_type()}"

    # Check for dangerous keywords
    dangerous = ['DROP', 'DELETE', 'UPDATE', 'INSERT', 'ALTER', 'TRUNCATE']
    sql_upper = sql.upper()
    for keyword in dangerous:
        if keyword in sql_upper:
            return False, f"Dangerous keyword found: {keyword}"

    return True, "Valid"
```

---

### 5.4 The HYBRID Path — Combining Both

For hybrid queries, both retrieval paths run and their results are merged:

```python
async def hybrid_search(query: str, filters: dict) -> list:
    # Step 1: NL-to-SQL for structured constraints
    sql_results = await nl_to_sql_search(
        f"Show products where {filters.get('price_constraint', '')} "
        f"and rating > {filters.get('min_rating', 4.0)}"
    )
    # Returns: set of product_ids matching structured criteria

    # Step 2: Semantic search for intent matching
    vector_results = await semantic_search(
        query=query,
        pre_filter_ids=sql_results  # Only search within SQL result set
    )
    # Returns: semantically ranked subset of sql_results

    # Step 3: Merge — SQL filters the candidates, vector search ranks them
    return vector_results  # Already filtered by SQL constraints
```

This is the correct architecture for hybrid retrieval: SQL reduces the candidate set, vector search ranks within it. Not two separate lists that need reconciling — one constrains the other.

---

### 5.5 What NL-to-SQL Adds to the Portfolio Story

Without NL-to-SQL, ShopSense serves customers only. With NL-to-SQL, it also serves the **store admin and business owner** who need analytics without writing SQL.

Resume line: *"Built a hybrid retrieval system combining Qdrant semantic search and schema-aware NL-to-SQL with a LangGraph query router — classifies intent in 150ms and routes to the correct retrieval path. SQL validation loop prevents unsafe queries. HYBRID path constrains vector search candidates using SQL filters for deterministic + semantic results."*

---

## 6. LangGraph Agent — Updated Flow

The agent now has three retrieval paths instead of one. The query router determines which path runs.

```mermaid
flowchart TD
    START([User Message\n+ session_id + user_id]) --> LOAD[Load Context\nRedis: last 10 turns\nPostgreSQL: user preferences]

    LOAD --> CLASSIFY[classify_intent\nclaude-3-haiku (Bedrock)\nPRODUCT_SEARCH / COMPARE\nEXPLAIN / OUT_OF_SCOPE]

    CLASSIFY --> ROUTE_INTENT{Intent Router}

    ROUTE_INTENT -->|PRODUCT_SEARCH\nor EXPLAIN| QUERY_ROUTER[query_type_router\nclaude-3-haiku (Bedrock)\nSEMANTIC / ANALYTICAL / HYBRID]

    ROUTE_INTENT -->|PRODUCT_COMPARE| COMPARE[fetch and compare\n2-3 products\nSide-by-side analysis]

    ROUTE_INTENT -->|OUT_OF_SCOPE| REFUSE[Polite refusal\nNo LLM call]

    QUERY_ROUTER -->|SEMANTIC| SEM[semantic_search\nQdrant + flashrank\nTop 10 products]

    QUERY_ROUTER -->|ANALYTICAL| ANAL[nl_to_sql_search\nGenerate SQL\nValidate\nExecute on PostgreSQL]

    QUERY_ROUTER -->|HYBRID| HYB[hybrid_search\nSQL constrains candidates\nVector search ranks\nMerge results]

    SEM --> PERSONAL[personalise\nBoost preferred brands\nAdjust by price range]
    ANAL --> SYNTH
    HYB --> PERSONAL
    COMPARE --> SYNTH

    PERSONAL --> SYNTH[synthesise_response\nclaude-3-5-sonnet (Bedrock)\nStream token by token]

    SYNTH --> SAVE[save_history\nRedis: history:session_id\nAppend turn]

    SAVE --> END([Streaming Response])
    REFUSE --> END

    SYNTH -.->|Full trace| LANGSMITH[LangSmith\nAll nodes traced]
```

**Updated ShopSenseState:**

```python
class ShopSenseState(TypedDict):
    messages: List[BaseMessage]      # Conversation history
    intent: str                      # PRODUCT_SEARCH, COMPARE, EXPLAIN, OUT_OF_SCOPE
    query_type: str                  # SEMANTIC, ANALYTICAL, HYBRID
    search_results: List[Dict]       # From semantic or hybrid path
    sql_results: List[Dict]          # From analytical path
    generated_sql: str               # For audit/debugging
    user_preferences: Dict           # From users module
    session_id: str
    user_id: str
    final_response: str
    sources: List[str]               # Product IDs or table names cited
```

---

## 7. Kafka Event Architecture

### 7.1 Topics

```mermaid
graph LR
    subgraph Producers
        P1[products module] -->|product.viewed| T1[product.viewed\nPartitions: 3\n7 day retention]
        P1 -->|product.created| T1
        P2[orders module] -->|cart.updated| T2[cart.updated\nPartitions: 3\n7 day retention]
        P2 -->|order.created| T3[order.created\nPartitions: 3\n30 day retention]
        P3[pricing engine] -->|price.updated| T4[price.updated\nPartitions: 1\n24h retention]
    end

    subgraph Consumers
        T1 -->|INCR views counter| C1[search module\nRedis demand signal]
        T1 -->|update profile| C2[personalisation worker]
        T2 -->|update profile| C2
        T3 -->|update profile\nhighest weight| C2
        T4 -->|recalc cart totals| C3[orders module]
    end
```

### 7.2 Event Payloads

**product.viewed**

```json
{
  "event_type": "product.viewed",
  "product_id": "prod_abc123",
  "user_id": "usr_456",
  "session_id": "sess_789",
  "source": "search_results",
  "timestamp": "2026-05-09T10:15:00Z"
}
```

**price.updated**

```json
{
  "event_type": "price.updated",
  "product_id": "prod_abc123",
  "old_price": 75000,
  "new_price": 78750,
  "change_percentage": 5.0,
  "reason": "high_demand",
  "timestamp": "2026-05-09T10:35:00Z"
}
```

---

## 8. Database Schema

### 8.1 PostgreSQL (Supabase)

```mermaid
erDiagram
    PRODUCTS {
        uuid id PK
        string name
        string brand
        string category
        decimal base_price
        decimal current_price
        jsonb specs
        integer stock_count
        float avg_rating
        boolean is_active
        timestamp created_at
    }
    REVIEWS {
        uuid id PK
        uuid product_id FK
        integer rating
        text review_text
        float battery_sentiment
        float display_sentiment
        float build_quality_sentiment
        float value_sentiment
        float performance_sentiment
        timestamp created_at
    }
    USERS {
        uuid id PK
        string email
        string name
        string password_hash
        string role
        timestamp created_at
    }
    USER_PREFERENCES {
        uuid id PK
        uuid user_id FK
        jsonb preferred_brands
        jsonb preferred_categories
        decimal typical_price_min
        decimal typical_price_max
        jsonb feature_priorities
        timestamp last_updated
    }
    ORDERS {
        uuid id PK
        uuid user_id FK
        jsonb items
        decimal total_amount
        string status
        timestamp created_at
    }
    PRICE_HISTORY {
        uuid id PK
        uuid product_id FK
        decimal old_price
        decimal new_price
        float change_percentage
        string reason
        timestamp changed_at
    }
    NL_SQL_AUDIT {
        uuid id PK
        string natural_language_query
        string generated_sql
        integer rows_returned
        boolean validation_passed
        integer retry_count
        timestamp created_at
    }

    PRODUCTS ||--o{ REVIEWS : has
    PRODUCTS ||--o{ PRICE_HISTORY : has
    USERS ||--o{ ORDERS : places
    USERS ||--|| USER_PREFERENCES : has
```

> **NL_SQL_AUDIT table** — logs every NL-to-SQL query, the generated SQL, and whether validation passed. After 500+ rows, this table becomes training data for a fine-tuned NL-to-SQL model specific to your schema.

### 8.2 Redis Key Design

| Key Pattern                    | Type             | TTL    | Purpose                        |
| ------------------------------ | ---------------- | ------ | ------------------------------ |
| `cart:{user_id}`             | Hash             | 7 days | Cart items with prices         |
| `current_price:{product_id}` | String           | 10 min | Live price from pricing engine |
| `views:{product_id}`         | String (counter) | 24h    | Demand signal for pricing      |
| `history:{session_id}`       | List             | 1h     | Last 10 conversation turns     |
| `search_cache:{query_hash}`  | String JSON      | 1h     | Cached semantic search results |
| `sql_cache:{query_hash}`     | String JSON      | 30 min | Cached NL-to-SQL results       |
| `prefs_cache:{user_id}`      | String JSON      | 30 min | User preference profile cache  |

### 8.3 Qdrant Collection

```
Collection: products
Dimensions: 1024 (Jina jina-embeddings-v3 or NVIDIA nv-embedqa-e5-v5 — set by EMBEDDING_PROVIDER env var)
Distance: Cosine

Text embedded per product:
"{name} {brand} {category} {specs as readable sentences} {top review highlights}"

Payload metadata (for filtering):
{
  product_id, name, brand, category,
  price, avg_rating, stock_available,
  battery_sentiment, display_sentiment,
  build_quality_sentiment, value_sentiment, performance_sentiment,
  use_cases: ["video_editing", "development", "gaming"],
  key_specs: {ram_gb, storage_gb, display_inches, battery_wh, weight_kg}
}
```

---

## 9. LLM Schema & Prompts

### 9.1 Model Usage

| Task                     | Model                                         | Path                | Avg Latency |
| ------------------------ | --------------------------------------------- | ------------------- | ----------- |
| Intent classification    | `claude-3-haiku-20240307-v1:0 (Bedrock)`    | All queries         | ~200ms      |
| Query type routing       | `claude-3-haiku-20240307-v1:0 (Bedrock)`    | PRODUCT_SEARCH      | ~150ms      |
| NL-to-SQL generation     | `claude-3-haiku-20240307-v1:0 (Bedrock)`    | ANALYTICAL / HYBRID | ~300ms      |
| Filter extraction        | `claude-3-haiku-20240307-v1:0 (Bedrock)`    | SEMANTIC            | ~300ms      |
| Response synthesis       | `claude-3-5-sonnet-20241022-v2:0 (Bedrock)` | All paths           | ~1.2–1.5s  |
| Aspect sentiment (batch) | `claude-3-5-sonnet-20241022-v2:0 (Bedrock)` | Ingestion only      | Batch       |

### 9.2 Filter Extraction Prompt (Semantic Path)

```python
FILTER_EXTRACTION_PROMPT = """
Extract structured product filters from this shopping query.
Return JSON only. Use null for any field not mentioned.

Query: {query}

Return:
{
  "max_price": 80000,
  "min_price": null,
  "brand": null,
  "category": "laptops",
  "use_case": "video editing",
  "features": ["light weight", "good battery"],
  "rewritten_query": "portable laptop for video editing content creation"
}
"""
```

### 9.3 Response Synthesis Prompt

```python
RESPONSE_SYNTHESIS_PROMPT = """
You are ShopSense, an intelligent product advisor.

Customer query: {query}
Customer preferences: {preferences}
Retrieved data: {results_json}
Retrieval method: {method}  # SEMANTIC, ANALYTICAL, or HYBRID

For SEMANTIC results: write a warm, conversational product recommendation.
For ANALYTICAL results: present the data clearly with a brief insight.
For HYBRID results: lead with the data finding, then explain the products.

Rules:
- Respect budget constraints always
- Cite specific specs and review scores, not generic descriptions
- Maximum 3 paragraphs
- No bullet points
"""
```

### 9.4 Aspect Sentiment Prompt (Batch Ingestion)

```python
ASPECT_SENTIMENT_PROMPT = """
Analyse these product reviews and extract sentiment scores from 1.0 to 5.0.
Return JSON only.

Reviews: {reviews_text}

Return:
{
  "battery_sentiment": 3.8,
  "display_sentiment": 4.7,
  "build_quality_sentiment": 4.2,
  "value_sentiment": 3.5,
  "performance_sentiment": 4.6,
  "keyboard_sentiment": 4.0,
  "thermal_sentiment": 3.2,
  "top_complaint": "battery drains fast under heavy load",
  "top_praise": "stunning 4K display with excellent colour accuracy"
}
"""
```

---

## 10. End-to-End Product Lifecycle

### 10.1 Customer Journey

```mermaid
sequenceDiagram
    participant C as Customer
    participant FE as React
    participant NGINX
    participant APP as ShopSense App
    participant ROUTER as Query Router
    participant QDRANT
    participant PG as PostgreSQL
    participant REDIS
    participant KAFKA
    participant GROQ

    Note over C,GROQ: Phase 1 — Browse
    C->>FE: Opens storefront
    FE->>NGINX: GET /api/products
    NGINX->>APP: products module
    APP->>REDIS: Check current_price cache
    APP->>PG: SELECT products
    APP-->>FE: Product grid

    Note over C,GROQ: Phase 2 — Semantic Search
    C->>FE: "laptop for video editing under 80K"
    FE->>APP: POST /api/search
    APP->>GROQ: Extract filters (8B, 300ms)
    APP->>APP: Generate embedding (local, 50ms)
    APP->>QDRANT: Vector search + price filter
    QDRANT-->>APP: Top 20 candidates
    APP->>APP: flashrank rerank
    APP-->>FE: Top 10 ranked results

    Note over C,GROQ: Phase 3 — AI Chat (Semantic path)
    C->>FE: "I travel a lot, do video editing, budget 80K"
    FE->>APP: POST /api/chat
    APP->>REDIS: Load history (empty)
    APP->>GROQ: Classify intent → PRODUCT_SEARCH (8B)
    APP->>GROQ: Route query → SEMANTIC (8B)
    APP->>QDRANT: Semantic search with preferences injected
    APP->>GROQ: Synthesise response (70B, stream)
    APP-->>FE: Streaming tokens
    APP->>REDIS: Save turn to history

    Note over C,GROQ: Phase 4 — Admin Analytics (NL-to-SQL path)
    C->>FE: Admin: "which brand has highest avg rating?"
    FE->>APP: POST /api/analytics/query
    APP->>GROQ: Route query → ANALYTICAL (8B)
    APP->>GROQ: Generate SQL (8B, 300ms)
    APP->>APP: Validate SQL (sqlparse, 5ms)
    APP->>PG: Execute SELECT query (10ms)
    APP->>GROQ: Synthesise insight (70B)
    APP-->>FE: "Dell leads with 4.6 avg rating..."

    Note over C,GROQ: Phase 5 — Demand signal + price update
    C->>FE: Clicks Dell XPS 15
    FE->>APP: GET /products/prod_xps15
    APP->>KAFKA: Publish product.viewed
    KAFKA->>APP: Consume product.viewed
    APP->>REDIS: INCR views:prod_xps15 (now 51)
    Note over APP: Pricing engine wakes (every 2 min)
    APP->>REDIS: GET views:prod_xps15 = 51 > 50
    APP->>PG: UPDATE current_price = 75000 * 1.05
    APP->>REDIS: SET current_price:prod_xps15 78750
    APP->>KAFKA: Publish price.updated
    KAFKA->>APP: orders module consumes price.updated
    APP->>REDIS: Recalculate active cart totals

    Note over C,GROQ: Phase 6 — Cart + Order
    C->>FE: Add to Cart → Place Order
    FE->>APP: POST /orders
    APP->>PG: INSERT order (price snapshot)
    APP->>REDIS: DEL cart:usr_456
    APP->>KAFKA: Publish order.created
```

---

## 11. AI Layers — Implementation Details

### 11.1 Semantic vs Keyword vs NL-to-SQL

```mermaid
graph TD
    subgraph A["Keyword Search"]
        KQ["laptop for video editing"] --> KM["Exact string match"]
        KM --> KR["0 results"]
    end

    subgraph B["Semantic Search"]
        SQ["laptop for video editing"] --> SE["384-dim vector\nCaptures meaning"]
        SE --> SR["Dell XPS 15, MacBook Pro M3\nSemantically close to\nvideo editing workstation"]
    end

    subgraph C["NL-to-SQL"]
        NQ["which brand has highest avg rating?"] --> NS["Generate SQL\nSELECT brand, AVG(avg_rating)\nGROUP BY brand ORDER BY 2 DESC"]
        NS --> NR["Dell: 4.6, Apple: 4.5, Sony: 4.3"]
    end
```

### 11.2 Dynamic Pricing Rules

```python
PRICING_RULES = {
    "high_demand": {
        "condition": "views_24h > 50 AND stock_count > 5",
        "multiplier": 1.05,  # 5% increase
        "reason": "high_demand"
    },
    "low_stock_high_demand": {
        "condition": "views_24h > 30 AND stock_count <= 5",
        "multiplier": 1.10,  # 10% increase
        "reason": "low_stock_high_demand"
    },
    "high_abandonment": {
        "condition": "cart_adds_24h > 20 AND orders_24h < 3",
        "multiplier": 0.95,  # 5% decrease
        "reason": "high_abandonment"
    },
    "stale_inventory": {
        "condition": "views_24h < 5 AND stock_count > 50",
        "multiplier": 0.93,  # 7% decrease
        "reason": "low_demand_high_stock"
    }
}

MIN_MULTIPLIER = 0.80  # Never below 80% of base_price
MAX_MULTIPLIER = 1.30  # Never above 130% of base_price
```

---

## 12. Data Strategy

### 12.1 Phase 1 — Synthetic (Day 1, $0)

Generate 200 laptop products using Python + Faker. Each product has realistic CPU/RAM/storage/display/battery/GPU/weight specs and 5 reviews with varied ratings. Purpose: validate the full pipeline before spending time on real data ingestion.

### 12.2 Phase 2 — Real Products (Day 3, $0)

**Best Buy Developer API** — register at `developer.bestbuy.com` (free, no credit card). Rate limit: 5 req/s. Pull 1,500–2,000 laptops with real specs, images, and pricing. Run once, store in PostgreSQL.

### 12.3 Phase 3 — Real Reviews (Day 3–4, $0)

**Kaggle Amazon Electronics Reviews** — freely available for research. Filter to electronics, match to Best Buy products by brand and approximate name. Run aspect sentiment batch job via Bedrock Claude Sonnet (~30 min for 2,000 products).

### 12.4 Phase 4 — Embeddings (Day 4, $0)

Run `generate_embeddings.py` locally. Embedding generation runs via API (Jina or NVIDIA). 2,000 products at ~50 req/s takes approximately 5 minutes. Upsert to Qdrant. Semantic search is now live.

### 12.5 Data Pipeline

```mermaid
flowchart LR
    A[Best Buy API] --> C[clean_and_normalise.py]
    B[Kaggle Reviews] --> C
    C --> D[seed_postgres.py\nInsert to Supabase]
    D --> E[run_sentiment.py\nBedrock Claude Sonnet batch job]
    E --> F[generate_embeddings.py\nJina or NVIDIA API\n1024-dim vectors]
    F --> G[verify_ingestion.py\n10 test queries\nQuality check]
```

---

## 13. Repository Structure

```
shopsense/
│
├── docker-compose.yml              # Full local stack: postgres, redis, qdrant, kafka, kafka-ui
├── .env.example
├── Makefile                        # make dev, make test, make deploy
│
├── app/                            # Modular monolith — single FastAPI app
│   ├── main.py                     # App factory, include all routers
│   ├── config.py                   # Settings from environment
│   ├── database.py                 # SQLAlchemy engine + session
│   ├── redis_client.py             # Redis connection
│   │
│   ├── products/
│   │   ├── router.py               # FastAPI routes
│   │   ├── models.py               # SQLAlchemy models
│   │   ├── schemas.py              # Pydantic schemas
│   │   ├── service.py              # Business logic
│   │   └── kafka.py                # Event producer
│   │
│   ├── orders/
│   │   ├── router.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── service.py
│   │   ├── kafka_producer.py
│   │   └── kafka_consumer.py       # Consumes price.updated
│   │
│   ├── users/
│   │   ├── router.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   └── service.py
│   │
│   ├── search/
│   │   ├── router.py
│   │   ├── embedder.py             # Embedding provider wrapper (Jina or NVIDIA, set by env)
│   │   ├── qdrant_ops.py           # Qdrant upsert and search
│   │   ├── query_router.py         # SEMANTIC / ANALYTICAL / HYBRID classifier
│   │   ├── nl_to_sql.py            # SQL generation + validation + execution
│   │   ├── hybrid_search.py        # Combines SQL filter + vector search
│   │   ├── reranker.py             # flashrank cross-encoder
│   │   ├── kafka_consumer.py       # Consumes product.viewed → Redis INCR
│   │   └── pricing_engine.py       # Background task every 120s
│   │
│   ├── agent/
│   │   ├── router.py               # POST /chat streaming endpoint
│   │   ├── graph.py                # LangGraph graph definition
│   │   ├── state.py                # ShopSenseState TypedDict
│   │   ├── prompts.py              # All LLM prompts
│   │   └── nodes/
│   │       ├── classify_intent.py
│   │       ├── route_query.py      # NEW: SEMANTIC/ANALYTICAL/HYBRID router
│   │       ├── semantic_search.py
│   │       ├── nl_to_sql_search.py # NEW: NL-to-SQL retrieval node
│   │       ├── hybrid_search.py    # NEW: Hybrid retrieval node
│   │       ├── compare_products.py
│   │       ├── personalise.py
│   │       ├── synthesise.py
│   │       └── refuse.py
│   │
│   └── analytics/
│       ├── router.py               # Admin-only endpoints
│       └── nl_to_sql_admin.py      # NL-to-SQL for admin dashboard
│
├── workers/
│   ├── personalisation_worker.py   # Kafka consumer → user preference profiles
│   └── run_workers.py              # Entry point: starts all background workers
│
├── data/
│   ├── ingestion/
│   │   ├── fetch_bestbuy.py
│   │   ├── process_kaggle.py
│   │   ├── seed_postgres.py
│   │   ├── run_sentiment.py
│   │   ├── generate_embeddings.py
│   │   └── verify_ingestion.py
│   └── sample/
│       └── synthetic_products.json
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ProductGrid.tsx
│   │   │   ├── ProductDetail.tsx
│   │   │   ├── SearchBar.tsx
│   │   │   ├── ShopSenseChat.tsx
│   │   │   ├── AdminDashboard.tsx  # NEW: NL-to-SQL admin panel
│   │   │   ├── Cart.tsx
│   │   │   └── PriceDisplay.tsx
│   │   ├── App.tsx
│   │   └── main.tsx
│   └── package.json
│
├── infra/
│   ├── terraform/
│   │   ├── main.tf                 # Core infrastructure
│   │   ├── variables.tf            # Input variables
│   │   ├── outputs.tf              # EC2 public IP, etc.
│   │   ├── security_groups.tf      # Firewall rules
│   │   └── backend.tf              # Remote state in S3
│   └── nginx/
│       └── nginx.conf
│
└── tests/
    ├── test_products.py
    ├── test_search_semantic.py
    ├── test_nl_to_sql.py           # NEW: NL-to-SQL validation tests
    ├── test_query_router.py        # NEW: Router accuracy tests
    └── test_kafka_events.py
```

---

## 14. Terraform Deployment Guide

### 14.1 Why Learn Terraform Here

Terraform is Infrastructure as Code — you describe the AWS resources you want in `.tf` files and `terraform apply` creates them. The key benefit for your portfolio: your entire AWS setup is reproducible, version-controlled, and destroyable in one command. This is what every production AI system uses, and it appears in almost every AI Engineer job description.

ShopSense uses Terraform to deploy a single EC2 instance with the correct security groups, an Elastic IP, and S3 remote state. This is the simplest useful Terraform configuration — perfect for learning the concepts without drowning in complexity.

### 14.2 What You Will Learn

- **Providers:** How Terraform talks to AWS using your credentials
- **Resources:** Declaring EC2 instances, security groups, Elastic IPs in HCL syntax
- **Variables:** Making configurations reusable across environments (dev vs prod)
- **Outputs:** Extracting useful values after deployment (EC2 public IP)
- **State:** How Terraform tracks what it has created (stored in S3 for teams)
- **Lifecycle:** `terraform init` → `terraform plan` → `terraform apply` → `terraform destroy`

### 14.3 The Terraform Files

**`infra/terraform/backend.tf`** — Remote state in S3 so the state file is not lost if your laptop dies:

```hcl
terraform {
  backend "s3" {
    bucket = "shopsense-terraform-state"
    key    = "shopsense/terraform.tfstate"
    region = "us-east-1"
  }
}
```

**`infra/terraform/variables.tf`** — All configurable values in one place:

```hcl
variable "aws_region" {
  description = "AWS region to deploy to"
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t2.micro"  # Free tier
}

variable "your_ip" {
  description = "Your IP address for SSH access — get from whatismyip.com"
  type        = string
  # No default — you must supply this. Prevents SSH being open to the world.
}
```

**`infra/terraform/security_groups.tf`** — The firewall rules:

```hcl
resource "aws_security_group" "shopsense_sg" {
  name        = "shopsense-sg"
  description = "ShopSense application security group"

  # HTTP — open to anyone (your API)
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTPS — open to anyone
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # SSH — only your IP. Replace with your actual IP.
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["${var.your_ip}/32"]
  }

  # All outbound traffic allowed
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "shopsense-sg"
    Project = "ShopSense"
  }
}
```

**`infra/terraform/main.tf`** — The EC2 instance:

```hcl
provider "aws" {
  region = var.aws_region
}

# EC2 instance running the ShopSense monolith
resource "aws_instance" "shopsense" {
  ami                    = "ami-0c7217cdde317cfec"  # Ubuntu 22.04 us-east-1
  instance_type          = var.instance_type
  key_name               = "shopsense-key"          # Create this in AWS Console first
  vpc_security_group_ids = [aws_security_group.shopsense_sg.id]

  # Startup script — runs once when instance first boots
  user_data = <<-EOF
    #!/bin/bash
    apt-get update -y
    apt-get install -y docker.io docker-compose-plugin git

    # Clone your repo and start the stack
    git clone https://github.com/yourusername/shopsense.git /home/ubuntu/shopsense
    cd /home/ubuntu/shopsense
    docker compose up -d
  EOF

  root_block_device {
    volume_size = 20  # 20 GB — enough for Docker images + data
    volume_type = "gp3"
  }

  tags = {
    Name    = "shopsense-server"
    Project = "ShopSense"
  }
}

# Elastic IP — static address that survives instance reboots
resource "aws_eip" "shopsense_ip" {
  instance = aws_instance.shopsense.id
  domain   = "vpc"

  tags = {
    Name = "shopsense-eip"
  }
}
```

**`infra/terraform/outputs.tf`** — Values printed after deployment:

```hcl
output "public_ip" {
  description = "Public IP of the ShopSense server"
  value       = aws_eip.shopsense_ip.public_ip
}

output "ssh_command" {
  description = "SSH command to connect to the server"
  value       = "ssh -i shopsense-key.pem ubuntu@${aws_eip.shopsense_ip.public_ip}"
}

output "app_url" {
  description = "ShopSense application URL"
  value       = "http://${aws_eip.shopsense_ip.public_ip}"
}
```

### 14.4 Deployment Commands

```bash
# One-time setup
cd infra/terraform
terraform init          # Downloads AWS provider, connects to S3 backend

# Before deploying — see exactly what Terraform will create
terraform plan -var="your_ip=YOUR.IP.HERE"

# Deploy
terraform apply -var="your_ip=YOUR.IP.HERE"
# Type 'yes' when prompted
# After ~2 minutes: outputs public IP and SSH command

# To destroy everything (stops AWS charges)
terraform destroy -var="your_ip=YOUR.IP.HERE"
```

### 14.5 What Terraform Teaches You About AWS

By writing these files and running them, you learn:

- **Security groups** — AWS firewall. You will understand inbound/outbound rules, why SSH should never be open to 0.0.0.0/0, and how to restrict access properly
- **EC2 instances** — AMI IDs, instance types, user_data startup scripts, key pairs for SSH
- **Elastic IPs** — why you need a static IP (EC2 public IPs change on restart)
- **IAM** — you will need to configure AWS credentials. Understanding access keys, profiles, and the principle of least privilege comes naturally
- **S3 for state** — why Terraform state matters and why it should be stored remotely
- **HCL syntax** — Terraform's language. Enough to read any Terraform configuration you encounter in a job

---

## 15. Cost Analysis

### 15.1 Development (Weeks 1–3, Local Docker Compose)

| Component                           | How Hosted         | Cost                                      |
| ----------------------------------- | ------------------ | ----------------------------------------- |
| PostgreSQL + Redis + Qdrant + Kafka | Docker containers  | **$0**                              |
| LLM inference                       | Amazon Bedrock     | Pay per token (~$1–5/month at dev usage) |
| Embeddings                          | Jina or NVIDIA API | Free tier available, ~$0 at dev usage     |
| **Total**                     |                    | **$0/month**                        |

### 15.2 Portfolio Deployment (Free Tiers)

| Component       | Provider                      | Cost                         |
| --------------- | ----------------------------- | ---------------------------- |
| React frontend  | Vercel free tier              | $0                           |
| PostgreSQL      | Supabase free (500 MB)        | $0                           |
| Vector DB       | Qdrant Cloud free (1 GB)      | $0                           |
| Redis           | Upstash free (10k req/day)    | $0                           |
| LLM inference   | Amazon Bedrock                | ~$1/month at portfolio usage |
| Backend + Kafka | EC2 t2.micro (free 12 months) | $0                           |
| Terraform state | S3 (< 1 MB, negligible)       | ~$0.01                       |
| **Total** |                               | **~$0/month**          |

> After 12-month free tier: **$8.50/month** (EC2 t2.micro on-demand)

### 15.3 Production (Paying Client)

| Component               | Cost                          |
| ----------------------- | ----------------------------- |
| EC2 t3.medium ×2 + ALB | $78/month                     |
| Supabase Pro (8 GB)     | $25/month                     |
| Qdrant Cloud (5 GB)     | $25/month                     |
| Upstash Redis           | $10/month                     |
| Amazon Bedrock          | ~$20/month at production load |
| Domain + SSL            | $1/month                      |
| **Total**         | **~$149/month**         |

---

## 16. Build Roadmap

```mermaid
gantt
    title ShopSense Build Timeline — 3 Weeks
    dateFormat  YYYY-MM-DD

    section Week 1 — Monolith + Base
    Docker Compose + project scaffold  :w1a, 2026-05-12, 1d
    products module + seed data        :w1b, after w1a, 2d
    orders module + Kafka events       :w1c, after w1b, 2d
    users module                       :w1d, after w1c, 1d

    section Week 2 — AI Search + NL-to-SQL
    Real data ingestion                :w2a, 2026-05-19, 1d
    Semantic search + Qdrant           :w2b, after w2a, 1d
    Query router implementation        :w2c, after w2b, 1d
    NL-to-SQL engine + validation      :w2d, after w2c, 1d
    Hybrid search + aspect sentiment   :w2e, after w2d, 1d

    section Week 3 — Agent + Deploy
    LangGraph agent + all nodes        :w3a, 2026-05-26, 2d
    Pricing engine + personalisation   :w3b, after w3a, 1d
    React frontend + admin dashboard   :w3c, after w3b, 2d
    Terraform + EC2 deploy             :w3d, after w3c, 1d
```

### Day-by-Day Milestones

| Day    | What you build                                                                       | Demo at end of day                                                                |
| ------ | ------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| 1      | Docker Compose: postgres + redis + qdrant + kafka + kafka-ui all running             | `docker-compose up` starts full stack. Kafka UI shows 4 topics                  |
| 2–3   | products module: CRUD endpoints, SQLAlchemy models, Kafka producer                   | Browse products via API.`product.viewed` events appear in Kafka UI              |
| 4–5   | orders module: cart in Redis, orders in PostgreSQL, Kafka consumer for price.updated | Add to cart, place order, see events flow                                         |
| 6      | users module: profiles and preference table structure                                | User profile endpoints working                                                    |
| 7      | Real data: Best Buy API + Kaggle reviews ingested, sentiment scores populated        | 2000 real products in database                                                    |
| 8      | Semantic search: embeddings in Qdrant, search endpoint working                       | "laptop for video editing" returns relevant results                               |
| 9      | Query router: SEMANTIC / ANALYTICAL / HYBRID classification working                  | Router correctly classifies 10 test queries                                       |
| 10     | NL-to-SQL: schema-aware SQL generation, validation loop, execution                   | "which brand has highest rating?" returns correct answer from DB                  |
| 11     | Hybrid search: SQL constrains candidates, vector search ranks within them            | Complex query uses both retrieval paths                                           |
| 12–13 | LangGraph agent: all nodes including new NL-to-SQL node, streaming working           | Full conversation with streaming response, LangSmith traces visible               |
| 14     | Pricing engine + personalisation worker                                              | Demand signal flows: view product → Redis counter → price update → Kafka event |
| 15–16 | React frontend + ShopSense chat widget + admin analytics dashboard                   | Live UI with search, chat, and admin NL-to-SQL panel                              |
| 17     | Terraform: write files,`terraform plan`, `terraform apply`                       | ShopSense live on AWS EC2 at a public IP                                          |
| 18     | Final testing + demo recording                                                       | 3-minute demo video ready for portfolio                                           |

---

## 17. GenAI Learning Outcomes

This section maps every component of ShopSense to what it teaches you about GenAI engineering. This is the learning agenda, not just a feature list.

### 17.1 RAG and Retrieval

**What you build:** Semantic search over product embeddings with metadata filtering, aspect-based sentiment as retrieval signals, flashrank cross-encoder reranking.

**What you learn:**

- The difference between embedding quality and retrieval quality — a great embedding model with poor chunking gives bad results
- Why reranking matters: the top-20 from vector similarity is not the same as the top-10 a human would choose
- Metadata filtering in Qdrant: how to combine semantic similarity with structured constraints
- The real meaning of recall vs precision in retrieval systems

**Why it matters for interviews:** Most candidates say "I used RAG." You can say "I built a two-stage retrieval system: first-stage vector search for recall, second-stage cross-encoder reranking for precision, with structured metadata filters applied before the vector search to reduce the candidate space."

---

### 17.2 LangGraph and Agentic Orchestration

**What you build:** A multi-node LangGraph graph with conditional edges, multiple retrieval paths, streaming output, conversation memory in Redis, and full LangSmith observability.

**What you learn:**

- How LangGraph state flows between nodes and why `TypedDict` matters for type safety
- Conditional edges: how the graph makes routing decisions without hardcoded if/else
- Streaming with FastAPI SSE: why token-by-token streaming requires async generators and how to wire them correctly
- The difference between LangChain chains (linear) and LangGraph graphs (conditional, cyclical) — and when each is appropriate
- Human-in-the-loop patterns: where to add confirmation steps before executing consequential actions

**Why it matters for interviews:** Interviewers at companies building serious AI products want engineers who understand agent orchestration, not just prompt engineering. Explaining your LangGraph state machine with conditional edges signals exactly this.

---

### 17.3 NL-to-SQL and Structured Retrieval

**What you build:** Schema-aware SQL generation with `sqlparse` validation, retry loops, audit logging, and hybrid combination with vector search.

**What you learn:**

- Why schema injection is essential and how to format it for reliable SQL generation
- JSONB query patterns in PostgreSQL — a common failure point for generic models
- The validation-retry loop pattern: never trust LLM-generated code without checking it
- When to use SQL vs vector search vs both — the fundamental retrieval routing decision
- How to build a training data pipeline: the `nl_sql_audit` table collects real query-to-SQL pairs for future fine-tuning

**Why it matters for interviews:** NL-to-SQL is appearing in every enterprise AI product. Being able to explain the safety constraints (SELECT only, validation before execution) and the hybrid architecture (SQL constrains, vectors rank) immediately distinguishes you from someone who just calls an API.

---

### 17.4 LLM Prompt Engineering and Structured Outputs

**What you build:** Six different prompts for different tasks, each returning structured JSON, plus a synthesis prompt that adapts its tone based on which retrieval path was used.

**What you learn:**

- Structured output prompting: how to reliably get JSON back from an LLM and what happens when you do not
- Model selection by task: why you use the fast 8B model for classification and routing, and the 70B model only for final synthesis
- Prompt versioning: every prompt in `prompts.py` should be versioned and tracked alongside model versions in MLflow
- The temperature/top-p settings for different tasks: classification needs low temperature (deterministic), creative synthesis needs slightly higher
- Few-shot examples vs zero-shot: when to add examples and when the schema injection is enough

---

### 17.5 Evaluation and Observability

**What you build:** LangSmith traces on every agent interaction, Prometheus metrics on every endpoint, the `nl_sql_audit` table for SQL accuracy tracking.

**What you learn:**

- How to interpret a LangSmith trace: what each node received as input, what it returned, and how long it took
- The difference between system-level metrics (Prometheus: request count, latency P95) and AI-specific metrics (LangSmith: faithfulness, hallucination rate)
- Building a golden test set for NL-to-SQL: 30 natural language queries with expected SQL and expected results, run on every deployment
- Why evaluation-gated CI/CD matters: a deployment that regresses NL-to-SQL accuracy by 10% should not go to production

---

### 17.6 Event-Driven AI Systems

**What you build:** Kafka event bus connecting user behaviour (product views) to AI decisions (price updates) with a complete audit trail.

**What you learn:**

- Event-driven architecture in the context of AI: how to feed real-time signals (user behaviour) into ML models (pricing) without tight coupling
- The consumer group pattern: multiple consumers reading from the same topic for different purposes (demand counters, personalisation profiles)
- At-least-once vs exactly-once delivery: why the Redis `INCR` for demand counters needs idempotency protection
- How Kafka enables time-travel debugging: replay events to understand why a price changed on a specific day

---

### 17.7 Terraform and AWS Infrastructure for AI Systems

**What you build:** EC2 instance, security groups, Elastic IP, and S3 state backend — all declared in Terraform HCL.

**What you learn:**

- The mental model of Infrastructure as Code: your infrastructure has the same properties as your application code — version control, code review, reproducibility
- AWS security fundamentals: security groups, least-privilege SSH access, why port 22 should never be open to 0.0.0.0/0
- EC2 user_data scripts: how to bootstrap an application on first boot
- State management: why Terraform state matters, what happens if it gets corrupted, and why S3 is the right backend
- The plan → apply workflow: always review the diff before changing infrastructure, exactly like reviewing a PR before merging

---

## 18. Success Criteria & Evaluation

### 18.1 Functional Checklist

| Feature                    | Test                              | Pass                                          |
| -------------------------- | --------------------------------- | --------------------------------------------- |
| Semantic search            | "laptop for video editing"        | Returns 5+ relevant results                   |
| Filter extraction          | "under ₹80K Dell laptop"         | `max_price=80000`, `brand=Dell` extracted |
| Query router — SEMANTIC   | "something portable for travel"   | Routes to vector search                       |
| Query router — ANALYTICAL | "which brand has highest rating?" | Routes to NL-to-SQL                           |
| Query router — HYBRID     | "best rated laptop under 80K"     | Uses both paths                               |
| NL-to-SQL safety           | Inject "DROP TABLE products"      | Blocked by validation                         |
| NL-to-SQL accuracy         | 20 golden test queries            | >= 85% generate correct SQL                   |
| AI agent streaming         | Ask any question                  | Response streams token by token               |
| Kafka demand signal        | Browse product 55 times           | Price updates,`price.updated` published     |
| Cart sync                  | Price updates while in cart       | Cart total recalculated automatically         |
| LangSmith traces           | Any agent interaction             | Full trace visible                            |
| Terraform deploy           | `terraform apply`               | ShopSense live at public IP                   |

### 18.2 Performance Targets

| Metric                           | Target      |
| -------------------------------- | ----------- |
| Semantic search P95 latency      | < 1 second  |
| NL-to-SQL generation + execution | < 800ms     |
| Query router classification      | < 200ms     |
| Agent first token                | < 2 seconds |
| Kafka event processing lag       | < 500ms     |

### 18.3 Demo Script — 4 Minutes

1. **0:00–0:30** — Keyword search fails: "laptop for video editing" → 0 results
2. **0:30–1:00** — Semantic search succeeds with same query → relevant ranked results
3. **1:00–1:30** — Admin panel: "which brand has the highest average rating?" → NL-to-SQL generates SQL, runs query, returns "Dell: 4.6 stars" — show the generated SQL in the audit log
4. **1:30–2:15** — ShopSense chat: "I travel a lot and do video editing, budget ₹80K" → streaming response with personalised recommendation
5. **2:15–2:45** — Hybrid query: "best reviewed Dell laptop under ₹80K" → show HYBRID path in LangSmith trace, SQL constrains to Dell + price, vector ranks by review quality
6. **2:45–3:15** — Demand signal: browse product 55 times → watch Redis counter in terminal, see price update in UI, see `price.updated` event in Kafka UI
7. **3:15–4:00** — Terraform: show the 4 `.tf` files, run `terraform plan`, show what it would create — "one command deploys the entire infrastructure"

---

*ShopSense v2.0 — Modular Monolith + NL-to-SQL Hybrid Retrieval + Terraform Deployment*
*Built with FastAPI, LangGraph, Kafka, Qdrant, PostgreSQL, Redis, Amazon Bedrock, and AWS*
*Zero cost during development. ~$0/month on AWS free tier.*

---

## 19. Agentic Tool Calling — ShopSense as an Action-Taking Agent

### 19.1 The Shift from Answering to Acting

Up to this point, ShopSense answers questions. This section describes the upgrade that turns it into an agent that takes real actions — adding products to carts, processing payments, sending emails, tracking orders, managing wishlists — all through natural conversation. This is the difference between a smart search engine and an autonomous shopping assistant.

The mental model to hold: every time the agent does something to the real world, that is a tool call. The agent proposes the action, shows the user exactly what will happen, waits for explicit confirmation, then executes. This human-in-the-loop confirmation gate before every consequential action is what makes the system trustworthy. An agent that autonomously charges your card without asking is terrifying. An agent that says "your total is ₹78,750 — shall I proceed with your Visa ending in 4242?" is genuinely useful.

---

### 19.2 MCP Servers — Standardising the Tool Layer

Rather than building ad-hoc tool functions scattered across the codebase, ShopSense uses the **Model Context Protocol (MCP)** to standardise how tools are defined, discovered, and called. MCP is an open standard from Anthropic that defines a clean interface between an AI agent and the external capabilities it can invoke. Every tool in ShopSense is exposed as an MCP server endpoint, which means the same tool definitions work whether the agent is running locally, on EC2, or connected to Claude Code for development.

The practical benefit is that the LangGraph agent discovers tools at runtime from the MCP server rather than having them hardcoded into the graph. Adding a new tool means adding it to the MCP server — the agent can use it immediately without touching the graph definition. This is the same pattern used by enterprise AI systems at scale.

The MCP server runs as a separate process inside the monolith's Docker Compose stack. It exposes all tools over a standardised JSON-RPC interface. The LangGraph agent is configured with the MCP server URL at startup and discovers the full tool list automatically.

---

### 19.3 The Shopping Checkout Flow — Phase 1 Implementation

This is the first tool-calling flow to build. It is the complete journey from product selection through payment and receipt — exactly the example described above. All other tool categories listed in Section 19.4 are planned for later phases.

The flow works as follows. A customer has been chatting with the ShopSense agent and has found a laptop they like. They say something like "okay I think I will go with the Dell XPS 15." The agent recognises this as purchase intent — not a search query, not a question, but a decision. The intent classifier routes to a new node in the LangGraph graph called `handle_purchase_intent`.

The `handle_purchase_intent` node calls the `check_stock_status` tool first. If the product is in stock, it calls `get_delivery_estimate` using the user's saved pincode and shows the customer: the product name, the current price, the estimated delivery date, and asks "Shall I add this to your cart?" The customer says yes. The agent calls `add_to_cart` and confirms it was added.

The agent then calls `get_frequently_bought_together` using the product ID, which queries the orders table to find products commonly purchased alongside this laptop — this is real purchase co-occurrence data, not a hardcoded list. The agent says something like "Customers who bought this laptop also picked up a USB-C hub and a laptop stand — want to see those options?" If the customer says yes, the agent fetches those products and the loop continues. If the customer says no or "I am ready to pay," the agent moves to checkout.

For checkout, the agent calls `get_saved_payment_methods` and tells the customer which cards or UPI IDs are on file with the last four digits shown. The customer picks one or says to use the saved card. The agent then calls `calculate_order_total` and presents the complete itemised bill: product name, price, any discounts applied, tax, delivery fee, and the final total. The customer sees exactly what they are about to pay before committing.

The final confirmation is a single question: "Shall I place this order?" The agent will not proceed on any ambiguous response. Only a clear affirmative — "yes", "confirm", "place it", "go ahead" — triggers `process_payment`. If the payment succeeds, the agent immediately calls `send_confirmation_email` which sends a receipt with the order ID, itemised list, total paid, and estimated delivery date via SendGrid. The agent then tells the customer their order number and delivery window in the chat.

This single flow demonstrates six tool calls, a human-in-the-loop gate before payment, a proactive cross-sell loop, and an automated post-purchase action — all in one conversation thread with no page reloads, no form fills, and no navigating between pages.

---

### 19.4 MCP Tool Registry — Full Catalogue

This section documents all planned tools across the complete ShopSense tool surface. Phase 1 implements the checkout flow tools. All remaining tools are planned for later phases and are included here so Claude Code has the full architectural picture from the start.

**Cart and Checkout Tools (Phase 1 — implement first)**

The `add_to_cart` tool takes a product ID and quantity, validates stock availability, reads the current live price from Redis, adds the item to the user's cart in Redis, and returns the updated cart total. The agent always shows this total before confirming the add. The `remove_from_cart` tool mirrors this in reverse — agent confirms what will be removed and shows the new total. The `apply_coupon` tool validates a discount code against the coupons table, shows the saving amount, and applies it only after the user confirms. The `get_saved_payment_methods` tool returns the user's stored payment methods with card numbers masked to last four digits — never exposes full card data. The `calculate_order_total` tool computes the complete bill including product prices, any applied discounts, GST, and delivery fee, returning a structured breakdown for the agent to present as a formatted summary. The `process_payment` tool is the most critical — it calls the payment gateway with the cart ID and payment method ID, records the transaction in the orders table, and returns the order ID. It has an absolute rule: it only executes after an unambiguous confirmation from the user in the immediately preceding message. The `send_confirmation_email` tool calls SendGrid with the order ID, constructs the receipt from the order record, includes the itemised list and delivery estimate, and sends it to the user's registered email. The `get_delivery_estimate` tool takes a product ID and pincode, queries the warehouse location and courier SLA data, and returns a realistic delivery window.

**Product Intelligence Tools (Phase 2)**

The `get_frequently_bought_together` tool queries the orders table to find products that appear in the same orders as the given product ID, ranked by co-occurrence frequency. This is real purchase data — not a hardcoded list, not a recommendation model trained offline, but live query results from actual customer behaviour. The `get_compatible_accessories` tool uses the product knowledge graph to return accessories with a known compatibility relationship to the given product — chargers, cases, docking stations, and peripheral devices that are verified to work. The `compare_products` tool takes two or three product IDs, fetches their full specs and sentiment scores, and returns a structured comparison that the agent formats as a side-by-side narrative with clear trade-off language. The `check_stock_status` tool returns the current stock count and whether the product is available for immediate dispatch. When stock is low, the agent uses this to create honest urgency. The `get_price_history` tool returns the price trend for a product from the price_history table — the agent uses this to tell customers whether the current price is a good deal relative to recent history. The `set_price_alert` tool creates a record in a price_alerts table so the user is emailed when a product hits their target price — the agent proactively offers this when a product is above the user's budget.

**Wishlist and Saved Items Tools (Phase 2)**

The `add_to_wishlist` tool saves a product to the user's wishlist table when they are interested but not ready to buy. The agent proactively offers this when a customer says something like "maybe later" or "let me think about it." The `get_wishlist` tool reads the user's wishlist and is used to answer questions like "what did I save last time?" The `move_wishlist_to_cart` tool transfers a saved item directly to the cart — the agent uses this proactively when a wishlist item comes back into stock or drops in price. The `notify_when_in_stock` tool creates a stock notification record so the user is emailed when an out-of-stock product becomes available.

**Order Tracking and Post-Purchase Tools (Phase 3)**

The `get_order_status` tool queries the orders table and any integrated courier tracking API to return the current status of an order — the most common post-purchase question. The `get_tracking_info` tool returns the courier name, tracking number, and last scanned location for a shipped order. The `cancel_order` tool first checks whether the cancellation window is still open (before dispatch), shows the refund timeline to the user, and only calls the actual cancellation after two explicit confirmations — the consequences of cancellation are irreversible. The `initiate_return` tool starts the return process by creating a return request record, asks the user for a return reason which feeds into the product analytics, generates a return shipping label, and schedules a courier pickup. The `get_refund_status` tool returns the current state of a pending refund and a concrete date estimate based on the payment method used. The `submit_review` tool creates a product review record after delivery — the agent proactively opens a follow-up conversation a few days after the delivery confirmation event, making review collection conversational rather than a separate email campaign.

**Admin and Analytics Tools (Phase 3)**

The `update_stock_count` tool allows the store admin to update inventory by telling the agent in plain English — "mark the Dell XPS as 50 units in stock." The `create_discount` tool creates a time-limited promotion — admin says "put the Sony headphones on 15% sale until Sunday" and the agent creates the discount record and confirms. The `get_sales_analytics` tool calls the NL-to-SQL engine with an analytics-specific schema context and returns sales data that the agent narrates conversationally — "this week you sold 23 units, up 18% from last week, with the Dell XPS 15 driving 40% of revenue." The `send_bulk_notification` tool finds customers matching a given segment description, shows the count before sending, and only dispatches after admin confirmation — used for restock alerts, sale announcements, and re-engagement campaigns. The `flag_suspicious_order` tool is called automatically by the agent when order patterns deviate from normal — same product, multiple orders, different addresses within a short window — and creates a flag for human review rather than taking autonomous action.

---

### 19.5 The Human-in-the-Loop Architecture

Every tool in the registry is classified as either a read tool or a write tool. Read tools execute immediately — they return data, they do not change anything, and they add no friction. Write tools always require explicit confirmation before executing — they change state in the real world, and that change may be difficult or impossible to reverse.

The LangGraph graph implements this through a dedicated `await_confirmation` node that sits between the `propose_action` node and the `execute_tool` node for all write operations. When the agent proposes a write action, the graph pauses at this node. The next user message is classified by a simple intent router as CONFIRM, DECLINE, or AMBIGUOUS. A CONFIRM routes to tool execution. A DECLINE routes to a cancellation response. An AMBIGUOUS response routes back to the agent to ask for clarification — the system never interprets silence or vague responses as consent to a write operation.

The one exception to this rule is `send_confirmation_email`, which executes automatically after a successful `process_payment` — it is a direct consequence of the payment confirmation and does not require a separate gate. Every other write tool, without exception, requires its own explicit confirmation.

---

### 19.6 LangGraph State — Updated for Tool Calling

The ShopSenseState TypedDict gains new fields to support the tool-calling flow:

```python
class ShopSenseState(TypedDict):
    # Existing fields
    messages: List[BaseMessage]
    intent: str
    query_type: str
    search_results: List[Dict]
    sql_results: List[Dict]
    generated_sql: str
    user_preferences: Dict
    session_id: str
    user_id: str
    final_response: str
    sources: List[str]

    # New tool-calling fields
    pending_tool: str           # Name of the tool awaiting confirmation
    pending_tool_args: Dict     # Arguments for the pending tool
    pending_tool_description: str  # Human-readable description shown to user
    tool_result: Dict           # Result from the last executed tool
    awaiting_confirmation: bool # Whether the graph is paused for user input
    confirmation_context: str   # What the confirmation is for (shown to user)
    order_id: str               # Set after successful payment
    cart_summary: Dict          # Current cart state for context
```

---

### 19.7 Phase 1 Build Steps — Checkout Flow Only

The checkout flow is built in this exact order. Each step is testable before the next begins.

First, create the MCP server file at `app/mcp/server.py`. Define the tool schema for the eight checkout flow tools using the MCP protocol — each tool has a name, description, and input schema. Start the MCP server as a separate process in docker-compose.yml on port 8006. Verify the tool list is discoverable by calling the MCP server's `list_tools` endpoint.

Second, implement the eight tool functions in `app/mcp/tools/checkout.py`. Each function talks to the existing module service layers — `add_to_cart` calls the orders module service, `get_saved_payment_methods` queries the users table, `process_payment` calls a mock payment gateway (Stripe test mode for portfolio), `send_confirmation_email` calls SendGrid. Test each tool function in isolation before wiring to the agent.

Third, add three new nodes to the LangGraph graph in `app/agent/nodes/`: `handle_purchase_intent.py` (detects purchase signals and orchestrates the checkout flow), `propose_tool_action.py` (formats the tool description for the user), and `await_confirmation.py` (pauses the graph and classifies the next user message as CONFIRM, DECLINE, or AMBIGUOUS). Add conditional edges connecting these nodes.

Fourth, update the intent classifier prompt to include `PURCHASE_INTENT` as a new category alongside the existing ones. Add `CONFIRM` and `DECLINE` as intent categories for when the graph is in the awaiting_confirmation state.

Fifth, add the `get_frequently_bought_together` tool and wire the cross-sell loop — after `add_to_cart` succeeds, the graph automatically calls this tool and the agent presents the results before moving to checkout.

Sixth, add the Wishlist table migration to Supabase and implement `add_to_wishlist` — the agent offers this when a user expresses interest but not immediate purchase intent.

Seventh, test the complete flow end to end: search for a laptop, select it, confirm add to cart, see cross-sell suggestions, decline them, see the cart summary, confirm payment method, see the itemised bill, confirm payment, receive the email. Verify the full LangSmith trace shows all nodes and tool calls.

---

### 19.8 Tool Calling in the GenAI Learning Context

Building tool calling teaches four things that are genuinely difficult to learn from tutorials. The first is the difference between stateless and stateful agents — a stateless agent answers a question and forgets everything. A stateful agent maintains context across a multi-turn conversation, knows what it has proposed, knows what it is waiting for, and knows what it has already done. The ShopSenseState TypedDict is the statefulness implementation.

The second is human-in-the-loop design as an engineering discipline rather than a safety checkbox. The `await_confirmation` node is not a safety feature bolted on — it is a first-class architectural component that the entire checkout flow is built around. Understanding where to place confirmation gates, what counts as ambiguous, and how to handle declined confirmations gracefully is an engineering skill that most candidates who talk about "building agents" have never thought through.

The third is MCP as a tool standardisation layer. Most tutorials implement tools as hardcoded Python functions inside the agent. MCP makes tools discoverable, composable, and swappable. Adding a new tool to ShopSense means adding it to the MCP server — the agent discovers it without any code change. This is the architecture that scales to hundreds of tools in an enterprise system.

The fourth is the complete transaction lifecycle: proposing → confirming → executing → handling failure → recovering. The `process_payment` tool can fail — the card can be declined, the payment gateway can timeout, the network can fail between the payment and the database write. Building the retry logic, the idempotency keys that prevent double charges, and the user-facing error messages for each failure mode is the real engineering work that separates a production tool from a demo tool.

---

## 20. Scaffold Decisions, Environment Config & Auth Design

This section records all structural and configuration decisions made before scaffolding begins. It exists so Claude Code has every answer it needs without asking, and so the decisions are version-controlled alongside the code they affect.

---

### 20.1 Scaffold Decisions — Q1 through Q12

**Q1 — Where does the scaffold live?**
The entire project is created inside the existing `shopsense/` directory. The `ShopSense_Platform_Plan_v4.md` stays at `shopsense/` root as the reference document. All code goes directly inside `shopsense/` — so `shopsense/app/`, `shopsense/docker-compose.yml`, `shopsense/frontend/` and so on. No additional nesting layer.

**Q2 — Python package manager?**
`uv`. Root-level files are `pyproject.toml` and `uv.lock`. No `requirements.txt` — uv generates one via `uv export` when needed for Docker builds. This is consistent with VanaciRetain.

**Q3 — Python version?**
Python **3.11** specifically. Not 3.12. Reason: Intel Mac x86_64 compatibility constraints on torch, onnxruntime, and pyarrow that are known to break on 3.12. Consistent with VanaciRetain.

**Q4 — MCP server folder — include now or later?**
Include `app/mcp/` in the initial scaffold as a stub. Create the folder with an empty `__init__.py` and a `README.md` noting it is Phase 1 tool calling. Stub beats absent — the structure is correct from day one.

**Q5 — Frontend — monorepo or separate?**
Same repository. `frontend/` is a sibling to `app/` inside `shopsense/`. Single `git push` covers both. Vercel is configured to deploy from the `frontend/` subdirectory.

**Q6 — Docker Compose — one file or split?**
Split into two files. `docker-compose.yml` is the base — all infrastructure: postgres, redis, qdrant, kafka, zookeeper, kafka-ui. `docker-compose.override.yml` is for development extras: hot reload volume mounts, debug port exposure, test database. Docker Compose merges these automatically on `docker-compose up`. Production uses `docker-compose.yml` plus a `docker-compose.prod.yml` that overrides environment variables and removes dev mounts.

**Q7 — Tests folder — flat or mirrored?**
Mirrored structure. `tests/products/`, `tests/orders/`, `tests/users/`, `tests/search/`, `tests/agent/`, `tests/analytics/`, `tests/mcp/`. Pytest discovery runs cleanly with `pytest tests/search/` to scope to one module during development.

**Q8 — Makefile — include from day one.**
Root-level `Makefile` with targets: `make dev` (docker-compose up), `make test` (pytest), `make lint` (ruff + mypy), `make deploy` (terraform apply), `make down` (docker-compose down), `make logs` (docker-compose logs -f).

**Q9 — conftest.py placement?**
One root-level `conftest.py` only. Contains shared fixtures: app factory, async test database session, mock Bedrock client, mock Redis client, mock Kafka producer. Per-module conftest files are added only if a specific module needs fixtures that should not bleed into others.

**Q10 — Tool config — all in pyproject.toml.**
`[tool.ruff]`, `[tool.mypy]`, and `[tool.pytest.ini_options]` all inside `pyproject.toml`. One file to open, one file to commit. Separate config files are added only if a section grows too large.

**Q11 — AWS credentials — profile for local, explicit keys for production.**
`.env.example` references `AWS_PROFILE` for local development (reads from `~/.aws/credentials` named profile — no credentials ever in the `.env` file itself) and `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` as commented-out placeholders for production and CI. The `config.py` settings class reads `AWS_PROFILE` first and falls back to explicit keys.

**Q12 — app/agent/nodes/ — stub all node files from day one.**
Every node file listed in Section 13 and Section 19 is created as a stub containing the import block, the function signature with typed parameters, a docstring explaining what the node does and which edge connects to it, and a `raise NotImplementedError("implement in phase X")` body. Claude Code uses these stubs as a map of what exists and what is pending.

---

### 20.2 LLM Provider — Amazon Bedrock

Groq has been replaced with **Amazon Bedrock** throughout the platform. Bedrock requires no API key — it authenticates via the AWS profile or instance role that is already set up for the rest of the infrastructure. There is no separate credential to manage.

Two models are used, selected by task:

The **generation model** is `anthropic.claude-3-5-sonnet-20241022-v2:0`. This handles all response synthesis, aspect sentiment extraction during ingestion, product comparison generation, and any task where output quality matters. It is slower and costs more per token but produces the best results.

The **fast model** is `anthropic.claude-3-haiku-20240307-v1:0`. This handles all classification and routing tasks — intent classification, query type routing, NL-to-SQL generation, and filter extraction — where speed matters more than creative quality. It is significantly cheaper and faster than Sonnet.

The LangChain integration uses `langchain-aws` with the `ChatBedrock` class. The boto3 session is created from the `AWS_PROFILE` environment variable locally and from the EC2 instance role in production — no code change required between environments. Bedrock is available in `us-east-1` and several other regions; `AWS_REGION` in `.env` controls which region is used.

Approximate cost at portfolio usage (a few hundred requests per day): $1–5 per month. At production load for a paying client: $15–25 per month depending on query volume. This replaces the Groq free tier in the cost tables throughout the document.

---

### 20.3 Embedding Provider — Jina or NVIDIA

The embedding provider is runtime-configurable via the `EMBEDDING_PROVIDER` environment variable. The two supported providers are Jina (`jina-embeddings-v3`) and NVIDIA (`nvidia/nv-embedqa-e5-v5`). Both produce 1024-dimensional vectors which is why `EMBEDDING_DIMENSIONS=1024` is set in the environment config — this replaces the 384-dimensional vectors that all-MiniLM-L6-v2 produced.

The provider decision will be finalised when building the search module in Week 2. Until then the `EMBEDDING_PROVIDER` variable defaults to `JINA` in `.env.example` since Rohit already has experience with Jina embeddings from the personal chatbot project at `rohit-hebbar.com`. The embedder module (`app/search/embedder.py`) reads this variable at startup and instantiates the correct API client — no other code changes when switching providers.

The Qdrant collection is created with `dimensions=1024` at ingestion time. If the provider is changed after ingestion, the collection must be recreated and all products re-embedded. This is a one-time operation handled by the `generate_embeddings.py` ingestion script.

---

### 20.4 Complete `.env.example`

The following is the authoritative environment variable specification. Every variable in this file must be accounted for in `app/config.py`. Variables with empty values must be set before the corresponding feature works. Commented-out variables are alternatives or optional features.

```
# ── Application ────────────────────────────────────────────────────────
APP_ENV=development
APP_SECRET_KEY=                    # Min 32 chars. Generate: openssl rand -hex 32
JWT_ALGORITHM=HS256
JWT_EXPIRY_HOURS=24

# ── Database ───────────────────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://shopsense:shopsense@localhost:5432/shopsense
# Supabase production override:
# DATABASE_URL=postgresql+asyncpg://postgres:<password>@<host>:5432/postgres

# ── Redis ──────────────────────────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0
# Upstash production override:
# REDIS_URL=rediss://:<password>@<host>:6379

# ── Qdrant ─────────────────────────────────────────────────────────────
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=                    # Empty for local Docker. Set for Qdrant Cloud.
QDRANT_COLLECTION_NAME=products

# ── Kafka ──────────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_CONSUMER_GROUP_ID=shopsense-consumer-group
KAFKA_AUTO_OFFSET_RESET=earliest

KAFKA_TOPIC_PRODUCT_VIEWED=product.viewed
KAFKA_TOPIC_PRODUCT_CREATED=product.created
KAFKA_TOPIC_CART_UPDATED=cart.updated
KAFKA_TOPIC_ORDER_CREATED=order.created
KAFKA_TOPIC_PRICE_UPDATED=price.updated

# ── AWS / Bedrock ──────────────────────────────────────────────────────
AWS_REGION=us-east-1

# Local development — named profile from ~/.aws/credentials (recommended)
AWS_PROFILE=shopsense-dev

# Production / CI — explicit keys (never commit these, use secrets manager)
# AWS_ACCESS_KEY_ID=
# AWS_SECRET_ACCESS_KEY=

BEDROCK_GENERATION_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
BEDROCK_FAST_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0

# ── Embeddings ─────────────────────────────────────────────────────────
EMBEDDING_PROVIDER=JINA            # JINA | NVIDIA
EMBEDDING_DIMENSIONS=1024

JINA_API_KEY=
JINA_MODEL=jina-embeddings-v3

# NVIDIA_API_KEY=
# NVIDIA_MODEL=nvidia/nv-embedqa-e5-v5

# ── MCP Server ─────────────────────────────────────────────────────────
MCP_SERVER_PORT=8006
MCP_SERVER_URL=http://localhost:8006

# ── External Services ──────────────────────────────────────────────────
SENDGRID_API_KEY=
SENDGRID_FROM_EMAIL=noreply@shopsense.com

STRIPE_SECRET_KEY=                 # sk_test_... for development
STRIPE_WEBHOOK_SECRET=

# TAVILY_API_KEY=                  # Optional — web search enrichment

# ── Observability ──────────────────────────────────────────────────────
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=
LANGCHAIN_PROJECT=shopsense

# ── Pricing Engine ─────────────────────────────────────────────────────
PRICING_ENGINE_INTERVAL_SECONDS=120
PRICING_DEMAND_THRESHOLD=50
PRICING_MAX_MULTIPLIER=1.30
PRICING_MIN_MULTIPLIER=0.80

# ── Data Ingestion ─────────────────────────────────────────────────────
BESTBUY_API_KEY=                   # Register free at developer.bestbuy.com
```

---

### 20.5 Auth Module Design

Authentication in ShopSense is handled by the `app/auth/` module. Since this is a modular monolith, auth is a module rather than a separate service. Every other module imports the auth dependencies from this module to protect their routes.

**What the auth module contains:**

`router.py` exposes three public endpoints: `POST /auth/register` creates a new user account with a hashed password, `POST /auth/login` verifies credentials and returns a signed JWT, and `GET /auth/me` returns the current user's profile from the token. These three endpoints are the only ones that do not require authentication.

`models.py` defines the User SQLAlchemy model with columns: `id` (UUID primary key), `email` (unique, indexed), `hashed_password`, `role` (enum: customer or admin), `is_active` (boolean, default true), `created_at`.

`schemas.py` defines the Pydantic models: `UserCreate` (email + password), `UserLogin` (email + password), `UserResponse` (id + email + role, never exposes the hash), and `Token` (access_token + token_type).

`service.py` contains the business logic: `create_user` hashes the password with bcrypt and inserts the record, `authenticate_user` verifies credentials and raises a 401 if they do not match, `get_user_by_id` is used by the auth dependency on every protected request.

`dependencies.py` contains two FastAPI dependencies that every other module imports. `get_current_user` reads the `Authorization: Bearer <token>` header, verifies the JWT signature against `APP_SECRET_KEY`, checks expiry, fetches the user record, and returns the User object — it raises HTTP 401 if anything fails. `require_admin` wraps `get_current_user` and additionally checks that the role is admin, raising HTTP 403 if not.

`utils.py` contains four pure functions with no FastAPI dependencies: `hash_password` (bcrypt), `verify_password` (bcrypt verify), `create_access_token` (python-jose, signs with APP_SECRET_KEY and sets expiry from JWT_EXPIRY_HOURS), and `decode_access_token` (python-jose, raises 401 on invalid or expired token).

**How other modules use auth:**

Public endpoints such as product listing and search import neither dependency — they are open routes. Customer endpoints such as add to cart, place order, and get wishlist import `get_current_user` as a FastAPI dependency in their route signature. Admin endpoints such as analytics queries, stock updates, and bulk notifications import `require_admin` instead. The auth module itself never imports from any other module — it is a leaf in the dependency graph.

**Token design:**

The JWT payload contains only three fields: `user_id` (UUID string), `role` (customer or admin), and `exp` (Unix timestamp). No sensitive data, no unnecessary fields. The token is signed with HS256 using the `APP_SECRET_KEY`. Expiry is 24 hours for customers and 8 hours for admins — both read from `JWT_EXPIRY_HOURS` which can be overridden per environment.

---

### 20.6 Updated Technology Stack

The following table supersedes the technology stack table in Section 5, reflecting the Bedrock and embedding provider changes.

| Layer               | Technology                                         | Notes                                                           |
| ------------------- | -------------------------------------------------- | --------------------------------------------------------------- |
| LLM — generation   | Amazon Bedrock Claude 3.5 Sonnet                   | Response synthesis, sentiment extraction, comparison generation |
| LLM — fast tasks   | Amazon Bedrock Claude 3 Haiku                      | Intent classification, routing, NL-to-SQL, filter extraction    |
| Embeddings          | Jina jina-embeddings-v3 or NVIDIA nv-embedqa-e5-v5 | 1024 dimensions, provider set by EMBEDDING_PROVIDER env var     |
| Vector DB           | Qdrant (Docker local, Qdrant Cloud production)     | Collection dimension updated to 1024                            |
| Structured DB       | Supabase PostgreSQL                                | Unchanged                                                       |
| Agent orchestration | LangGraph + LangChain                              | Unchanged                                                       |
| LLM SDK             | langchain-aws (ChatBedrock)                        | Replaces langchain-groq                                         |
| Backend API         | FastAPI + uvicorn                                  | Unchanged                                                       |
| Auth                | python-jose (JWT) + bcrypt                         | New — see Section 20.5                                         |
| Event bus           | Apache Kafka + Zookeeper                           | Unchanged                                                       |
| Cache               | Redis                                              | Unchanged                                                       |
| MCP server          | FastAPI-based MCP server                           | Port 8006, stub in scaffold                                     |
| Package manager     | uv                                                 | Unchanged                                                       |
| Python version      | 3.11                                               | Unchanged                                                       |
| Frontend            | React + Vite + TypeScript                          | Unchanged                                                       |
| Deployment          | AWS EC2 + Terraform                                | Unchanged                                                       |
| Observability       | LangSmith + Prometheus + Grafana                   | Unchanged                                                       |
