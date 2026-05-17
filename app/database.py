from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# Schema is managed by Supabase CLI migrations in database/migrations/.
#   supabase db push        — apply pending migrations to remote
#   supabase db reset       — drop and recreate (dev only)
#   supabase migration new  — scaffold a new numbered migration file
# Alembic is available as a fallback (see pyproject.toml).
# Never call Base.metadata.create_all() in application code.

engine = create_async_engine(
    settings.active_database_url,
    echo=settings.is_development,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,  # recycle connections after 30 min to avoid stale TCP connections
    pool_pre_ping=True,  # verify liveness before handing a connection to a caller
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a session and rolls back on unhandled exceptions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Call during application shutdown to drain the connection pool cleanly."""
    await engine.dispose()
