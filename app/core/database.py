from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from app.config import settings

# Transaction pooled connection for app operations (via Supabase pooler on port 6543)
# Note: Transaction pooler doesn't support prepared statements, so we disable them
#
# Pool sizing rationale:
# - Supabase free tier: 60 pooler connections
# - Supabase Pro: 200+ pooler connections
# - pool_size=10 base + max_overflow=20 = 30 max connections
# - Supports ~10 concurrent users with 3 requests each before waiting
engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    pool_size=10,  # Increased from 5 for better concurrency
    max_overflow=20,  # Increased from 10 (total max = 30 connections)
    pool_pre_ping=True,  # Detects stale connections before use
    pool_recycle=300,  # Recycle connections every 5 min (Supabase pooler compatibility)
    pool_timeout=30,  # Wait up to 30s for a connection from pool
    connect_args={
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "command_timeout": 60,  # Query timeout in seconds (prevents hung queries)
    },
)

# Direct connection for migrations, admin operations, and long-running tasks (port 5432)
# Supports prepared statements and DDL operations.
# Use this for operations that may exceed the transaction pooler's statement timeout (~15s).
direct_engine = create_async_engine(
    settings.database_url_direct,
    echo=False,
    future=True,
    pool_pre_ping=True,
    pool_size=3,  # Small pool - only used for long operations
    max_overflow=5,
    connect_args={
        "command_timeout": 300,  # 5 minute timeout for long operations
    },
)

async_session_maker = sessionmaker(  # type: ignore[call-overload]
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Session maker for direct connections (long-running operations)
direct_session_maker = sessionmaker(  # type: ignore[call-overload]
    direct_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields an async database session.

    Uses the transaction pooler connection (port 6543).
    Suitable for most API operations with typical query times.
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_direct_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields a direct database session (bypasses pooler).

    Use this for long-running operations that may exceed the transaction
    pooler's statement timeout (~15s), such as:
    - Documentation generation
    - AI analysis tasks
    - Bulk data operations
    - Complex aggregation queries

    Uses direct connection (port 5432) with 5-minute command timeout.
    """
    async with direct_session_maker() as session:
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
