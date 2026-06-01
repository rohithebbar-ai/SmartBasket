# SmartBasket — AI-Native Product Discovery Platform

### Complete Production Build Plan · Architecture · Agents · Deployment · Observability

**Version:** 2.0 | **Date:** May 2026 | **Author:** Rohit Hebbar | **Status:** Active Build — Days 1–17 Complete

---

## Table of Contents

1. [What SmartBasket Is](#1-what-smartbasket-is)
2. [Architecture Decision — Modular Monolith](#2-architecture-decision--modular-monolith)
3. [High-Level Architecture](#3-high-level-architecture)
4. [The Multi-Agent System](#4-the-multi-agent-system)
5. [RAG Strategy — What Goes Where](#5-rag-strategy--what-goes-where)
6. [Recommender System](#6-recommender-system)
7. [Module Specifications](#7-module-specifications)
8. [Kafka Event Architecture](#8-kafka-event-architecture)
9. [Database Schema](#9-database-schema)
10. [ETL Data Pipeline](#10-etl-data-pipeline)
11. [Frontend — Two Surfaces, One Codebase](#11-frontend--two-surfaces-one-codebase)
12. [Admin Dashboard — What It Contains](#12-admin-dashboard--what-it-contains)
13. [Observability Stack](#13-observability-stack)
14. [Deployment Architecture](#14-deployment-architecture)
15. [Cost Analysis](#15-cost-analysis)
16. [Environment Configuration](#16-environment-configuration)
17. [Repository Structure](#17-repository-structure)
18. [Day-by-Day Build Plan](#18-day-by-day-build-plan)
19. [Success Criteria](#19-success-criteria)

---

## 1. What SmartBasket Is

SmartBasket is a single-tenant AI-powered shopping assistant for a fashion e-commerce storefront. A customer types "show me something for a beach wedding that is not too formal, under ₹3000" and receives three specific products with a sentence explaining why each one was chosen — grounded entirely in the store's actual catalogue, never hallucinated. An admin types "which products had zero purchases but over 50 views this month?" and receives a precise answer from live database data. A returning customer opens the chat and receives recommendations that account for what they bought before, what they browsed today, and what customers with similar purchase patterns chose.

**The three things SmartBasket does that generic chatbots cannot:**

Semantic understanding of customer intent — not keyword matching, but genuine comprehension of what a person is shopping for. Structured intelligence — NL-to-SQL for questions that need exact database answers, not vector search. Conversational commerce — the complete checkout flow handled inside the chat, with human-in-the-loop confirmation before every write.

**Why it is not a document RAG system:**

Product specifications are structured data — name, price, colour, material, stock level. These belong in PostgreSQL and Qdrant, queried by SQL or vector similarity. Document RAG in SmartBasket is reserved for genuinely unstructured content: store return policies, sizing guides, brand storytelling. Putting product specs in PDFs and chunking them destroys structure that is useful for precise queries. The architecture reflects this distinction explicitly.

**Single-tenant first, multi-tenant later:**

SmartBasket is built for one store. The codebase is structured to make multi-tenancy straightforward to add later — clean module boundaries, no global state, service functions that accept explicit IDs. But `tenant_id` is not wired through everything from day one. That adds 3–4 weeks of infrastructure overhead (RLS policies, API key models, plan limits, Stripe webhooks) before a single feature is delivered. Build the product first. Add the B2B layer when the product is proven.

---

## 2. Architecture Decision — Modular Monolith

SmartBasket is built as a **modular monolith**, not microservices. This is a deliberate decision.

One person builds this. Microservices add two to three weeks of infrastructure overhead — service discovery, inter-service networking, distributed tracing across services, independent deployment pipelines — before a single feature is delivered. The coordination cost is all cost, no benefit at this stage.

The monolith has clean module boundaries. Each module has its own folder, router, models, schemas, and service layer. No module imports from another module's internals. They communicate through the service layer or Kafka events. This is the same structural discipline as microservices without the operational overhead.

**The two genuine exceptions — separate processes, not separate services:**

The embedding worker is CPU and I/O intensive during catalogue ingestion. It runs as a separate process consuming a Redis task queue. Same codebase, same repository, different entry point.

The ALS recommender training job is a batch process that runs weekly. It runs as a scheduled Python script, not inside the FastAPI app. Same codebase, separate execution.

**When to extract to microservices — specific triggers only:**

Extract the embedding worker to a separate EC2 spot instance when ingestion jobs are delaying API responses under real load. Extract the agent service when concurrent streaming SSE connections create memory pressure on the main API process. Extract nothing preemptively.

---

## 3. High-Level Architecture

```mermaid
graph TB
    subgraph Clients["Client Layer"]
        WIDGET[Embeddable JS Widget\nOne script tag\nAny webstore]
        ADMIN_UI[Admin Portal\nReact SPA\nStore management]
        STOREFRONT[Customer Storefront\nReact SPA\nProduct browsing]
    end

    subgraph Gateway["Gateway Layer"]
        NGINX[Nginx\nSSL termination\nRate limiting\nRoute /api/* to FastAPI\nServe widget.js statically]
    end

    subgraph App["Modular Monolith — FastAPI on EC2 t3.small"]
        direction TB
        AUTH[auth/ module\nJWT + bcrypt]
        PRODUCTS[products/ module\nCatalogue CRUD\nKafka producer]
        ORDERS[orders/ module\nCart Redis\nOrders PostgreSQL]
        USERS[users/ module\nProfiles\nPreferences]
        SEARCH[search/ module\nQuery router\nSemantic search\nNL-to-SQL\nHybrid path\nVisual search]
        AGENT[agent/ module\nSupervisor + 6 sub-agents\nLangGraph orchestration\nStreaming SSE]
        ANALYTICS[analytics/ module\nAdmin BI queries\nTrend reports]
        RECS[recommendations/ module\nALS serving\nContent-based\nHybrid blending]
        POLICIES[policies/ module\nDocument RAG\nStore policy Q&A]
        MCP[mcp/ module\nMCP server port 8006\nCheckout tools\nAdmin tools]
    end

    subgraph Workers["Background Workers — separate processes"]
        EMB_WORKER[Embedding Worker\nETL pipeline\nJina v3 API\nQdrant upsert]
        PERS_WORKER[Personalisation Worker\nKafka consumer\nPreference updates]
        PRICING_WORKER[Pricing Engine\nDemand signals\nPrice adjustments]
        REC_TRAINER[Recommender Trainer\nWeekly ALS retrain\nMLflow tracking]
        TREND_AGENT[Trend Intelligence Agent\nScheduled analysis\nAdmin notifications]
        RESTOCK_AGENT[Restock Prediction Agent\nTime-series forecast\nLow-stock alerts]
    end

    subgraph Storage["Storage Layer — managed free tiers"]
        PG[(Supabase PostgreSQL\nProducts, orders, users)]
        QDRANT_PROD[(Qdrant Cloud\nproducts\npolicies)]
        REDIS_UP[(Upstash Redis\nCart, sessions\nDemand counters\nRec cache)]
    end

    subgraph Events["Event Bus"]
        KAFKA[Apache Kafka\nDocker on EC2\n6 topics]
        KAFKAUI[Kafka UI\nport 8080]
    end

    subgraph AI["AI Layer"]
        BEDROCK[Amazon Bedrock\nClaude Sonnet 4.5 — generation\nClaude Haiku 4.5 — routing]
        JINA[Jina v3\n1024-dim embeddings\nretrieval.query / passage]
        ALS_MODEL[ALS Model\nMLflow registry\nWeekly retrain]
    end

    subgraph Observability["Observability"]
        LANGSMITH[LangSmith\nAgent traces]
        MLFLOW[MLflow\nModel registry\nExperiment tracking]
        PROMETHEUS[Prometheus\nSystem metrics]
        GRAFANA[Grafana\nDashboards]
    end

    Clients --> NGINX
    NGINX --> App
    App --> Storage
    App --> Events
    App --> AI
    Workers --> Storage
    Workers --> Events
    Workers --> AI
    App --> Observability
    Workers --> Observability
    KAFKA --> KAFKAUI
```

---

## 4. The Multi-Agent System

SmartBasket uses a supervisor-and-subagents architecture. Every user message goes to the Supervisor Agent first. The Supervisor classifies intent and routes to the appropriate specialist. Specialists never call each other — they communicate through shared LangGraph state.

```mermaid
flowchart TD
    MSG([User Message]) --> SUP[Supervisor Agent\nClassify intent\nRoute to specialist\nBedrock Haiku ~150ms]

    SUP -->|DISCOVERY| DISC[Product Discovery Agent\nSemantic search\nConstraint extraction\nPersonalised ranking]
    SUP -->|ANALYTICS| SQL[Text2SQL Agent\nNL-to-SQL\nSchema-aware\nAudit logged]
    SUP -->|VISUAL| VIS[Visual Search Agent\nVision LLM\nAttribute extraction\nImage-to-vector]
    SUP -->|COMPARE| COMP[Comparison Agent\nFetch 2-3 products\nTrade-off analysis\nRecommendation]
    SUP -->|POLICY| POL[Policy RAG Agent\nDocument retrieval\nReturn policy\nSizing guide]
    SUP -->|CHECKOUT| CHK[Purchase Agent\nMCP tool calling\nHuman-in-the-loop\nCheckout flow]
    SUP -->|OUT_OF_SCOPE| REF[Refusal Node\nPolite redirect\nNo LLM call]

    DISC --> SYNTH[Response Synthesis\nBedrock Sonnet\nPersonalised narrative\nStreaming SSE]
    SQL --> SYNTH
    VIS --> SYNTH
    COMP --> SYNTH
    POL --> SYNTH
    CHK --> SYNTH

    SYNTH --> SAVE[Save History\nRedis session\nLast 10 turns]
    SYNTH -.->|Full trace| LANGSMITH[LangSmith]
```

### 4.1 Supervisor Agent

The entry point for every message. Uses Bedrock Haiku for speed — classification should add under 200ms to the total latency. Reads conversation history from Redis before classifying so follow-up messages are understood in context.

Intent categories: `DISCOVERY` (find products), `ANALYTICS` (data questions), `VISUAL` (image upload), `COMPARE` (compare specific products), `POLICY` (store rules and guides), `CHECKOUT` (buy, cart, payment), `CLARIFY` (ambiguous — triggers clarifying question node), `OUT_OF_SCOPE` (non-shopping queries).

### 4.2 Product Discovery Agent

Handles all discovery and recommendation queries. Runs the constraint extractor to parse budget, colour, material, occasion from natural language. Routes to SEMANTIC, ANALYTICAL, or HYBRID retrieval path. Injects user preference profile from Redis cache before generating the final ranked list. Blends recommender system scores with semantic similarity scores for known users.

The constraint extractor reads the store's `available_attributes` metadata from Redis to know what filters exist in this specific catalogue. A clothing store extracts colour, size, material. The extractor does not hardcode these — it reads them from the indexed product attributes.

### 4.3 Text2SQL Agent

Handles all structured data questions from both customers and admins. Validates generated SQL with `sqlparse` before execution. Maximum 2 retries. Logs every query to `nl_sql_audit` table.

For customers: "do you have this in size XL?", "what colours does this come in?"
For admins: "which products have zero sales this month?", "what is the average order value?"

### 4.4 Visual Search Agent

New capability not in ShopSense. Accepts an image upload from the customer. Sends the image to Bedrock Claude Sonnet's vision capability and extracts: dominant colours, garment type, style keywords, occasion suitability, visible patterns. Generates a Jina v3 embedding from the extracted description. Searches Qdrant with that embedding plus any payload filters from the visual description. Returns visually similar products.

This is the multimodal RAG capability. The "document" being retrieved against is not a PDF — it is a structured description extracted from an image.

### 4.5 Comparison Agent

Handles direct product comparisons. Fetches full product details for 2-3 specific products. Builds a structured comparison using product attributes and sentiment scores. Generates a narrative trade-off analysis using Bedrock Sonnet tailored to the user's stated use case.

### 4.6 Policy RAG Agent

**This is the only traditional document RAG component in SmartBasket.** Store policies — return policy, shipping policy, sizing guide, care instructions — are genuinely unstructured documents that cannot be reduced to database rows. They are chunked, embedded, and stored in a separate Qdrant collection `policies`.

When a customer asks "can I return a dress I wore once?", the Policy RAG Agent retrieves the most relevant chunks from the policy documents, passes them to Bedrock Sonnet as context, and generates a grounded answer. If no relevant policy exists, it says so explicitly rather than hallucinating.

### 4.7 Purchase Agent

Handles the complete checkout flow via MCP tool calling. Human-in-the-loop before every write operation. The full checkout sequence:

1. `check_stock_status` — confirm availability
2. `get_delivery_estimate` — show delivery window
3. Confirmation gate → `add_to_cart`
4. `get_frequently_bought_together` — cross-sell loop
5. `get_saved_payment_methods` — show saved cards
6. `calculate_order_total` — itemised bill
7. Final confirmation gate → `process_payment`
8. `send_confirmation_email` — automatic post-payment

### 4.8 Scheduled Agents — Run Without User Trigger

**Trend Intelligence Agent:** Runs nightly. Reads the `search_queries` audit table and clusters zero-result queries by embedding similarity. Surfaces the top 10 catalogue gaps to the admin: "47 customers searched for 'sustainable activewear' this month — you have 0 matching products."

**Restock Prediction Agent:** Runs daily. Reads purchase velocity per product from the orders table. Applies a 7-day moving average. Flags products predicted to run out within 7 days at current velocity.

**Post-Purchase Feedback Agent:** Triggers 3 days after confirmed delivery. Opens a conversation with the customer: "How was your [product name]?" Collects rating and optional comment.

**Catalogue Gap Agent:** Runs weekly. Cross-references zero-result query clusters against the current catalogue. Generates a specific gap report with counts and examples.

---

## 5. RAG Strategy — What Goes Where

### 5.1 The Core Principle

Ask one question before deciding: **can this information be expressed as a row in a table with fixed columns?**

If yes → PostgreSQL for exact queries, Qdrant for semantic similarity. Product name, price, colour, material, stock level, rating — all yes.

If no → chunk it, embed it, retrieve with RAG. Return policies, sizing guides, care instructions, brand storytelling — all no.

### 5.2 Qdrant Collections

| Collection        | Content                           | Embedding text                                          | Used by                                      |
| ----------------- | --------------------------------- | ------------------------------------------------------- | -------------------------------------------- |
| `products`      | Product records                   | name + description + category + attributes + top_praise | Product Discovery Agent, Visual Search Agent |
| `policies`      | Policy documents                  | Chunked document text                                   | Policy RAG Agent                             |
| `brand_stories` | Optional brand/product narratives | Long-form content chunks                                | Policy RAG Agent (extended)                  |

### 5.3 Why Product Specs Are Not RAG

Product specifications are structured. A user asking "does this come in size XL?" is answered by `SELECT variants FROM products WHERE id = ?` — not by retrieving text chunks. A user asking "show me blue dresses" is answered by Qdrant vector search with a colour filter on the payload.

Document RAG for product data destroys structure. It takes `{"colour": "navy blue", "size": ["XS", "S", "M", "L"]}` and turns it into a paragraph that an LLM then has to parse back into structure. This is circular and error-prone.

### 5.4 The Policy RAG Pipeline

```
Admin uploads return_policy.pdf or return_policy.txt
    ↓
app/policies/ingest.py
    ↓
PyMuPDF extracts text from PDF (or read plain text directly)
    ↓
RecursiveCharacterTextSplitter
  chunk_size=512, chunk_overlap=50
  separators=["\n\n", "\n", ". ", " "]
    ↓
Each chunk embedded with Jina v3 (retrieval.passage task)
    ↓
Upsert to Qdrant collection: policies
  payload: {chunk_text, source_file, page_number, chunk_index}
    ↓
Policy RAG Agent retrieves top-3 chunks on query
    ↓
Bedrock Sonnet generates grounded answer
  System prompt: "Answer only from the provided policy text.
                  If the policy does not address this question, say so."
```

---

## 6. Recommender System

### 6.1 Why It Fits SmartBasket

The H&M dataset includes 31 million real transactions from 1.3 million customers — real purchase signals, not synthetic. Kafka captures every product view, cart addition, and purchase in real time — the input stream for online updates. The LangGraph agent can explain recommendations in natural language — "based on your previous purchases and customers with similar taste, we especially recommend this" is qualitatively different from a silent ranked list.

### 6.2 Three Recommender Types

**Collaborative Filtering (ALS) — the trained ML model**

Trains on the user-item interaction matrix from purchase history. Uses the `implicit` library's Alternating Least Squares implementation. Produces a latent vector for every user and every product. At serving time, the dot product of a user vector and a product vector is the recommendation score.

Training data: H&M transaction history for bootstrap. Ongoing: purchases from Kafka stream accumulated in an `interactions` PostgreSQL table, retraining weekly via the batch job.

Evaluation metrics logged to MLflow: precision@10, recall@10, NDCG@10. Model promoted to production only if it beats the previous version's precision@10 on the held-out validation set.

**Content-Based — Qdrant nearest neighbours**

Already implemented by the Product Discovery Agent. When a user views a product, find the 10 most similar products in Qdrant by cosine similarity of their embedding vectors. Surface as "Similar items" on the product detail page. Cold-start safe — works for new users with no purchase history.

**Hybrid Blending — the production approach**

For known users (have purchase history), blend ALS score (40%) with semantic similarity score (60%). For new users, use semantic similarity only (100%). The blending weight is configurable via the admin portal settings.

### 6.3 MLflow Experiment Tracking

Every ALS training run logged with: hyperparameters (factors, iterations, regularisation), dataset version (number of users, items, interactions), evaluation metrics (precision@10, recall@10, NDCG@10), training duration, model artifact.

The MLflow model registry has three stages: `Staging`, `Production`, `Archived`. Promotion from Staging to Production requires precision@10 improvement over the current Production model.

### 6.4 Online Updates

The Personalisation Worker consumes `order.created` and `cart.updated` events from Kafka. For every purchase it writes an interaction record to the `user_item_interactions` table: `(user_id, product_id, interaction_type, weight, timestamp)`. Purchases have weight 5. Cart additions have weight 3. Product views have weight 1.

---

## 7. Module Specifications

### 7.1 auth module — `app/auth/`

JWT token issuance and validation. bcrypt password hashing. User JWT (customer or admin, expires 24h). The `get_current_user` dependency reads JWTs. The `require_admin` dependency wraps `get_current_user` and checks role.

### 7.2 products module — `app/products/`

Product catalogue CRUD. Reads `current_price` from Redis cache first, falls back to PostgreSQL. Publishes `product.viewed` to Kafka on every detail fetch. Publishes `product.created` on new product creation. Exposes `GET /products/{id}/similar` using Qdrant nearest-neighbour search. Exposes `GET /products/{id}/frequently-bought` using co-purchase SQL query.

### 7.3 orders module — `app/orders/`

Cart in Redis (TTL 7 days). Orders in PostgreSQL (permanent snapshot). Cart operations read live price from `current_price:{product_id}` Redis key. Kafka consumer for `price.updated` — recalculates active cart totals automatically. Publishes `cart.updated` and `order.created` to Kafka.

### 7.4 search module — `app/search/`

The core retrieval layer. Contains: `embedder.py` (Jina v3 wrapper with task mode selection), `qdrant_ops.py` (upsert, search, delete), `query_router.py` (SEMANTIC/ANALYTICAL/HYBRID/VISUAL classifier), `nl_to_sql.py` (schema-aware SQL generation, validation, execution, audit logging), `constraint_extractor.py` (dynamic attribute-aware filter extraction), `hybrid_search.py` (SQL constrains candidates, vectors rank within), `reranker.py` (flashrank cross-encoder), `pricing_engine.py` (background task, demand-based price adjustment).

### 7.5 agent module — `app/agent/`

LangGraph supervisor and all sub-agents. `graph.py` defines the supervisor graph with conditional routing edges. `state.py` defines the `SmartBasketState` TypedDict. `prompts.py` contains all LLM prompts versioned by name. `nodes/` folder contains one file per node. Each file has a typed function signature, docstring explaining the node's role and connecting edges, and the implementation.

### 7.6 recommendations module — `app/recommendations/`

ALS model serving and content-based fallback. `als_model.py` loads the current Production model from MLflow registry and caches it in memory. `content_based.py` wraps the Qdrant nearest-neighbour query. `blending.py` combines scores with configurable weights. `router.py` exposes `GET /recommendations/{user_id}` — checks for ALS model availability, falls back to content-based for unknown users.

### 7.7 policies module — `app/policies/`

Policy document RAG. `ingest.py` handles PDF/text upload, chunking, embedding, Qdrant upsert to `policies` collection. `retriever.py` runs the semantic search over policy chunks. `router.py` exposes `POST /policies/upload` (admin only) and `POST /policies/query` (internal, called by Policy RAG Agent).

### 7.8 analytics module — `app/analytics/`

Admin-only NL-to-SQL for business intelligence. Separate from customer-facing search — uses different schema injection focused on analytics tables. Exposes `POST /analytics/query`. Every query logged to `nl_sql_audit` table.

### 7.9 mcp module — `app/mcp/`

MCP server on port 8006. Phase 1 tools (checkout flow): `check_stock_status`, `get_delivery_estimate`, `add_to_cart`, `remove_from_cart`, `apply_coupon`, `get_cart_summary`, `get_saved_payment_methods`, `calculate_order_total`, `process_payment`, `send_confirmation_email`, `get_frequently_bought_together`, `get_compatible_accessories`. Admin tools: `update_stock_count`, `create_discount`, `get_sales_summary`, `send_bulk_notification`.

---

## 8. Kafka Event Architecture

### 8.1 Topics

| Topic                | Producer        | Consumers                                                       | What triggers it                   |
| -------------------- | --------------- | --------------------------------------------------------------- | ---------------------------------- |
| `product.viewed`   | products module | search module (demand counter), personalisation worker          | Customer views product detail page |
| `product.created`  | products module | embedding worker                                                | Admin adds new product             |
| `cart.updated`     | orders module   | personalisation worker                                          | Customer adds or removes cart item |
| `order.created`    | orders module   | personalisation worker (weight 5), post-purchase feedback agent | Customer completes checkout        |
| `price.updated`    | pricing engine  | orders module (recalculate cart totals)                         | Pricing engine adjusts price       |
| `catalog.ingested` | ETL pipeline    | embedding worker                                                | Full catalogue ingestion complete  |

### 8.2 The Demand Signal Chain

```
Customer views product
    ↓
products module publishes product.viewed
    ↓
search module Kafka consumer: INCR views:{product_id} in Redis (TTL 24h)
    ↓
Pricing engine runs every 120 seconds:
  reads views:{product_id}
  if views > threshold AND stock > 5: price × 1.05
  if abandonment_rate > 60% AND stock > 80%: price × 0.95
  writes new price to Redis current_price:{product_id}
  writes to price_history table
  publishes price.updated to Kafka
    ↓
orders module Kafka consumer reads price.updated:
  finds all active carts containing this product
  recalculates cart totals in Redis
    ↓
next customer viewing their cart sees updated price
```

---

## 9. Database Schema

### 9.1 PostgreSQL Tables (Supabase)

**Core tables**

```sql
products (id, external_product_id, title, description,
          category, brand, price, currency, url,
          attributes JSONB, inventory_status, variants JSONB,
          tags JSONB, image_url,
          style_sentiment, quality_sentiment, fit_sentiment,
          value_sentiment, comfort_sentiment,
          keyboard_sentiment, thermal_sentiment,
          top_complaint, top_praise,
          embedding_status, sentiment_scored_at,
          last_ingested_at, is_active)

reviews (id, product_id, rating, review_text,
         reviewer_name, helpful_votes, created_at)

users (id, email, hashed_password, role, is_active, created_at)

user_preferences (id, user_id, preferred_brands JSONB,
                  preferred_categories JSONB, typical_price_min,
                  typical_price_max, feature_priorities JSONB,
                  last_updated)

orders (id, user_id, items JSONB, total_amount,
        currency, status, stripe_payment_intent_id, created_at)

cart_sessions (id, user_id, redis_key, item_count, last_updated)

price_history (id, product_id, old_price, new_price,
               change_percentage, reason, changed_at)
```

**Analytics and AI tables**

```sql
search_queries (id, user_id, query_text, query_type,
                result_count, top_result_id, clicked_result_id,
                session_id, created_at)

nl_sql_audit (id, natural_language_query, generated_sql,
              validation_passed, retry_count, rows_returned, created_at)

user_item_interactions (id, user_id, product_id,
                        interaction_type, weight, session_id, created_at)

admin_notifications (id, type, title, body, metadata JSONB,
                     is_read, created_at)

catalog_ingestion_jobs (id, source_type, source_config JSONB,
                        status, total_rows, processed_rows, failed_rows,
                        errors JSONB, started_at, completed_at)

policy_documents (id, filename, source_type, chunk_count,
                  embedding_status, uploaded_at, last_updated)
```

### 9.2 Redis Key Design

| Key Pattern                       | TTL    | Purpose                                            |
| --------------------------------- | ------ | -------------------------------------------------- |
| `cart:{user_id}`                | 7 days | Hash of cart items with live prices                |
| `current_price:{product_id}`    | 10 min | Live price from pricing engine                     |
| `views:{product_id}`            | 24h    | Rolling demand counter                             |
| `history:{session_id}`          | 1h     | Last 10 conversation turns                         |
| `search_cache:{query_hash}`     | 1h     | Cached semantic search results                     |
| `sql_cache:{query_hash}`        | 30 min | Cached NL-to-SQL results                           |
| `prefs_cache:{user_id}`         | 30 min | User preference profile                            |
| `rec_cache:{user_id}`           | 30 min | ALS recommendation scores                          |
| `sentiment_queued:{product_id}` | 1h     | Prevents duplicate scoring jobs                    |
| `product_attrs`                 | 6h     | Available attribute keys for constraint extraction |
| `embedding_queue`               | —     | Redis list of product IDs awaiting Jina embedding  |

### 9.3 Qdrant Collections

```
products
  dimensions: 1024 (Jina v3)
  distance: Cosine
  payload: {product_id, title, brand, category, price, rating,
            stock_available, attributes, sentiment_scores,
            image_url, embedding_text_hash}

policies
  dimensions: 1024 (Jina v3)
  distance: Cosine
  payload: {chunk_text, source_file, page_number, chunk_index, document_id}

brand_stories  (optional, created on demand)
  dimensions: 1024 (Jina v3)
  distance: Cosine
  payload: {chunk_text, product_id, story_type, source_file}
```

---

## 10. ETL Data Pipeline

### 10.1 Pipeline Overview

```mermaid
flowchart LR
    subgraph Sources["Data Sources"]
        HM[H&M HuggingFace\nDataset\nBootstrap source]
        CSV[CSV Upload\nadmin portal]
        JSON[JSON Upload\nadmin portal]
        SF[Snowflake\ncredentials\nscheduled sync]
        SHOPIFY[Shopify API\noauth integration\nsync on webhook]
    end

    subgraph Extract["Extract Layer — workers/etl/connectors/"]
        HM_CONN[hm_connector.py\nHuggingFace datasets]
        CSV_CONN[csv_connector.py]
        JSON_CONN[json_connector.py]
        SF_CONN[snowflake_connector.py]
        SHOPIFY_CONN[shopify_connector.py]
    end

    subgraph Transform["Transform Layer — workers/etl/"]
        COLMAP[column_mapper.py\nFuzzy match → canonical schema]
        VALIDATE[validator.py\nRequired fields\nRow-level errors]
        NORMALISE[normaliser.py\nPrice to standard currency\nAttribute normalisation]
        ENRICH[enricher.py\nVision LLM for image attributes\nBedrock Haiku]
    end

    subgraph Load["Load Layer — workers/etl/"]
        PG_LOAD[pg_loader.py\nUpsert to products\nON CONFLICT DO UPDATE]
        SENTIMENT_Q[sentiment_queue.py\nQueue products for\naspect scoring]
        EMB_Q[embedding_queue.py\nQueue for Jina v3\nembedding generation]
    end

    subgraph PostLoad["Post-Load Workers"]
        SENT_WORKER[Sentiment Worker\nBedrock Haiku\nbatch 50 products\ntop 1500 first]
        EMB_WORKER[Embedding Worker\nJina v3 API\nbatch 100 products\nupsert to Qdrant]
        ATTR_UPDATE[Attribute Indexer\nUpdate product_attrs\nin Redis after ingestion]
    end

    Sources --> Extract
    Extract --> Transform
    Transform --> Load
    Load --> PostLoad
```

### 10.2 The H&M Dataset

The primary data source is the H&M Personalised Fashion Recommendations dataset from HuggingFace (`Qdrant/hm_ecommerce_products`). It contains:

- ~105,000 fashion products with real images hosted on H&M's CDN
- Product attributes: garment type, colour, pattern, material, occasion
- 31 million transactions from 1.3 million customers for the recommender
- Review data for sentiment scoring

This is the bootstrap dataset. The ETL pipeline is designed to also accept CSV, JSON, Shopify, and Snowflake sources so the same infrastructure handles any real catalogue a client provides.

### 10.3 The Connector Interface

Every data source connector implements the same three methods. `validate_connection()` tests credentials and returns success/failure with a descriptive message. `fetch_products()` returns an async iterator of raw product dictionaries in the source's native schema. `get_schema()` returns the source's column names so the column mapper can run.

### 10.4 Column Mapping

Different sources name the same fields differently. The column mapper does fuzzy matching against candidate lists:

```python
TITLE_CANDIDATES = [
    "title", "name", "product_name", "product_title",
    "item_name", "item_title", "heading", "label",
    "article_id", "prod_name"
]
PRICE_CANDIDATES = [
    "price", "cost", "amount", "regular_price", "sale_price",
    "unit_price", "retail_price", "selling_price"
]
DESCRIPTION_CANDIDATES = [
    "description", "desc", "details", "about", "summary",
    "product_description", "short_description", "detail_desc"
]
```

On first ingestion: detected mapping is stored in `catalog_ingestion_jobs` metadata and reused for future syncs from the same source.

### 10.5 Sentiment Scoring Strategy

Fashion sentiment dimensions differ from electronics. The seven aspects scored for clothing are: **style** (aesthetic quality, design appeal), **quality** (build/fabric quality, durability), **fit** (sizing accuracy, comfort), **value** (price-to-quality ratio), **comfort** (wearability, feel against skin), **versatility** (how many occasions it works for), and **delivery** (packaging, transit quality).

Score in priority order to minimise cost. Process top 1500 products by review count first. Remaining products scored lazily when a product page is first viewed.

### 10.6 Embedding Generation

Products must have sentiment scores before embedding because `top_praise` is part of the embedding text. The embedding worker checks `sentiment_scored_at IS NOT NULL` before processing.

```python
def build_embedding_text(product: Product) -> str:
    attrs = " ".join(f"{k}: {v}" for k, v in product.attributes.items())
    praise = product.top_praise or ""
    return (
        f"{product.title}. {product.description}. "
        f"Category: {product.category}. Brand: {product.brand}. "
        f"{attrs}. {praise}"
    ).strip()
```

Jina v3 API called with `task="retrieval.passage"` for product embeddings. `task="retrieval.query"` for search query embeddings.

---

## 11. Frontend — Two Surfaces, One Codebase

Two React applications built from one Vite + TypeScript monorepo. They share component libraries, API client code, and design tokens. They are deployed to different Vercel projects but built from the same `frontend/` folder.

### 11.1 Customer Storefront (`frontend/storefront/`)

Dark mode by default. Product grid with real H&M images, real prices, real sentiment bars. Search bar that triggers semantic or hybrid retrieval. Visual search button in the search bar for image upload. Product detail page with seven animated sentiment bars (animated fill on load), `top_praise` in a green quote card, `top_complaint` in an amber quote card, frequently bought together section, similar items section. SmartBasket chat widget floating bottom-right — slides in as a side panel without covering the product page. Cart icon in nav opens chat in checkout mode.

### 11.2 Admin Portal (`frontend/admin/`)

Different visual identity — lighter, more data-dense. Sidebar navigation with sections: Dashboard, Catalogue, Analytics, Policies, Recommender, Settings.

The catalogue management section: product table with sync status, sentiment coverage, embedding coverage. The analytics section: NL-to-SQL query interface. The policies section: document upload interface for policy RAG. Settings: API keys, tone preset configuration, webhook endpoints.

### 11.3 Embeddable Widget (`frontend/widget/`)

A separate Vite build target that produces a single `widget.js` file. Hosted via Vercel. The integration is one line of HTML that any webstore can drop in. The widget renders the SmartBasket chat interface in a lightweight manner, using a static API key for the hosted demo.

```html
<script 
  src="https://smartbasket.vercel.app/widget.js"
  data-position="bottom-right"
  data-theme="dark"
  data-greeting="Hi! How can I help you find something today?">
</script>
```

---

## 12. Admin Dashboard — What It Contains

The admin dashboard is the primary value delivery surface for the store owner. It is not a configuration UI — it is an intelligence platform.

### 12.1 Overview Panel

Real-time metrics for today, this week, and this month:

- Total conversations and unique users
- Conversation-to-cart conversion rate
- Cart-to-purchase conversion rate
- Average conversation length (turns)
- Top 5 search queries today

### 12.2 Catalogue Health Panel

- Total products indexed vs total uploaded
- Products with complete sentiment scores vs pending
- Products with embeddings vs pending
- Low stock alerts (configurable threshold)
- Products with zero sales in last 30 days
- Last ingestion timestamp and status

### 12.3 Search Intelligence Panel

**Zero-result queries:** Every query that returned 0 results, grouped by similarity into themes, with count and first-seen date. This is the catalogue gap detector. Export as CSV for the buying team.

**Low-engagement queries:** Queries that returned results but had zero clicks — signals description quality issues.

**Top performing queries:** Queries with the highest click-through rate.

**Query volume trends:** Week-over-week change in search volume per category.

### 12.4 NL-to-SQL Query Interface

Full-screen split panel. Left: text input with clickable example query chips. Right: generated SQL in a syntax-highlighted block, results as a formatted table, one-sentence insight from the LLM.

Example chips: "Which products have zero sales this month?", "What is the average order value this week?", "Show products with stock below 10 units", "Which categories are growing fastest?"

### 12.5 Agent Performance Panel

AI-specific metrics:

- Grounding rate: percentage of responses that cited specific products
- Clarification rate: percentage of queries that needed a clarifying question
- Sub-agent routing distribution: how often each agent type is invoked
- LangSmith trace link for any conversation

### 12.6 Notifications Panel

Alerts generated by the scheduled agents:

- Low stock predictions from the Restock Prediction Agent
- Catalogue gap reports from the Trend Intelligence Agent
- Post-purchase feedback summaries (average rating this week, new complaints)

### 12.7 Recommender Performance Panel

- Current model version in production (from MLflow registry)
- precision@10 and recall@10 from the last training run
- Training history chart showing metric improvement over time
- Last retrain date and next scheduled retrain
- Cold-start percentage
- Recommendation click-through rate

---

## 13. Observability Stack

### 13.1 LangSmith — Agent Observability

Every agent interaction produces a LangSmith trace showing: which nodes ran and in what order, what each node received as input, what it produced as output, how long each node took, the full prompt sent to each LLM call, the token count and cost of each call, which Qdrant query ran and how many results it returned, which SQL was generated and executed.

Set `LANGCHAIN_TRACING_V2=true` and `LANGCHAIN_API_KEY` in the environment. No code changes needed.

### 13.2 MLflow — Model Observability

Every ALS recommender training run logged: hyperparameters, dataset statistics, evaluation metrics, training duration, model artifact. Model registry tracks Staging → Production → Archived lifecycle.

### 13.3 Prometheus + Grafana — System Observability

FastAPI exposes `/metrics` endpoint via `prometheus-fastapi-instrumentator`. Metrics collected: request rate per endpoint, P50/P95/P99 latency per endpoint, error rate, active connections.

Kafka metrics: consumer lag per topic per consumer group, message production rate.

Redis metrics: command rate, memory usage, hit/miss ratio per key pattern.

Grafana dashboards:

1. **API Health:** Request rate, latency percentiles, error rate per endpoint
2. **Kafka Pipeline:** Consumer lag, throughput per topic, pricing engine cycle timing
3. **AI Layer:** LLM call latency, token usage per model, embedding generation throughput
4. **Business Metrics:** Conversations per day, conversion rates, recommendation click-through

### 13.4 Structured Logging

Every FastAPI request logged with: `user_id`, `endpoint`, `method`, `status_code`, `duration_ms`, `request_id`. Every agent interaction logged with: `session_id`, `intent_classified`, `sub_agent_invoked`, `retrieval_method`, `llm_calls_made`, `total_duration_ms`. JSON format throughout.

---

## 14. Deployment Architecture

### 14.1 Local Development

```bash
docker-compose up
# Starts: PostgreSQL, Redis, Qdrant, Kafka, Zookeeper, Kafka UI
# FastAPI runs locally: uvicorn app.main:app --reload
# Workers run in separate terminal: python workers/embedding_worker.py
```

No cloud costs during development. All infrastructure in Docker.

### 14.2 Production Stack

```
EC2 t3.small ($15/month)
  ├── Nginx (SSL, rate limiting, reverse proxy)
  ├── FastAPI app (uvicorn, port 8000)
  ├── Kafka + Zookeeper (Docker, internal only)
  ├── Background workers (systemd services)
  └── MCP server (port 8006, internal only)

Supabase (free tier)
  └── PostgreSQL

Qdrant Cloud (free 1GB)
  └── products + policies collections

Upstash Redis (free tier)
  └── All caching and session state

Vercel (free)
  ├── Customer storefront
  ├── Admin portal
  └── Widget

Amazon Bedrock (pay per token ~$5-15/month at portfolio scale)
  └── eu-north-1, IAM-authenticated

Jina API (free tier)
  └── Embeddings for products and queries

MLflow Tracking Server (self-hosted on EC2)
  └── Experiment tracking, model registry
```

### 14.3 Terraform Infrastructure

```
terraform/
├── main.tf              # EC2 t3.small, Elastic IP
├── security_groups.tf   # 80/443 open, 22 restricted to your IP
├── variables.tf         # aws_region, instance_type, your_ip
├── outputs.tf           # public_ip, ssh_command, app_url
└── backend.tf           # S3 remote state
```

### 14.4 CI/CD — GitHub Actions

```yaml
# .github/workflows/deploy.yml
# Triggers: push to main

Steps:
  1. Run pytest (all modules, with coverage)
  2. Check NL-to-SQL golden test set (20 queries, must pass ≥85%)
  3. Check query router golden test set (30 queries, must pass ≥85%)
  4. Build Docker images for workers
  5. SSH to EC2, git pull, restart FastAPI systemd service
  6. Run smoke tests against production endpoint
  7. Notify on failure
```

Evaluation-gated deployment: if NL-to-SQL accuracy drops below 85%, the deployment fails before touching production.

---

## 15. Cost Analysis

### 15.1 Development Phase — $0/month

Everything runs locally in Docker Compose. Bedrock requires AWS credentials (already set up from ShopSense). Jina free tier for embeddings. Total: $0.

### 15.2 Portfolio Deployment

| Component           | Provider                   | Cost                  |
| ------------------- | -------------------------- | --------------------- |
| Customer storefront | Vercel free                | $0                    |
| Admin portal        | Vercel free                | $0                    |
| PostgreSQL          | Supabase free (500MB)      | $0                    |
| Vector DB           | Qdrant Cloud free (1GB)    | $0                    |
| Redis               | Upstash free (10k req/day) | $0                    |
| LLM                 | Amazon Bedrock             | ~$3-8/month           |
| Embeddings          | Jina API free tier         | $0                    |
| EC2 t3.small        | AWS                        | $0-15/month           |
| MLflow              | Self-hosted on EC2         | $0 extra              |
| **Total**     |                            | **$3-23/month** |

---

## 16. Environment Configuration

### 16.1 Complete `.env.example`

```bash
# ── Application ────────────────────────────────────────────────────────
APP_ENV=development
APP_SECRET_KEY=                    # openssl rand -hex 32
JWT_ALGORITHM=HS256
JWT_EXPIRY_HOURS=24

# ── Database ───────────────────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://smartbasket:smartbasket@localhost:5432/smartbasket
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=

# ── Redis ──────────────────────────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0

# ── Qdrant ─────────────────────────────────────────────────────────────
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=                    # Empty for local Docker
QDRANT_PRODUCTS_COLLECTION=products
QDRANT_POLICIES_COLLECTION=policies

# ── Kafka ──────────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_CONSUMER_GROUP_ID=smartbasket-consumer-group
KAFKA_TOPIC_PRODUCT_VIEWED=product.viewed
KAFKA_TOPIC_PRODUCT_CREATED=product.created
KAFKA_TOPIC_CART_UPDATED=cart.updated
KAFKA_TOPIC_ORDER_CREATED=order.created
KAFKA_TOPIC_PRICE_UPDATED=price.updated
KAFKA_TOPIC_CATALOG_INGESTED=catalog.ingested

# ── AWS / Bedrock ──────────────────────────────────────────────────────
AWS_REGION=eu-north-1
AWS_PROFILE=smartbasket-dev
BEDROCK_GENERATION_MODEL_ID=eu.anthropic.claude-sonnet-4-5-20250929-v1:0
BEDROCK_FAST_MODEL_ID=eu.anthropic.claude-haiku-4-5-20251001-v1:0

# ── Embeddings ─────────────────────────────────────────────────────────
EMBEDDING_PROVIDER=JINA
EMBEDDING_DIMENSIONS=1024
JINA_API_KEY=
JINA_MODEL=jina-embeddings-v3

# ── MCP Server ─────────────────────────────────────────────────────────
MCP_SERVER_PORT=8006
MCP_SERVER_URL=http://localhost:8006

# ── External Services ──────────────────────────────────────────────────
SENDGRID_API_KEY=
SENDGRID_FROM_EMAIL=noreply@smartbasket.ai
STRIPE_SECRET_KEY=                 # sk_test_... for development
STRIPE_WEBHOOK_SECRET=

# ── MLflow ─────────────────────────────────────────────────────────────
MLFLOW_TRACKING_URI=http://localhost:5000
MLFLOW_EXPERIMENT_NAME=smartbasket-recommender

# ── Observability ──────────────────────────────────────────────────────
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=
LANGCHAIN_PROJECT=smartbasket

# ── Pricing Engine ─────────────────────────────────────────────────────
PRICING_ENGINE_INTERVAL_SECONDS=120
PRICING_DEMAND_THRESHOLD=50
PRICING_MAX_MULTIPLIER=1.30
PRICING_MIN_MULTIPLIER=0.80

# ── Recommender ────────────────────────────────────────────────────────
ALS_FACTORS=64
ALS_ITERATIONS=20
ALS_REGULARIZATION=0.1
REC_SEMANTIC_WEIGHT=0.60
REC_COLLABORATIVE_WEIGHT=0.40
REC_RETRAIN_DAY=monday
REC_MIN_PRECISION_FOR_PROMOTION=0.35
```

---

## 17. Repository Structure

```
smartbasket/
│
├── app/                            # Modular monolith — one FastAPI app
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── redis_client.py
│   │
│   ├── auth/
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── service.py
│   │   ├── dependencies.py
│   │   ├── utils.py
│   │   └── router.py
│   │
│   ├── products/
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── service.py
│   │   ├── kafka.py
│   │   └── router.py
│   │
│   ├── orders/
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── service.py
│   │   ├── kafka_producer.py
│   │   ├── kafka_consumer.py
│   │   └── router.py
│   │
│   ├── users/
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── service.py
│   │   └── router.py
│   │
│   ├── search/
│   │   ├── embedder.py
│   │   ├── qdrant_ops.py
│   │   ├── query_router.py
│   │   ├── constraint_extractor.py
│   │   ├── nl_to_sql.py
│   │   ├── hybrid_search.py
│   │   ├── reranker.py
│   │   ├── kafka_consumer.py
│   │   ├── pricing_engine.py
│   │   └── router.py
│   │
│   ├── agent/
│   │   ├── graph.py
│   │   ├── state.py
│   │   ├── prompts.py
│   │   ├── router.py
│   │   └── nodes/
│   │       ├── supervisor.py
│   │       ├── product_discovery.py
│   │       ├── text2sql.py
│   │       ├── visual_search.py
│   │       ├── comparison.py
│   │       ├── policy_rag.py
│   │       ├── purchase_agent.py
│   │       ├── clarifying_question.py
│   │       ├── propose_action.py
│   │       ├── await_confirmation.py
│   │       ├── execute_tool.py
│   │       ├── personalise.py
│   │       ├── synthesise.py
│   │       ├── save_history.py
│   │       └── refuse.py
│   │
│   ├── recommendations/
│   │   ├── als_model.py
│   │   ├── content_based.py
│   │   ├── blending.py
│   │   └── router.py
│   │
│   ├── policies/
│   │   ├── ingest.py
│   │   ├── retriever.py
│   │   ├── models.py
│   │   └── router.py
│   │
│   ├── analytics/
│   │   ├── nl_to_sql_admin.py
│   │   └── router.py
│   │
│   └── mcp/
│       ├── server.py
│       └── tools/
│           ├── checkout.py
│           ├── product_intel.py
│           ├── wishlist.py
│           ├── orders.py
│           └── admin.py
│
├── workers/
│   ├── embedding_worker.py
│   ├── personalisation_worker.py
│   ├── sentiment_worker.py
│   ├── recommender_trainer.py
│   │
│   ├── scheduled_agents/
│   │   ├── trend_intelligence.py
│   │   ├── restock_prediction.py
│   │   ├── post_purchase.py
│   │   └── catalogue_gap.py
│   │
│   └── etl/
│       ├── pipeline.py
│       ├── column_mapper.py
│       ├── validator.py
│       ├── normaliser.py
│       ├── enricher.py
│       ├── pg_loader.py
│       └── connectors/
│           ├── base.py
│           ├── hm_connector.py
│           ├── csv_connector.py
│           ├── json_connector.py
│           ├── snowflake_connector.py
│           └── shopify_connector.py
│
├── data/
│   └── sample/
│       └── hm_sample_100.json
│
├── database/
│   └── migrations/
│       ├── 001_create_users.sql
│       ├── 002_create_products.sql
│       ├── 003_create_reviews.sql
│       ├── 004_create_orders.sql
│       ├── 005_create_price_history.sql
│       ├── 006_create_user_preferences.sql
│       ├── 007_create_analytics_tables.sql
│       ├── 008_create_interactions.sql
│       ├── 009_create_policy_documents.sql
│       └── 010_create_ingestion_jobs.sql
│
├── frontend/
│   ├── storefront/
│   │   ├── src/
│   │   │   ├── components/
│   │   │   │   ├── ProductGrid.tsx
│   │   │   │   ├── ProductDetail.tsx
│   │   │   │   ├── SentimentBars.tsx
│   │   │   │   ├── SearchBar.tsx
│   │   │   │   ├── VisualSearchButton.tsx
│   │   │   │   ├── SmartBasketChat.tsx
│   │   │   │   ├── RecommendationRow.tsx
│   │   │   │   └── PriceIndicator.tsx
│   │   │   ├── App.tsx
│   │   │   └── main.tsx
│   │   └── package.json
│   │
│   ├── admin/
│   │   ├── src/
│   │   │   ├── components/
│   │   │   │   ├── OverviewPanel.tsx
│   │   │   │   ├── CatalogueHealth.tsx
│   │   │   │   ├── SearchIntelligence.tsx
│   │   │   │   ├── NLQueryInterface.tsx
│   │   │   │   ├── AgentPerformance.tsx
│   │   │   │   ├── RecommenderPanel.tsx
│   │   │   │   ├── NotificationsPanel.tsx
│   │   │   │   └── PolicyUpload.tsx
│   │   │   ├── App.tsx
│   │   │   └── main.tsx
│   │   └── package.json
│   │
│   └── widget/
│       ├── src/
│       │   └── widget.tsx
│       └── vite.config.ts
│
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   ├── security_groups.tf
│   ├── backend.tf
│   └── outputs.tf
│
├── tests/
│   ├── auth/
│   ├── products/
│   ├── orders/
│   ├── search/
│   │   ├── test_query_router.py
│   │   └── test_nl_to_sql.py
│   ├── agent/
│   │   ├── test_supervisor.py
│   │   └── test_tool_calling.py
│   ├── recommendations/
│   └── policies/
│
├── docker-compose.yml
├── docker-compose.override.yml
├── pyproject.toml
├── Makefile
└── .env.example
```

---

## 18. Day-by-Day Build Plan

### Status Overview

```
COMPLETED — Days 1–17 (ShopSense foundation):
  Core infrastructure, auth, products, orders, users,
  Kafka pipeline, search (semantic / NL-to-SQL / hybrid),
  LangGraph agent framework, MCP tool calling,
  pricing engine, personalisation worker,
  post-purchase worker, frontend (shopping UI + chat),
  Supabase migrations, Docker Compose, Terraform scaffold.

REMAINING — Days 18–37 (SmartBasket-specific work):
  H&M ETL pipeline, fashion domain data,
  visual search agent, comparison agent,
  policy RAG agent, recommender system (ALS + MLflow),
  scheduled agents, admin dashboard,
  fashion storefront frontend, observability stack,
  CI/CD, production deployment, load testing,
  embeddable widget, final polish.
```

---

### ✅ Days 1–17 — COMPLETED (ShopSense Foundation)

All foundational infrastructure is in place from the ShopSense build. The components below are complete and carry over directly.

| Day | What was built                         | Key deliverable                                                                                                          |
| --- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| 1   | Infrastructure scaffold                | docker-compose, config.py, database.py, redis_client.py, all migration stubs, Makefile                                   |
| 2   | Auth module                            | JWT, bcrypt, get_current_user, register/login/me endpoints, full test suite                                              |
| 3   | Products module + Kafka                | CRUD, product.viewed publisher, product.created publisher, Redis price overlay                                           |
| 4   | Data pipeline scaffold                 | ETL connector interface, column mapper, validator, normaliser, pg_loader                                                 |
| 5   | Orders module + Users module           | Cart (Redis), orders (PostgreSQL), user_preferences, personalisation worker skeleton                                     |
| 6   | Embedding worker + Semantic search     | Jina v3 wrapper, Qdrant upsert + search, flashrank reranker, basic /search endpoint                                      |
| 7   | Query router + NL-to-SQL + Hybrid      | SEMANTIC/ANALYTICAL/HYBRID classifier, sqlparse validator, audit logging, hybrid RRF merge                               |
| 8   | LangGraph supervisor + core sub-agents | graph.py, state.py, prompts.py, supervisor, product_discovery, text2sql, synthesise, save_history, refuse                |
| 9   | Comparison agent + Policy RAG stub     | comparison.py fetches multi-product details, policy RAG node skeleton with Qdrant stub                                   |
| 10  | MCP server + Purchase agent            | All 10+ checkout tools, propose_action, await_confirmation (CONFIRM/DECLINE/AMBIGUOUS), execute_tool, full checkout flow |
| 11  | Recommender scaffold + MLflow setup    | als_model.py stub, content_based.py (Qdrant KNN), blending.py, MLflow tracking server running                            |
| 12  | Scheduled agents scaffold              | APScheduler setup, post_purchase.py, trend_intelligence.py stub, restock_prediction.py stub                              |
| 13  | Admin dashboard API                    | /analytics/query, /analytics/overview, /analytics/agent-metrics, nl_sql_audit table                                      |
| 14  | Customer storefront                    | ProductGrid, ProductDetail, SentimentBars, SearchBar, SmartBasketChat widget                                             |
| 15  | Admin portal frontend                  | OverviewPanel, CatalogueHealth, NLQueryInterface, AgentPerformance, NotificationsPanel                                   |
| 16  | Pricing engine + Kafka consumers       | demand signal chain complete, price.updated recalculates carts, views:{product_id} counter                               |
| 17  | Integration tests + golden sets        | 30-query router golden set (≥85%), 20-query NL-to-SQL golden set (≥85%), intent classifier (≥90%)                     |

---

### Day 18 — H&M Data Download + ETL Pipeline

This is the data foundation day. Everything built from Day 18 onwards needs real H&M fashion data to be meaningful. No shortcuts with synthetic data — the H&M dataset has real images, real attributes, and real purchase history.

Write `workers/etl/connectors/hm_connector.py`. Uses the `datasets` library to stream `Qdrant/hm_ecommerce_products` from HuggingFace. Implements the connector interface: `validate_connection()` checks library availability and network access, `fetch_products()` returns an async generator of raw H&M product dicts, `get_schema()` returns the H&M column names. Do not load the full dataset into RAM — stream it.

Write the H&M column mapping config. H&M's schema uses `article_id`, `prod_name`, `product_type_name`, `colour_group_name`, `graphical_appearance_name`, `detail_desc`, `section_name`. Map these to SmartBasket's canonical schema: `external_product_id`, `title`, `category`, `attributes.colour`, `attributes.pattern`, `description`, `brand`.

Run `workers/etl/pipeline.py` against the H&M connector. First run: ~105,000 products, takes approximately 20 minutes to ingest. Write progress logging — every 1,000 rows log count and estimated time remaining. After ingestion, run `workers/sentiment_worker.py` against the top 1,500 products by review count. Uses Bedrock Haiku with the fashion-specific 7-aspect prompt (style, quality, fit, value, comfort, versatility, delivery). Takes approximately 25 minutes.

Verify the data: `SELECT COUNT(*) FROM products` returns the full count. Browse 10 random products, verify image URLs resolve to real H&M images. `SELECT title, top_praise, style_sentiment FROM products WHERE sentiment_scored_at IS NOT NULL LIMIT 5` returns populated sentiment data.

**Demo at end of Day 18:** `SELECT COUNT(*) FROM products` returns 105,000+. Open any product via `GET /products/{id}` and see real H&M image URL, real product description, real sentiment scores. The data pipeline ran end-to-end without manual intervention.

---

### Day 19 — Embedding Generation + Qdrant Population

Day 18 produced sentiment-scored products. Today you generate 1024-dimensional Jina v3 embeddings and populate the Qdrant collection.

Write `workers/embedding_worker.py` (finalise the full implementation). Reads product IDs from the `embedding_queue` Redis list (populated by a queue script that queries `WHERE sentiment_scored_at IS NOT NULL AND embedding_status = 'pending'`). Calls Jina v3 API with `task="retrieval.passage"` in batches of 100. Builds the embedding text using `build_embedding_text()` — includes title, description, category, brand, all attributes, and `top_praise`. Upserts to the `products` Qdrant collection with the full payload. Updates `embedding_status = 'embedded'` in PostgreSQL. Handles API rate limits with exponential backoff.

Queue all 1,500 sentiment-scored products into Redis, run the worker. Takes approximately 15 minutes for 1,500 products. Verify Qdrant collection: `GET /collections/products` via Qdrant dashboard shows ~1,500 points.

Run the semantic search quality check. Write `data/verification/search_quality_check.py` — 15 fashion-specific test queries: "floral summer dress", "something for a beach wedding", "casual wear for work from home", "formal evening outfit", "sustainable fashion", "oversized cosy knit", "gym activewear", "office smart casual", "date night outfit", "gift for teenage girl", "warm winter coat", "lightweight jacket for spring", "swimwear for tropical holiday", "party dress under ₹2000", "comfortable shoes for standing all day". For each query, print the top-5 results with their similarity scores. Every result should be visually inspectable as relevant. Screenshot the output for demo materials.

**Demo at end of Day 19:** Qdrant dashboard shows 1,500 vectors. `POST /search` with "floral summer dress" returns relevant H&M dresses within 800ms. Compare side-by-side with a PostgreSQL keyword search for the same query — semantic search returns qualitatively better results. The quality check script passes all 15 queries.

---

### Day 20 — Multi-Catalogue Config-Driven Search Layer

#### Why config-driven, not fashion-specific

The search layer could be rewritten purely for H&M fashion — but that produces a second throw-away codebase after the electronics one. The correct move is a **config-driven architecture** where a `CatalogueConfig` object describes what a domain looks like. The extractor, router, NL-to-SQL, and filter builder all read from config and work for any domain. Adding books, furniture, or sportswear later means writing one config — not touching any search logic.

---

#### The `CatalogueConfig` data model

Write `app/search/catalogue_config.py` first — everything else imports from it.

```python
@dataclass
class AttrDef:
    key: str              # "colour", "brand", "ram"
    display_name: str
    type: Literal["keyword", "range", "bool"]
    is_qdrant_filter: bool   # True = hard Qdrant metadata filter
                             # False = soft, folded into rewritten_query
    redis_values_key: str    # "attrs:fashion:colour"

@dataclass
class CatalogueConfig:
    client_id: str           # "fashion", "electronics"
    display_name: str        # "H&M Fashion", "Tech Store"
    qdrant_collection: str   # "hm_products", "laptops"

    filterable_attrs: list[AttrDef]

    price_field_name: str    # "current_price" — never hardcoded elsewhere
    price_currency: str      # "USD" — internal storage currency

    sentiment_fields: list[str]   # domain-specific sentiment columns
    schema_hint: str              # injected verbatim into NL-to-SQL prompt
    routing_examples: list[tuple[str, str]]  # few-shot (query, route) pairs for LLM prompt
    embedding_fields: list[str]   # which DB fields go into passage text
```

Key decisions baked in:

- `price_field_name` is in config so no component hardcodes `current_price`
- `is_qdrant_filter` distinguishes hard metadata filters (colour → Qdrant) from soft semantic enrichment (occasion → rewritten_query)
- `sentiment_fields` feeds `qdrant_ops._scored_point_to_result` so it reads the right columns per domain
- `routing_examples` are few-shot prompt examples — separate from the 30-query offline test set in `tests/`

Provide two initial configs: `FASHION_CATALOGUE` and `ELECTRONICS_CATALOGUE`. Expose `get_catalogue(client_id: str) -> CatalogueConfig` that raises `HTTPException(400)` on unknown IDs — never a bare `KeyError`.

---

#### Occasion is a soft filter — always

"Beach wedding", "date night", "office casual" are not structured database fields. No product has `occasion = "beach wedding"` anywhere. The constraint extractor folds `occasion` into `rewritten_query` for semantic enrichment:

- Input: `"beach wedding, not too formal, under $40"`
- Output: `rewritten_query: "lightweight floral dress beach wedding smart casual outdoor"`, `max_price: 40.0`

`occasion` is returned in the response for agent transparency ("I filtered for beach wedding occasion") but it drives vector search — not a Qdrant metadata filter.

`AttrDef(key="occasion", is_qdrant_filter=False)` — this is the correct config.

---

#### Price currency handling — LLM detects, app converts

The LLM extracts the number the user typed and the currency it detected. The app does the conversion. Never ask the LLM to do currency math.

```python
# LLM outputs:
{ "price_value": 3000, "price_currency": "INR" }

# App converts using config.price_currency:
_CONVERSION_RATES = {"INR": 1/83, "USD": 1.0, "EUR": 1.08}
price_usd = price_value * _CONVERSION_RATES[detected_currency]
```

This supports users typing "₹3000" or "$40" naturally, regardless of what currency the catalogue stores prices in.

---

#### Build order

**1. `app/search/catalogue_config.py`**
No dependencies. Everything else imports from here. Get the dataclasses right before any other file is written.

**2. `workers/etl/attribute_indexer.py`**
Post-ETL script. Reads the catalogue and writes Redis sets per attribute per domain:

```
attrs:fashion:colour   → {"Black", "Blue", "White", "Pink", ...}
attrs:fashion:pattern  → {"Solid", "Floral", "Striped", ...}
attrs:electronics:brand → {"Apple", "Dell", "Lenovo", ...}
```

The constraint extractor loads these at request time to inject live catalogue values into the LLM prompt — preventing hallucinated filter values that don't exist in stock.

**3. `app/search/constraint_extractor.py`** — generic, config-driven

- Reads `AttrDef` list from `CatalogueConfig`
- Loads live attribute values from Redis via `redis_values_key`
- Builds LLM prompt dynamically: *"Available filters: colour (one of: Black, Blue, White...), pattern (one of: Solid, Floral...)"*
- LLM (Bedrock Haiku) extracts constraints and detects price currency
- App converts price to `config.price_currency`
- Returns: `rewritten_query`, `max_price`, `min_price`, and one key per `AttrDef` with `is_qdrant_filter=True`

**4. `app/search/query_router.py`** — inject config routing examples
The ShopSense prompt used electronics few-shot examples. Replace with `config.routing_examples` injected at call time. Fashion examples:

| Query                                | Route      |
| ------------------------------------ | ---------- |
| "something cute for brunch"          | SEMANTIC   |
| "show me floral"                     | SEMANTIC   |
| "what colours does H&M have?"        | ANALYTICAL |
| "which colour has most options?"     | ANALYTICAL |
| "well-reviewed blue dress under $30" | HYBRID     |
| "blue dress size M"                  | HYBRID     |

Run the 30-query golden test set (separate from routing_examples — these live in `tests/search/golden_queries_fashion.json`) until accuracy ≥ 85%.

**5. `app/search/nl_to_sql.py`** — inject `config.schema_hint`
Replace the hardcoded electronics schema block with `config.schema_hint`. Fashion schema hint:

```sql
-- products table (fashion domain)
id, name, brand, category,
current_price FLOAT,        -- USD
stock_count INT, avg_rating FLOAT,
description TEXT,
attributes JSONB,           -- keys: colour, pattern, garment_group, section, department
                            -- query: attributes->>'colour', attributes->>'pattern'
style_sentiment, quality_sentiment, fit_sentiment,
comfort_sentiment, versatility_sentiment, delivery_sentiment,
external_product_id VARCHAR  -- non-null = H&M product
-- Price is stored in USD. Users may ask in ₹ — convert: ₹3000 = $36.14
```

**6. `app/search/router.py`** — accept `catalogue` param

```
POST /search
{
  "query": "floral summer dress",
  "catalogue": "fashion",      # required, raises 400 if unknown
  "filters": { ... },          # optional, pre-extracted by agent
  "top_k": 20
}
```

Load `CatalogueConfig`, pass through the entire pipeline. `catalogue` defaults to `"fashion"` during the current build phase — can become required once multi-catalogue is live.

**7. Update `app/search/qdrant_ops._scored_point_to_result`**
Add `sentiment_fields: list[str]` parameter fed from `config.sentiment_fields`. Remove the hardcoded `_FASHION_SENTIMENT_KEYS` tuple — this is the only other place that has domain-specific knowledge baked in.

**8. `tests/search/test_constraint_extractor.py`**
20 queries split across both domains — same extractor, correct output for both:

- Fashion: "beach wedding, not too formal, under $40" → `{max_price: 40.0, rewritten_query: "..."}`
- Electronics: "gaming laptop 32GB RAM under $1200" → `{max_price: 1200.0, ram: "32GB"}`

Mark with `@pytest.mark.integration` — these hit Bedrock and should not run in CI without the flag.

---

**Demo at end of Day 20:**

- Query router classifies fashion queries at ≥ 85% on the 30-query golden set
- `"show me something floral"` → SEMANTIC, `"what colours does H&M have in stock?"` → ANALYTICAL, `"well-reviewed blue dress under $30"` → HYBRID
- Constraint extractor parses `"beach wedding, not too formal, under $40"` → `{rewritten_query: "lightweight dress beach wedding smart casual", max_price: 40.0}`
- Same extractor parses `"32GB RAM gaming laptop under $1200"` → `{rewritten_query: "gaming laptop high performance", max_price: 1200.0, ram: "32GB"}` — no code change, different config
- `POST /search` with `catalogue: "fashion"` returns H&M results; with `catalogue: "electronics"` returns laptops

---

### Day 21 — LangGraph Supervisor + Product Discovery Agent (Fashion)

Adapt the LangGraph agent from electronics to the fashion domain.

Update `app/agent/state.py` — add fashion-specific state fields: `visual_attributes` (extracted from image upload), `occasion_context` (inferred from conversation), `style_preference` (inferred from session behaviour). Remove electronics-specific fields.

Update `app/agent/prompts.py` — rewrite all prompts for fashion context. The supervisor prompt's intent examples should use fashion queries. The FILTER_EXTRACTION_PROMPT should reference fashion attributes. The SYNTHESIS_PROMPT should give fashion-specific response guidelines: "When recommending clothing, always mention the occasion it suits best and one standout feature that justifies the recommendation."

Update `app/agent/nodes/supervisor.py` intent classifier. Add `VISUAL` intent (image upload) to the routing table — the ShopSense supervisor did not have this. Update disambiguation rules: "show me something like this" with an image attached → VISUAL, not DISCOVERY. "what do you have in blue?" → DISCOVERY (not ANALYTICAL).

Update `app/agent/nodes/product_discovery.py` to use the fashion constraint extractor and to pass fashion-specific filters to the search module. Add a "wardrobe context" awareness: if the user mentioned an outfit already in the conversation, the discovery agent should look for complementary pieces.

Update `app/agent/nodes/personalise.py` — fashion personalisation boosts differ from electronics. Boost products that match `preferred_colours` and `preferred_occasions` from `user_preferences`. Add sentiment boost: if user_preferences has high `comfort_priority`, boost products with `comfort_sentiment >= 4.0`.

Re-run the intent classifier quality gate (20 fashion queries, ≥90% accuracy). Re-run the search integration tests with fashion data.

**Demo at end of Day 21:** Full conversation: "I need something for a rooftop birthday party this weekend, budget ₹4000" → supervisor classifies DISCOVERY → constraint extractor parses occasion and budget → product discovery agent returns 3 relevant options → synthesis generates a personalised recommendation narrative streaming token by token. Open LangSmith, see the complete trace.

---

### Day 22 — Visual Search Agent (CLIP + Separate Docker Service)

> **Architecture decision (2026-06-01):** Original plan used Bedrock Sonnet vision for attribute extraction. Replaced with local CLIP zero-shot classification to eliminate per-image Bedrock cost entirely (~$0.005–0.015/call saved) and reduce latency from ~1000ms to ~55ms. Decision driven by demo AWS credit constraints ($100 remaining) and the realisation that CLIP zero-shot over Redis attribute sets is more accurate than free-form LLM extraction (LLM can hallucinate colours not in the catalogue; CLIP always picks from the real Redis values). If results are unsatisfactory after the demo, swap back to Bedrock vision — the interface is identical.

#### Why CLIP, not direct embedding comparison

CLIP (Contrastive Language-Image Pretraining) learns a shared vector space for images and text. However, the `hm_products` Qdrant collection was embedded with **Jina v3 text embeddings** — a completely different vector space. A CLIP image vector compared directly against a Jina text vector is meaningless (different models, different dimensions, unaligned spaces).

Instead we use CLIP for **zero-shot classification**:
1. CLIP image-encodes the uploaded photo → image vector (512-dim, internal)
2. CLIP text-encodes every attribute value from Redis (colours, patterns, categories) → text vectors — **pre-cached at service startup**
3. cosine_similarity(image_vec, each_text_vec) → pick the highest-scoring label per attribute
4. Output: `{colour: "Black", pattern: "Solid", category: "Dresses"}` — guaranteed to be real catalogue values
5. Build `rewritten_query` from those attributes → Jina text embed → Qdrant search (normal path)

CLIP handles image→attributes. Jina handles attributes→Qdrant. They never compare vectors with each other.

#### Deployment architecture: separate Docker container, same EC2

**Do not** add CLIP/PyTorch to the main FastAPI container. PyTorch alone is ~2GB in a Docker image and would bloat the main app image and increase EC2 memory pressure.

```
EC2 t3.large (8GB RAM)
└── docker-compose
    ├── app           (FastAPI, ~1.5GB RAM, lean image, no torch)
    ├── clip-service  (FastAPI :8001, ~800MB RAM, owns torch + open-clip-torch)
    ├── redis         (~200MB)
    └── postgres / Supabase
```

The main app calls `http://clip-service:8001/classify` over Docker's internal network (~1ms overhead). If the CLIP service is down, `visual_search` node returns the graceful stub — rest of the app is unaffected.

**EC2 sizing:** t3.medium (4GB) is tight with CLIP added. Move to **t3.large (8GB, ~$60/mo)** when deploying Day 22.

#### Build order

**Step 1 — `Dockerfile.clip`**
```dockerfile
FROM python:3.11-slim
RUN pip install open-clip-torch fastapi uvicorn redis aioredis
# open-clip-torch is lighter than full transformers+torch (~1.2GB vs ~2.5GB)
COPY workers/clip_service.py .
CMD ["uvicorn", "clip_service:app", "--host", "0.0.0.0", "--port", "8001"]
```

**Step 2 — `workers/clip_service.py`** (standalone FastAPI service)
- On startup: load `ViT-B/32`, read Redis attribute sets, CLIP-encode all values, cache in memory
- `POST /classify` accepts `{"image_b64": "..."}`, returns `{"colour": "Black", "pattern": "Solid", "category": "Dresses", "scores": {...}}`
- Confidence threshold: if top score < 0.20, set attribute to `null` (don't force a bad filter)
- `/health` endpoint for docker-compose healthcheck

**Step 3 — `docker-compose.yml`** — add `clip-service` block with `depends_on: [redis]`

**Step 4 — `app/agent/nodes/visual_search.py`** (replace current stub)
- Read `state.visual_attributes["image_b64"]`
- POST to `http://clip-service:8001/classify`
- Build `rewritten_query` from non-null attributes
- Call `extract_constraints()` with the rewritten query + config to get hard filters
- Proceed to normal semantic search path (reuse `semantic_search` logic)

**Step 5 — `app/agent/router.py`** — update `POST /chat` to accept `multipart/form-data` with optional image; base64-encode and store in `state.visual_attributes`

**Step 6 — `app/agent/nodes/supervisor.py`** — detect `state.visual_attributes` non-empty → override intent to VISUAL regardless of message text ("find something like this", vague references)

**Step 7 — synthesis prompt** — for VISUAL query_type, mention which visual attributes were detected ("Found items matching your uploaded image: Black, Solid, Dresses")

#### Latency breakdown (CPU, t3.large)

| Step | Time |
|------|------|
| CLIP image encode (one forward pass) | ~50ms |
| cosine similarity over cached text vecs | ~5ms |
| HTTP to clip-service (internal Docker) | ~1ms |
| Jina text embed (existing path) | ~80ms |
| Qdrant search | ~30ms |
| **Total visual search** | **~170ms** |

Compare to original Bedrock Sonnet vision path: ~1000–1500ms. CLIP is ~8x faster.

#### Cost

- CLIP inference: **$0** (local)
- Per visual search request: **$0 Bedrock spend**
- EC2 cost increase: ~$30/mo (t3.medium → t3.large)

#### Synthesis model — switch to Haiku across all paths

Simultaneously with Day 22: update `CatalogueConfig.synthesis_model_tier` (new field, default `"fast"`) so synthesis uses **Haiku** instead of Sonnet. Sonnet is ~5x more expensive per token. For fashion recommendations the quality difference is acceptable for a demo. Can be toggled back to Sonnet per-catalogue when budget allows.

```python
# catalogue_config.py
synthesis_model_tier: str = "fast"   # "fast" = Haiku, "generation" = Sonnet
```

Pass to `synthesise.py` → `call_llm(prompt, tier=config.synthesis_model_tier, ...)`.

**Demo at end of Day 22:** Upload an H&M product photo via the chat interface. `visual_search` node calls the CLIP service, extracts colour/pattern/category, returns visually similar products from Qdrant. LangSmith trace shows the CLIP attributes and the downstream Jina embed + Qdrant call. At least 3 of the top 5 results match the dominant colour and garment type of the uploaded image. Zero Bedrock spend for the visual path.

---

### Day 23 — Comparison Agent + Policy RAG Agent

Complete the two remaining sub-agents.

**Comparison Agent** — finalise `app/agent/nodes/comparison.py`. The stub from Day 9 handled the fetch — today add the full comparison logic. Fetch complete product records for 2–3 products from PostgreSQL (fresh prices, stock). Build a structured comparison table across all shared attributes (colour, garment type, price, sentiment scores). Write the comparison synthesis prompt: gives Bedrock Sonnet the comparison table and the user's stated use case, instructs it to lead with a direct recommendation ("For a beach wedding, the floral midi dress is the better choice because...") then explain the trade-offs.

**Policy RAG Agent** — finalise `app/policies/ingest.py` and `app/policies/retriever.py`.

`ingest.py`: loads policy PDF with PyMuPDF or plain text file. Splits with `RecursiveCharacterTextSplitter` (chunk_size=512, overlap=50). Embeds each chunk with Jina v3 `retrieval.passage`. Upserts to `policies` Qdrant collection with payload `{chunk_text, source_file, page_number, chunk_index}`. Exposes `POST /policies/upload` (admin only, multipart file upload).

`retriever.py`: embeds the query with `retrieval.query`, searches top-3 policy chunks from Qdrant, returns them with their source file and page number.

Finalise `app/agent/nodes/policy_rag.py`. Calls retriever, injects top-3 chunks into Bedrock Sonnet context with strict grounding prompt: "Answer based only on the provided policy text. If the policy does not address this question, say explicitly that you cannot find this information in the policy." Cite the source file and page number in the response.

Write a sample return policy document for the demo (return_policy.txt — 2 pages of realistic UK/India e-commerce return policy text). Upload it via the admin API. Ask 5 questions about it and verify all answers are grounded.

**Demo at end of Day 23:** Ask "compare the H&M floral dress and the H&M wrap dress for a summer wedding" — comparison agent returns a direct recommendation with a trade-off narrative. Ask "can I return a sale item?" — policy RAG agent returns a grounded answer citing the specific policy clause, not a hallucinated generic response.

---

### Day 24 — MCP Server Adaptation + Purchase Agent Polish

Adapt the MCP server from the ShopSense electronics checkout to the fashion context.

Update MCP tool schemas for fashion. `check_stock_status` now returns size availability (which sizes are in stock, not just binary in/out-of-stock). `get_delivery_estimate` works the same. Add new tool: `check_size_availability(product_id, size)` — returns available sizes and their stock counts from the `variants` JSONB field.

Update `app/agent/nodes/purchase_agent.py`. The ShopSense version handled electronics — one product, one unit. Fashion checkout often involves: multiple sizes available, colour variants, outfit bundles (buy the dress + the matching shoes). Handle the size selection sub-flow: if a user says "add the floral dress to my cart", the agent must ask "what size?" before proceeding if size information is not in state. This is an additional `interrupt()` gate in the confirmation flow.

Add the outfit bundling cross-sell: after `add_to_cart` succeeds, call `get_frequently_bought_together` — for fashion this returns items that are commonly bought as part of the same outfit. Present as "Complete the look:" with 1–2 complementary items.

Write end-to-end checkout flow test: search for a dress, select it, get prompted for size, select size, add to cart, see cross-sell with matching shoes, decline, see cart summary, confirm payment, verify order created and email sent.

**Demo at end of Day 24:** Full fashion checkout flow through natural conversation. "Add the floral midi dress to my cart" → agent asks for size → "medium please" → confirm → add to cart → cross-sell "Complete the look: these sandals are frequently bought with this dress" → decline → checkout → payment confirmed → email received.

---

### Catalogue Ingestion & Stock Management Architecture

> Resolved during Day 20 — documented here as the foundation for Day 25's multi-tenant health dashboard and the Catalogue Gap Agent.

---

#### Why this matters

The Day 20 config-driven search layer assumes attribute values in Redis are always fresh and stock flags in Qdrant are always accurate. Neither is true without an automated pipeline. Every new catalogue, every inventory update, and every new client onboarding depends on the same four-step chain running reliably in the right order.

---

#### The four-step ingestion chain

Each product row moves through stages. The existing `embedding_status` column (`pending → embedded`) is the pattern — extend it to cover the full pipeline:

```
raw → normalised → sentiment_scored → embedded → indexed
```

A coordinator script (or simple cron) queries "what stage am I at?" for each catalogue and fires the next worker. New catalogue arrives → drop CSV → coordinator walks it through all four stages automatically.

| Stage               | Worker                                            | Output                                                                           |
| ------------------- | ------------------------------------------------- | -------------------------------------------------------------------------------- |
| 1. Normalise        | `workers/etl/pipeline.py`                       | Products written to `products` table with `embedding_status = 'pending'`     |
| 2. Score sentiment  | `workers/sentiment/fashion_sentiment_worker.py` | `sentiment_scored_at` set, 8 sentiment columns populated                       |
| 3. Embed            | `workers/embedding_worker.py`                   | Vectors upserted to Qdrant,`embedding_status = 'embedded'`                     |
| 4. Index attributes | `workers/etl/attribute_indexer.py`              | Redis sets refreshed — constraint extractor picks up new values on next request |

The attribute indexer must run **last** and must be triggered automatically at the end of the embedding run. Right now it is manual. The embedding worker already marks rows `embedded` — the indexer should hook off that completion signal, either as a direct callback at the end of `run_worker()` or as a short-interval cron that fires when the embedding queue drains to zero.

#### Adding a new catalogue

Today, a new catalogue requires:

1. Adding one `CatalogueConfig` object to `app/search/catalogue_config.py` (30 lines)
2. Running the four-step chain above for that catalogue's data
3. Calling `ensure_catalogue_indexes(collection_name, keyword_fields)` for the new Qdrant collection — already handled at startup by `app/main.py`

The constraint extractor serves the new catalogue automatically after step 4 completes — no restart needed because it reads Redis at request time.

**Future (Day 25+):** `CatalogueConfig` moves from a hardcoded Python file to a DB table, and `get_catalogue()` does a DB lookup. New clients self-serve by inserting a config row. The coordinator reads from that table and knows which workers to run for which catalogues.

---

#### Out-of-stock handling — filter vs delete

Two approaches, one clearly better:

**Option A — Keep in Qdrant, filter at query time (correct default)**

- `stock_available: bool` is already a top-level Qdrant payload field set by the embedding worker
- Out-of-stock products stay in the index; `stock_available: false` is a payload filter applied at search time
- When stock is restored: update the payload field only — no re-embedding, no re-indexing
- Cost of a stock change: one `set_payload` call to Qdrant

**Option B — Delete from Qdrant when out of stock (wrong default)**

- Every inventory fluctuation triggers a Qdrant delete + re-upsert cycle
- Ties embedding cost to stock frequency — expensive for fast-moving catalogues
- Loses the vector if the product comes back in stock; forces re-embedding

**Decision: Option A always.** The `in_stock_only: bool` field already exists in `SearchFilters`. When a user wants in-stock results, the constraint extractor sets it and the router applies `FieldCondition(key="stock_available", match=MatchValue(value=True))`. Products that go out of stock are never shown unless explicitly requested.

#### Redis attribute freshness

When a colour or pattern goes out of stock **entirely** (zero in-stock products in that value), it should stop appearing as a valid filter option in the constraint extractor prompt — otherwise users can select it and get zero results.

This is handled automatically by the attribute indexer: it queries the DB with whatever `WHERE` clause defines "active stock" for that catalogue, and only values that have at least one qualifying product end up in Redis. Re-running the indexer nightly (or after each ingestion run) keeps the attribute sets accurate without any extra logic.

The constraint extractor reads Redis at request time — no cache, no TTL. The moment the indexer writes a refreshed set, the next search request uses the new values.

---

### Day 25 — Recommender System (ALS + MLflow)

Build the collaborative filtering recommender using real H&M purchase data.

Write `workers/recommender_trainer.py`. Load the H&M transaction CSV (download from Kaggle `h-and-m-personalized-fashion-recommendations` — the `transactions_train.csv` contains 31M rows). Build the user-item interaction matrix from `user_item_interactions` table supplemented with H&M historical transactions. The matrix maps user_id to product_id via the interaction weight. Use `implicit.als.AlternatingLeastSquares` with factors=64, iterations=20, regularization=0.1.

Train/test split: hold out the last 30 days of transactions as the test set. Evaluate precision@10, recall@10, NDCG@10 on the held-out set. Log everything to MLflow: hyperparameters, dataset stats (n_users, n_items, n_interactions, sparsity), metrics, training duration, model artifact. Register the model in MLflow registry as `Staging`.

Run 5 training experiments with different hyperparameter combinations: factors=[32, 64, 128], regularization=[0.01, 0.1]. The training history comparison is your MLflow story — this is explicitly what interviewers want to see.

Finalise `app/recommendations/als_model.py`. Loads the `Production` model from MLflow registry at FastAPI startup, caches in memory. Exposes `get_recommendations(user_id, n=10)` — returns product IDs sorted by ALS score. Handles cold-start by returning an empty list (fallback to content-based in the blending layer).

Promote the best experiment from Staging to Production in MLflow registry. Verify `GET /recommendations/{user_id}` returns a ranked list of H&M products with different results for a user with purchase history vs a new user.

**Demo at end of Day 25:** MLflow UI shows 5 training runs with metrics comparison. The best run is marked Production. `GET /recommendations/user_123` returns 10 personalised product IDs. The same endpoint for a new user (no history) falls back to content-based — still returns 10 results, just not personalised. Admin dashboard Recommender Panel shows current precision@10.

---

### Day 26 — Scheduled Agents (All Four)

Build all four agents that run on schedules.

**Trend Intelligence Agent** (`workers/scheduled_agents/trend_intelligence.py`). Reads `search_queries` table for the past 7 days, filters to queries with `result_count = 0`. Generates Jina embeddings for all zero-result queries. Clusters them using K-means (scikit-learn, k=10) in embedding space. For each cluster, uses Bedrock Haiku to generate a label (e.g. "sustainable activewear", "vintage denim", "petite formal wear"). Writes cluster summaries to `admin_notifications` table. Runs nightly via APScheduler.

**Restock Prediction Agent** (`workers/scheduled_agents/restock_prediction.py`). Reads `orders` table for the past 30 days, calculates daily purchase velocity per product. Applies a 7-day moving average. Products with less than 7 days of stock remaining at current velocity generate notifications. Bedrock Haiku writes the notification text with specific numbers: "The H&M Floral Midi Dress (article 123456) has sold an average of 12 units/day this week. At current stock of 45 units, it will run out in 3–4 days." Runs daily.

**Post-Purchase Feedback Agent** (`workers/scheduled_agents/post_purchase.py`). Queries orders where `status = 'delivered'` and `delivery_confirmed_at < NOW() - INTERVAL '3 days'` and no review exists for that product from that user. Creates a pending review notification in Redis (`pending_review:{user_id}`) so the synthesise node can prepend a review nudge on the next chat session. Runs every 6 hours.

**Catalogue Gap Agent** (`workers/scheduled_agents/catalogue_gap.py`). Reads trend clusters from the notifications table (last 7 days). Cross-references each cluster label against the current catalogue using Qdrant similarity search. Generates a gap report: "Cluster 'sustainable activewear' has 47 searches this week — your catalogue has 2 matching products, both out of stock." Writes to `admin_notifications`. Runs weekly.

Add all four to `workers/run_scheduled_agents.py` using APScheduler. Run the trend intelligence agent manually. Verify the output in the admin notifications table.

**Demo at end of Day 26:** Run trend intelligence manually. It clusters zero-result searches from the test data. Open the admin portal notifications panel and see the cluster report. Manually insert a product with `stock_count = 2` and simulate high purchase velocity — the restock agent generates an alert.

---

### Day 27 — Admin Dashboard API + Search Intelligence Endpoints

Write all remaining admin API endpoints that the frontend needs.

Write `GET /analytics/overview`. Returns today's conversation count, unique users, conversation-to-cart rate, cart-to-purchase rate, average conversation length, top 5 search queries. All from the `search_queries` and `orders` tables via efficient SQL aggregations.

Write `GET /analytics/agent-metrics`. Returns grounding rate (percentage of synthesise node outputs where `sources` is non-empty), clarification rate (percentage of supervisor classifications that were `CLARIFY`), sub-agent distribution (group by `sub_agent_invoked` from a new `agent_traces` table), average retrieval confidence per query type.

Write `GET /analytics/search-intelligence`. Calls the trend intelligence logic inline (not waiting for the nightly scheduled run). Returns zero-result query clusters with counts, low-engagement queries, top performing queries, week-over-week volume changes per category.

Write `GET /tenants/catalog/status`. Returns total products, products with embeddings, products with sentiment scores, products out of stock, products with zero sales this month, last ingestion timestamp and status.

Write `GET /tenants/notifications`. Returns all unread admin notifications with type, title, body, created_at. Supports `?is_read=false` filter. Supports `DELETE /tenants/notifications/{id}` to dismiss.

Write tests for all 5 endpoints. Verify they return the expected shape and handle empty databases gracefully.

**Demo at end of Day 27:** `GET /analytics/overview` returns meaningful stats. `GET /analytics/search-intelligence` returns zero-result clusters from the test search data. All endpoints return in under 500ms.

---

### Day 28 — Customer Storefront Frontend (Fashion)

Build the customer-facing browsing experience adapted for the H&M fashion catalogue.

Write `frontend/storefront/src/components/ProductGrid.tsx`. Fetches from `GET /api/products`. Renders cards with real H&M product images (from `image_url`), product name, brand, price with a coloured indicator if it differs from base price by >2%. Responsive CSS grid. On hover: show the top two sentiment scores as small coloured pills ("Style 4.8", "Comfort 4.3"). Skeleton loading state with animated placeholders.

Write `frontend/storefront/src/components/SearchBar.tsx`. Text input on the left. On the right: a small image icon that opens a file picker for visual search. On text submit: calls `POST /api/search`. On image upload: includes the image in the multipart request to `POST /chat` with an initial message "Find something similar to this".

Write `frontend/storefront/src/components/ProductDetail.tsx`. Hero image at the top. Price with dynamic indicator. Size selector (reads available sizes from `variants` JSONB). "Add to cart" button opens the chat widget in purchase mode. Below the fold: seven animated sentiment bars (ScrollReveal animation), `top_praise` in a green card, `top_complaint` in an amber card. Recommendation row: "Complete the look" (frequently bought together), "You might also like" (content-based Qdrant KNN). Each recommendation card has image, name, price.

Write `frontend/storefront/src/components/SmartBasketChat.tsx`. Floating button bottom-right (chat bubble icon). On click: slides in a full-height side panel from the right. Text input at the bottom with: send button, image upload button (for visual search), microphone placeholder. Streaming response with typing indicator. Query type badge (SEMANTIC/HYBRID/VISUAL) shown after each response. Confirmation buttons (Confirm / Cancel) shown when agent sends an interrupt.

Configure Nginx proxy, deploy storefront to Vercel.

**Demo at end of Day 28:** Open the live Vercel URL. Browse real H&M products with real images. Search "floral summer dress" — semantic results. Upload a product photo — visual search returns similar items. Open a product detail page and see the sentiment bars animate in on scroll. Click "complete the look" recommendations.

---

### Day 29 — Admin Portal Frontend

Build the admin intelligence dashboard.

Write `frontend/admin/src/components/OverviewPanel.tsx`. Fetches from `GET /analytics/overview`. Stat cards with week-over-week arrows: conversation count, unique users, conversion rate, average session length. Simple sparkline charts using Recharts.

Write `frontend/admin/src/components/SearchIntelligence.tsx`. The most important panel. Fetches from `GET /analytics/search-intelligence`. Zero-result clusters displayed as cards: cluster label (e.g. "sustainable activewear"), search count, first-seen date, sample queries (expandable). "Export CSV" button. Low-engagement queries in a separate tab. Top performing queries in a third tab.

Write `frontend/admin/src/components/NLQueryInterface.tsx`. Full-screen split panel. Left: text input with 6 clickable example chips. Right: syntax-highlighted SQL block, results as a formatted table, one-sentence LLM insight. Connects to `POST /analytics/query`. The SQL block uses PrismJS for syntax highlighting.

Write `frontend/admin/src/components/CatalogueHealth.tsx`. Status grid: total products (with count), embeddings coverage (progress bar), sentiment coverage (progress bar), products out of stock (count with alert if >10%), products with zero sales (count). Last ingestion timestamp with status dot (green = success, red = failed).

Write `frontend/admin/src/components/RecommenderPanel.tsx`. Fetches from MLflow API proxy (`GET /analytics/mlflow/summary`). Current model precision@10, recall@10. Training run history as a line chart (Recharts). Last retrain date, next scheduled retrain. Cold-start percentage. Recommendation CTR.

Write `frontend/admin/src/components/NotificationsPanel.tsx`. Fetches from `GET /tenants/notifications`. Notification cards with type icon (inventory, trend, feedback, system), title, body, timestamp. Dismiss button per notification. Badge count in sidebar nav.

Deploy admin portal to Vercel on a separate Vercel project.

**Demo at end of Day 29:** Admin logs in via the portal. Dashboard shows all 7 panels populated with real data. Types "which H&M products have zero sales this month?" into the NL query interface, sees SQL generated and results returned in under 2 seconds. Zero-result cluster panel shows fashion trend gaps. Recommender panel shows MLflow training history.

---

### Day 30 — Constraint Extractor Refinement + Fashion-Specific Search Quality

Polish the search layer with fashion-specific improvements gathered from testing Days 19–29.

Update `app/search/constraint_extractor.py` with occasion-aware extraction. Fashion queries often embed occasion implicitly: "beach wedding" → occasion=wedding AND setting=outdoor AND formality=semi-formal. Build an occasion taxonomy: formal (gala, black-tie, wedding), semi-formal (cocktail, rooftop party, date night), business (office, work from home, presentation), casual (brunch, shopping, errands), active (gym, yoga, running), beach (holiday, pool, resort). Map colloquial occasions to this taxonomy in the prompt.

Implement filter carry-forward in the agent for fashion. When a user says "show me similar but in red", the constraint extractor should carry forward `garment_type` and `occasion` from the previous turn while replacing `colour`. This is the multi-turn search refinement pattern — critical for fashion where "similar but in red" is a common refinement.

Update `app/search/hybrid_search.py` for fashion JSONB queries. The H&M `attributes` JSONB contains nested colour groups, pattern types, garment groups. Test and fix any JSONB path issues in the SQL generation: `attributes->>'colour_group_name'`, `(attributes->>'price_range')::FLOAT`.

Write 10 multi-turn search conversation tests: start with a broad query, refine with colour, then occasion, then price — verify the constraint carry-forward works correctly at each step.

**Demo at end of Day 30:** Multi-turn fashion search works correctly. "Show me party dresses" → 5 results. "In red" → same occasion/type, only red ones. "Under ₹2500" → filtered to price. "With free delivery" → filtered to eligible products. The chat maintains shopping intent context across turns without losing prior constraints.

---

### Day 31 — Recommender Integration + Personalisation Deep Dive

Wire the recommender system end-to-end into the agent and test personalisation quality.

Finalise `app/agent/nodes/personalise.py`. Current state from ShopSense applies brand and sentiment boosts. Extend for fashion: apply `preferred_colours` boost (if user has ordered 3+ blue items in the past, blue products get +0.10 relevance boost), `preferred_occasions` boost (if user frequently buys workwear, work-appropriate products boosted), `size_preference` filter (if user always buys M, deprioritise products with no M in stock). All boosts are additive and capped at +0.25 total to avoid overriding relevance.

Update `app/agent/nodes/product_discovery.py` to blend ALS scores. After semantic search returns `search_results`, query `GET /recommendations/{user_id}` for the ALS-ranked list. For products that appear in both lists, add the ALS score to the relevance score with the configured weight (default: 40% ALS, 60% semantic). Re-sort by blended score. Pass to `personalise.py` for additional preference boosts.

Write the recommendation quality test: register two test users. Give User A a history of buying formal occasion dresses in size S. Give User B a history of buying casual streetwear in size L. Verify that `GET /recommendations/user_a` and `GET /recommendations/user_b` return substantially different product lists with the expected style profiles.

**Demo at end of Day 31:** "Show me something for a special occasion" — for User A (formal dress history), the response surfaces cocktail dresses and formal gowns. For User B (streetwear history), the same query surfaces stylish casual options. The personalisation is visible and explainable: agent response includes a line like "Based on your previous purchases, you tend to prefer..."

---

### Day 32 — Integration Tests + Golden Test Sets (Full Suite)

Consolidate all golden tests and run the full integration suite.

**Search layer:** Run the 30-query router golden test set (fashion-domain, must pass ≥85%). Run the 20-query NL-to-SQL golden test set (fashion schema, must pass ≥85%). If any tests fail, fix the prompt, not the test.

**Agent layer:** Write the intent classifier quality gate (20 fashion queries, ≥90% accuracy). Cover all 8 intent types with 2-3 queries each. Include edge cases: "I'll take it" (PURCHASE_INTENT), "how do I return my order" (POST_PURCHASE), "does this come in blue?" (DISCOVERY, not ANALYTICS). Write the confirmation classifier test (10 confirm/decline/ambiguous responses).

**Tool calling:** Write the checkout flow integration test end-to-end (mock Stripe and SendGrid, real graph execution). Verify the CONFIRM/DECLINE/AMBIGUOUS gate works correctly. Verify that "add the red one" after a visual search result routes correctly to the right product.

**RAG quality:** Write the policy RAG grounding test — 5 questions about the return policy, verify every answer is traceable to a specific policy chunk (check `sources` in state). Verify that "what is your refund policy on electronics?" returns a graceful "I cannot find this in the policy" response (we only have fashion return policy).

Run `make test` with full coverage. Target ≥80% coverage across all modules. Fix any failures before Day 33.

**Demo at end of Day 32:** `make test` runs in under 5 minutes. All golden tests pass at their thresholds. Coverage report shows ≥80%. No flaky tests.

---

### Day 33 — Observability Stack

Set up Prometheus and Grafana to complete the production observability picture.

Add `prometheus-fastapi-instrumentator` to the app. In `app/main.py` lifespan, call `Instrumentator().instrument(app).expose(app)`. This exposes `/metrics` at the FastAPI process level. Verify locally: `curl localhost:8000/metrics` returns Prometheus format metrics including `http_requests_total`, `http_request_duration_seconds`, `http_requests_in_progress`.

Add a Prometheus container to `docker-compose.yml`. Write `infra/prometheus.yml` scrape config targeting `fastapi:8000/metrics`, `kafka:9101/metrics` (JMX exporter), `redis:9121/metrics` (redis_exporter). Verify Prometheus graph UI at `localhost:9090` shows scraped targets as UP.

Add Grafana container to `docker-compose.yml`. Configure it to use Prometheus as a data source. Import or build four dashboards:

**Dashboard 1 — API Health:** `http_requests_total` by endpoint and status code. `http_request_duration_seconds` histogram (P50/P95/P99 per endpoint). Error rate panel (5xx / total). Active connections.

**Dashboard 2 — Kafka Pipeline:** Consumer lag per topic (from Kafka JMX exporter). Messages produced per minute per topic. Pricing engine cycle time (custom gauge metric added to `pricing_engine.py`).

**Dashboard 3 — AI Layer:** LLM call count per model (add custom counter in `app/llm.py`). LLM call latency histogram. Embedding request rate and latency. Qdrant search latency.

**Dashboard 4 — Business Metrics:** Conversations started per hour. Checkout flow completion rate (ratio of payment confirmations to add-to-cart events). Recommendation click-through rate.

Configure three Prometheus alerting rules in `infra/alerts.yml`: error rate above 1% for 5 minutes, P95 latency above 2 seconds for 5 minutes, Kafka consumer lag above 1000 messages for 10 minutes.

**Demo at end of Day 33:** Grafana at localhost:3000 shows all four dashboards populated with real metrics. Trigger a few searches and chats — watch the request rate and latency metrics update in near real-time. Prometheus Alertmanager configured (even if not sending emails yet).

---

### Day 34 — Terraform + Production Deployment

Deploy to EC2 and verify the full production stack.

Finalise all Terraform files (`terraform/main.tf`, `variables.tf`, `security_groups.tf`, `backend.tf`, `outputs.tf`). The EC2 `user_data` script: installs Docker and Docker Compose, clones the repository, copies `.env` (manually placed on the instance via SSM Parameter Store), runs `docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d` for Kafka, Redis, Qdrant, Prometheus, Grafana, starts the FastAPI app as a systemd service (`/etc/systemd/system/smartbasket.service`), starts the embedding and personalisation workers as systemd services.

Run `terraform init`, `terraform plan`, review the full plan output — specifically security groups (22 must only be open to your IP, never 0.0.0.0/0). Run `terraform apply`. SSH to the new instance using the `ssh_command` output.

On the EC2 instance: verify all containers are running (`docker ps`). Check FastAPI health endpoint: `curl localhost:8000/health`. Apply Supabase migrations against the production PostgreSQL. Run the H&M data ingestion pipeline against the production database (re-run; the local database data does not transfer automatically). Start embedding worker. Verify Qdrant collection is populated.

Update Vercel environment variables to point to the new EC2 Elastic IP for `VITE_API_URL`. Update Nginx config to whitelist the Vercel domain for CORS.

Verify end-to-end: open the Vercel storefront URL, perform a search, have a chat conversation, confirm the agent routes correctly and returns H&M products.

**Demo at end of Day 34:** `terraform output` shows the public IP. The live Vercel URL loads the storefront with real H&M products. The full chat flow works in production. Grafana is accessible via `http://{ec2_ip}:3000`. LangSmith traces appear from production conversations.

---

### Day 35 — Load Testing + Performance Tuning

Measure the system under realistic concurrent load and tune to meet targets.

Write `tests/load/k6_load_test.js`. Simulates 50 concurrent virtual users (VUs) over 10 minutes following this behaviour:

- 20% browse products (GET /api/products, GET /products/{id})
- 30% perform searches (POST /api/search with fashion queries)
- 30% have chat conversations (POST /api/chat, 3–5 turns each)
- 10% complete purchases (POST /api/chat with purchase intent → confirmation → payment)
- 10% admin analytics (POST /analytics/query)

Run the load test: `k6 run tests/load/k6_load_test.js`. Collect: P50/P95/P99 latency per endpoint, requests/second, error rate, Kafka consumer lag during load, EC2 memory usage.

Tuning based on results:

- If semantic search P95 > 1s: add Redis caching for frequent queries (already architected, just enable it)
- If NL-to-SQL P95 > 800ms: add query result caching by SQL hash
- If agent first-token > 2s: profile which node is slow (check LangSmith), likely Bedrock Haiku classification — consider caching supervisor classifications for identical messages
- If Kafka lag > 500ms under load: increase consumer group concurrency
- If memory usage > 70%: check for embedding worker memory leak, reduce embedding batch size

Document the results in `docs/load_test_results.md`: before-tuning and after-tuning numbers for each target metric.

**Demo at end of Day 35:** Load test results show all performance targets met: semantic search P95 < 1s, NL-to-SQL P95 < 800ms, agent first token < 2s, Kafka lag < 500ms, 0 errors during 50-user test. The before/after tuning comparison shows measurable improvement.

---

### Day 36 — Embeddable Widget + CI/CD Pipeline

Build the embeddable widget and automate deployment.

Write `frontend/widget/src/widget.tsx`. A minimal React component that renders the SmartBasket chat interface. Reads `data-position` and `data-theme` from the script tag's `dataset`. Renders as a floating button that expands to a chat panel. All chat functionality reused from `SmartBasketChat.tsx` via shared component library. Configure Vite to output a single `widget.js` file with no external dependencies (everything bundled).

Test the widget in isolation: create `frontend/widget/demo.html` — a minimal HTML page with a fake product and the widget script tag. Verify the widget loads, connects to the API, and a full search-to-purchase conversation works. This is the demo artefact for the portfolio.

Write `.github/workflows/deploy.yml`. On push to main:

1. `pytest tests/ --cov=app --cov-fail-under=80`
2. `pytest tests/search/test_query_router.py -v` (must pass ≥85%)
3. `pytest tests/search/test_nl_to_sql.py -v` (must pass ≥85%)
4. `pytest tests/agent/test_classify_intent.py -v` (must pass ≥90%)
5. `docker build -t smartbasket:latest .` (verify image builds)
6. SSH to EC2 → `git pull && sudo systemctl restart smartbasket`
7. `curl https://{ec2_ip}/health` — must return 200
8. Notify on failure via GitHub email notification

Push a test commit. Watch the workflow run. Verify it deploys cleanly. Introduce a deliberate test failure, verify the workflow stops before deploying.

**Demo at end of Day 36:** Paste `<script src="widget.js">` into the demo.html. The widget appears, connects to the production API, and the full chat flow works. GitHub Actions runs on every push. A test failure blocks deployment. A successful run deploys in under 5 minutes.

---

### Day 37 — Final Polish + Demo Materials

Fix everything that came up during load testing and production verification. Write the comprehensive README and record the demo video.

**Fixes and polish:** Review LangSmith traces from the past week of testing. Fix any nodes with consistently high latency. Fix any hallucination patterns caught by the grounding rate metric. Ensure all error responses are graceful (no raw stack traces to the user). Verify the visual search agent handles unsupported file formats (PNG, JPEG only — reject PDF, return friendly error).

**README:** Architecture section with the three Mermaid diagrams (high-level, agent flow, ETL pipeline). Setup instructions (docker-compose, env config, make dev). Data pipeline instructions (make ingest → make embed). Load test results table. LangSmith trace screenshot. Grafana dashboard screenshot.

**Demo video script (5 minutes):**

- 00:00–00:30: Customer storefront — real H&M products with images, real prices with dynamic pricing indicators
- 00:30–01:00: Semantic search — "floral dress for a beach wedding" returns visually relevant results
- 01:00–01:30: Visual search — upload an H&M product screenshot, find similar items by appearance
- 01:30–02:15: Chat conversation — "I need an outfit for a summer rooftop party under ₹5000" → streaming personalised recommendation
- 02:15–02:45: Fashion checkout — "add to cart, size medium" → cross-sell "complete the look" → payment confirmation flow
- 02:45–03:15: Admin dashboard — zero-result query clusters, NL-to-SQL interface ("which categories had zero sales this week?")
- 03:15–03:45: Recommender panel — MLflow training history, precision@10 improvement across 5 runs
- 03:45–04:15: Kafka UI — show product.viewed events flowing in real time as you browse and purchase
- 04:15–05:00: Terraform + CI/CD — show the `.tf` files, explain one-command deploy, show GitHub Actions run

Upload the video (unlisted on YouTube). Add to portfolio website. Update resume with SmartBasket entry.

---

## 19. Success Criteria

### 19.1 Functional Checklist

| Feature          | Test                                        | Pass                                                |
| ---------------- | ------------------------------------------- | --------------------------------------------------- |
| Semantic search  | "floral dress for a beach wedding"          | Relevant results, no keyword match required         |
| Query router     | 30-query fashion golden set                 | ≥85% correctly classified                          |
| NL-to-SQL        | 20-query fashion golden set                 | ≥85% generate correct SQL                          |
| NL-to-SQL safety | Inject "DROP TABLE"                         | Blocked by validation                               |
| Visual search    | Upload product image                        | Returns visually similar products                   |
| Policy RAG       | Ask return policy question                  | Grounded answer cites policy document               |
| Comparison agent | "Compare dress A and dress B for a wedding" | Direct recommendation + trade-off narrative         |
| Agent streaming  | Any conversation                            | Tokens stream one by one                            |
| Checkout flow    | Full buy journey incl. size selection       | Order created, email sent                           |
| HITL gate        | Payment confirmation                        | Never charges without explicit "yes"                |
| Recommender      | `GET /recommendations/{user_id}`          | Different results for user with history vs new user |
| Kafka pipeline   | Browse product 50+ times                    | Price updates, event visible in Kafka UI            |
| Admin NL-to-SQL  | "Zero sales this month?"                    | Returns correct product list                        |
| Scheduled agents | Run trend intelligence                      | Writes cluster report to notifications table        |
| Terraform        | `terraform apply`                         | EC2 live, all services running                      |
| CI/CD            | Push to main                                | Tests pass, auto-deploys                            |
| Load test        | 50 concurrent users, 10 minutes             | All performance targets met, zero errors            |

### 19.2 Performance Targets

| Metric               | Target                 | Measurement          |
| -------------------- | ---------------------- | -------------------- |
| Semantic search P95  | <1 second              | k6 load test         |
| NL-to-SQL P95        | <800ms                 | LangSmith trace      |
| Query router         | <200ms                 | LangSmith trace      |
| Agent first token    | <2 seconds             | LangSmith trace      |
| Kafka event lag P95  | <500ms                 | Grafana consumer lag |
| Recommender response | <100ms (Redis cache)   | FastAPI metrics      |
| Concurrent users     | 50 without degradation | k6 load test         |

### 19.3 Recommender Quality Targets

| Metric              | Target | Measurement            |
| ------------------- | ------ | ---------------------- |
| precision@10        | ≥0.35 | MLflow eval            |
| recall@10           | ≥0.25 | MLflow eval            |
| Cold-start coverage | 100%   | Content-based fallback |
| Cache hit rate      | ≥70%  | Redis metrics          |

### 19.4 Search Quality Targets

| Metric                     | Target                                 | Measurement            |
| -------------------------- | -------------------------------------- | ---------------------- |
| Query router accuracy      | ≥85%                                  | 30-query golden set    |
| NL-to-SQL accuracy         | ≥85%                                  | 20-query golden set    |
| Intent classifier accuracy | ≥90%                                  | 20-intent golden set   |
| Visual search relevance    | ≥3/5 top results visually similar     | Manual spot-check      |
| Policy RAG grounding       | 100% answers traceable to policy chunk | Automated source check |

---

*SmartBasket v2.0 — AI-Native Product Discovery · Single-Tenant, Production-Grade*
*FastAPI · LangGraph · Kafka · Qdrant · Bedrock · Jina v3 · ALS Recommender · MLflow · Terraform*
*Days 1–17: Foundation complete (ShopSense). Days 18–37: SmartBasket-specific build.*
*Multi-tenancy: future phase, added when the product is proven.*
