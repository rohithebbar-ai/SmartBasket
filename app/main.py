from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

# Load .env into os.environ BEFORE any LangChain/LangSmith import reads it.
# pydantic-settings populates Settings fields but does NOT write to os.environ,
# so LangSmith's tracer (which reads LANGCHAIN_* from os.environ directly)
# would never see the keys without this explicit load.
from dotenv import load_dotenv
load_dotenv(override=False)  # override=False: shell env vars take precedence

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import dispose_engine
from app.orders.kafka_consumer import start_consumer as start_orders_consumer
from app.orders.kafka_consumer import stop_consumer as stop_orders_consumer
from app.search.kafka_consumer import start_consumer as start_search_consumer
from app.search.kafka_consumer import stop_consumer as stop_search_consumer
from app.search.pricing_engine import start_pricing_engine, stop_pricing_engine
from app.orders.kafka_producer import close_producer as close_orders_producer
from app.products.kafka import close_producer as close_products_producer
from app.mcp.client import mcp_client
from app.redis_client import close_pool, ping
from app.search.catalogue_config import ELECTRONICS_CATALOGUE, FASHION_CATALOGUE
from app.search.qdrant_ops import ensure_catalogue_indexes


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # startup — initialise LangGraph Redis checkpointer (creates indexes on first run)
    from app.agent.graph import checkpointer as _graph_checkpointer
    if hasattr(_graph_checkpointer, "asetup"):
        await _graph_checkpointer.asetup()

    # startup — ensure Qdrant payload indexes for all known catalogues
    for catalogue in (FASHION_CATALOGUE, ELECTRONICS_CATALOGUE):
        keyword_fields = [
            a.key for a in catalogue.filterable_attrs if a.is_qdrant_filter
        ]
        ensure_catalogue_indexes(catalogue.qdrant_collection, keyword_fields)

    await start_orders_consumer()
    await start_search_consumer()
    await start_pricing_engine()
    yield
    # shutdown — cancel consumers + engine first, then drain producers and pools
    await stop_orders_consumer()
    await stop_search_consumer()
    await stop_pricing_engine()
    await dispose_engine()
    await close_pool()
    await close_products_producer()
    await close_orders_producer()
    await mcp_client.close()


def create_app() -> FastAPI:
    """
    Application factory. Returns a fresh FastAPI instance.
    Uvicorn: uvicorn app.main:app  (module-level singleton below)
    Tests:   each test calls create_app() to get an isolated instance.
    """
    app = FastAPI(
        title="ShopSense",
        description="AI-native product discovery platform for consumer electronics",
        version="0.1.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    allowed_origins = ["http://localhost:5173"]
    if settings.frontend_url:
        allowed_origins.append(settings.frontend_url)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ───────────────────────────────────────────────────────────────
    from app.auth.router import router as auth_router
    from app.orders.router import router as orders_router
    from app.products.router import router as products_router
    from app.users.router import router as users_router

    app.include_router(auth_router, prefix="/auth", tags=["auth"])
    app.include_router(products_router, prefix="/api/products", tags=["products"])
    app.include_router(orders_router, prefix="/api/orders", tags=["orders"])
    app.include_router(users_router, prefix="/api/users", tags=["users"])

    from app.search.router import router as search_router
    app.include_router(search_router, prefix="/api/search", tags=["search"])

    from app.analytics.router import router as analytics_router
    app.include_router(analytics_router, prefix="/api/analytics", tags=["analytics"])

    from app.agent.router import router as agent_router
    app.include_router(agent_router, prefix="/api/chat", tags=["agent"])

    from app.mcp.server import router as mcp_router
    app.include_router(mcp_router, prefix="/mcp", tags=["mcp"])

    # ── System endpoints ──────────────────────────────────────────────────────

    @app.get("/health", tags=["meta"])
    async def health() -> dict:
        redis_ok = await ping()
        return {
            "status": "ok" if redis_ok else "degraded",
            "service": "shopsense",
            "env": settings.app_env.value,
            "redis": "ok" if redis_ok else "unreachable",
        }

    return app


# Module-level singleton for uvicorn without --factory.
# The test suite imports create_app() directly.
app = create_app()
