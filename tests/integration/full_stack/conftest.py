"""Full-stack integration test conftest.

Provides real infrastructure fixtures for testing against:
- Real Supabase Auth (user creation, JWT tokens)
- Real database (commits are REAL — cleanup required)
- Stripe sandbox (checkout, webhooks)

These tests create real resources and MUST clean up after themselves.
"""

from __future__ import annotations

import logging

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config.settings import settings
from tests.helpers.auth import auth_header, create_supabase_test_user
from tests.helpers.cleanup import TestCleanup
from tests.helpers.tracker import ResourceTracker

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Direct DB engine for real commits (cleanup operations)
# ─────────────────────────────────────────────────────────────────────────────

_DIRECT_ENGINE = create_async_engine(
    settings.database_url_direct,
    echo=False,
    pool_pre_ping=True,
    pool_size=2,
    max_overflow=2,
    connect_args={"command_timeout": 60},
)

_direct_session_maker = sessionmaker(
    _DIRECT_ENGINE,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ─────────────────────────────────────────────────────────────────────────────
# Session-scoped fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def integration_tracker() -> ResourceTracker:
    """Session-scoped resource tracker — shared across all full-stack tests."""
    return ResourceTracker()


@pytest.fixture(scope="session")
async def integration_db():
    """Real DB session for cleanup operations.

    WARNING: Commits are real. Only use for cleanup, not for test setup.
    Test setup should go through the API to exercise the full stack.
    """
    async with _direct_session_maker() as session:
        yield session


@pytest.fixture(scope="session")
async def integration_client():
    """HTTP client that hits the REAL running API (localhost:8000).

    Uses real Supabase JWTs for authentication.
    No dependency overrides — tests the full stack.

    Requires: `npm run dev:backend` running separately.
    """
    async with AsyncClient(base_url="http://localhost:8000") as client:
        yield client


@pytest.fixture(scope="session")
async def test_user_primary(integration_tracker: ResourceTracker):
    """Primary test user — created once per session via Supabase Admin API.

    This user is used as the 'owner' across all full-stack tests.
    """
    user = await create_supabase_test_user()
    integration_tracker.register_user(user.id)
    return user


@pytest.fixture(scope="session")
async def test_user_registered(
    integration_client: AsyncClient,
    test_user_primary,
    integration_tracker: ResourceTracker,
):
    """Primary test user after first API call (triggers auto-provisioning).

    After this fixture:
    - User record exists in the app DB
    - Personal organization created
    - Subscription created with status=pending, tier=none
    """
    response = await integration_client.get(
        "/api/v1/users/me",
        headers=auth_header(test_user_primary.token),
    )
    assert response.status_code == 200, f"Auto-provisioning failed: {response.text}"

    # Track the personal org that was auto-created
    orgs_response = await integration_client.get(
        "/api/v1/organizations",
        headers=auth_header(test_user_primary.token),
    )
    if orgs_response.status_code == 200:
        for org in orgs_response.json():
            integration_tracker.register_org(org["id"])

    return test_user_primary


# ─────────────────────────────────────────────────────────────────────────────
# Auto-markers
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _mark_full_stack(request):
    """Auto-mark all tests in this directory as full_stack."""
    request.node.add_marker(pytest.mark.full_stack)


# ─────────────────────────────────────────────────────────────────────────────
# Session-Level Cleanup Failsafe
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
async def cleanup_on_exit(integration_tracker, integration_db):
    """Guarantee cleanup runs even on test failure.

    This is the last line of defense. Individual tests should also
    clean up after themselves when possible.
    """
    yield
    logger.info("Session ending — running cleanup failsafe...")
    try:
        await TestCleanup().cleanup_all(integration_tracker, integration_db)
    except Exception:
        logger.exception("Cleanup failsafe encountered errors (resources may need manual cleanup)")
