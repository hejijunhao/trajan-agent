from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from app.config import settings

# Transaction pooled connection for app operations (via Supabase pooler on port 6543)
# Note: Transaction pooler doesn't support prepared statements, so we disable them
engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    connect_args={
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    },
)

# Direct connection for migrations and admin operations (port 5432)
# Supports prepared statements and DDL operations
direct_engine = create_async_engine(
    settings.database_url_direct,
    echo=False,
    future=True,
    pool_pre_ping=True,
)

async_session_maker = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields an async database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create all tables (for development only - use Alembic in production).

    Uses direct connection since DDL operations require it.
    """
    async with direct_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
