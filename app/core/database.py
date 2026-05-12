from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
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

# Transaction pooled connection for cron + webhook bootstrap (port 6543,
# connects as BYPASSRLS role `trajan_cron`). Used only by:
#   - services/scheduler.py (cron job enumeration)
#   - api/v1/webhooks.py, api/v1/billing.py (webhook owner resolution)
#   - api/deps/api_key_auth.py, api/deps/org_api_key_auth.py (key validation)
#
# Intentionally NOT exposed as a FastAPI dependency (`get_cron_db()`): the
# injection surface is the audit boundary. A sessionmaker must be imported
# explicitly to be used, so `grep 'cron_session_maker('` across the repo
# catches accidental leakage into request handlers during code review.
#
# Pool sizing: cron runs 5 jobs on a schedule (most mutually exclusive via
# advisory locks) and API-key validation is sub-ms. pool_size=2 + overflow=3
# is ample; oversizing would steal from trajan_app's pooler budget.
cron_engine = create_async_engine(
    settings.database_url_cron,
    echo=False,
    future=True,
    pool_size=2,
    max_overflow=3,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_timeout=30,
    connect_args={
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "command_timeout": 60,
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

# Session maker for cron + webhook-bootstrap connections (BYPASSRLS).
# Never wire into a FastAPI Depends — see cron_engine docstring above.
cron_session_maker = sessionmaker(  # type: ignore[call-overload]
    cron_engine,
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


@asynccontextmanager
async def rls_scoped_session(user_id: UUID) -> AsyncIterator[AsyncSession]:
    """Open a fresh ``AsyncSession`` with RLS context bound to ``user_id``.

    Use this inside ``asyncio.gather`` fan-outs that perform DB work per
    task. SQLAlchemy ``AsyncSession`` is not safe for concurrent coroutines
    sharing one session — asyncpg refuses overlapping operations on a single
    connection (``cannot perform operation: another operation is in
    progress``). Each fanned-out task must own its session.

    The session is scoped to the ``async with`` block: it commits on clean
    exit, rolls back on exception, and is returned to the pool either way.
    The v0.31.3 ``after_begin`` listener re-arms ``SET LOCAL
    app.current_user_id`` across any mid-task ``commit()``, so RLS context
    survives the full task lifetime.

    Example:
        async def fetch_for_product(p):
            async with rls_scoped_session(user.id) as task_db:
                return await do_db_work(task_db, p)

        results = await asyncio.gather(*(fetch_for_product(p) for p in products))
    """
    # Late import to avoid circular dependency: rls -> database -> rls.
    from app.core.rls import set_rls_user_context

    async with async_session_maker() as session:
        try:
            await set_rls_user_context(session, user_id)
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


# ---------------------------------------------------------------------------
# RLS context auto-rehydration
#
# ``SET LOCAL app.current_user_id`` is bound to the current Postgres
# transaction. Any ``session.commit()`` ends that transaction and drops the
# setting — the next query on the session runs under NULL context. Under
# ``trajan_app`` + FORCE RLS, NULL context makes every user-scoped policy
# evaluate to false: SELECTs return zero rows, INSERTs raise WITH CHECK.
#
# The listener below attaches to the sync ``Session`` class (async sessions
# proxy through ``sync_session``) and fires at the start of every new
# transaction on any session. If the session has an ``rls_user_id`` on its
# ``info`` dict (populated by ``set_rls_user_context``), the listener
# re-issues ``SET LOCAL`` so the new transaction begins with the correct
# context. This makes the invariant mechanical — service authors no longer
# need to remember to re-call ``set_rls_user_context`` after every commit.
#
# Sessions that deliberately run BYPASSRLS (cron paths, tests) don't
# populate ``info["rls_user_id"]`` and the listener no-ops.
# ---------------------------------------------------------------------------


@event.listens_for(Session, "after_begin")
def _rls_after_begin(
    session: Session,
    transaction: object,  # noqa: ARG001 — required by SQLAlchemy listener signature
    connection: object,
) -> None:
    """Re-issue ``SET LOCAL app.current_user_id`` at the start of each
    transaction if the session carries an RLS user id in ``info``.

    ``after_begin`` fires synchronously on the sync Session. For async
    sessions, we're inside a greenlet that SQLAlchemy's async layer
    manages, so ``connection.execute`` talks to the real driver.
    """
    from app.core.rls import RLS_INFO_KEY  # avoid import cycle at module load

    rls_user_id = session.info.get(RLS_INFO_KEY)
    if rls_user_id is None:
        return

    # UUID repr is hex/hyphens only — safe to interpolate (``SET LOCAL``
    # does not support bound parameters in PostgreSQL).
    connection.execute(text(f"SET LOCAL app.current_user_id = '{rls_user_id}'"))  # type: ignore[attr-defined]


async def init_db() -> None:
    """Create all tables (for development only - use Alembic in production).

    Uses direct connection since DDL operations require it.
    """
    async with direct_engine.begin() as conn:
        # Enable pg_trgm for fuzzy duplicate detection in work items
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(SQLModel.metadata.create_all)
        # GIN trigram index for fast similarity queries on work item titles
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_work_items_title_trgm "
                "ON work_items USING gin (title gin_trgm_ops)"
            )
        )
