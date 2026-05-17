from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import dispose_engine
from app.orders.kafka_consumer import start_consumer, stop_consumer
from app.orders.kafka_producer import close_producer as close_orders_producer
from app.products.kafka import close_producer as close_products_producer
from app.redis_client import close_pool, ping


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # startup
    await start_consumer()
    yield
    # shutdown — cancel consumer first, then drain producers and pools
    await stop_consumer()
    await dispose_engine()
    await close_pool()
    await close_products_producer()
    await close_orders_producer()


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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],  # Vite dev server
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

    # Uncomment as each module is implemented:
    # from app.search.router import router as search_router
    # from app.agent.router import router as agent_router
    # from app.analytics.router import router as analytics_router
    # app.include_router(search_router, prefix="/api/search", tags=["search"])
    # app.include_router(agent_router, prefix="/api/chat", tags=["agent"])
    # app.include_router(analytics_router, prefix="/api/analytics", tags=["analytics"])

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
