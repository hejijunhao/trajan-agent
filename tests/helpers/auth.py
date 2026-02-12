"""Supabase test user helpers for full-stack integration tests.

Creates and authenticates test users against real Supabase Auth.
Uses identifiable email patterns for cleanup safety.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.config.settings import settings

logger = logging.getLogger(__name__)

# Test email domain — must be a non-existent domain to prevent real email delivery
TEST_EMAIL_DOMAIN = "trajan-integration-test.local"


@dataclass
class TestUser:
    """A test user created in Supabase Auth."""

    id: UUID
    email: str
    token: str  # JWT access token


def generate_test_email() -> str:
    """Generate a unique test email that is identifiable for cleanup."""
    return f"test-{uuid4().hex[:12]}@{TEST_EMAIL_DOMAIN}"


async def create_supabase_test_user(
    email: str | None = None,
    password: str = "TestPass123!",
) -> TestUser:
    """Create a real user in Supabase Auth and return credentials.

    Uses the Supabase Admin API (service role key) to create
    a user with a confirmed email (no verification needed).
    """
    from supabase import create_client

    if email is None:
        email = generate_test_email()

    admin_client = create_client(settings.supabase_url, settings.supabase_service_role_key)

    # Create user with admin API (auto-confirms email)
    response = admin_client.auth.admin.create_user(
        {
            "email": email,
            "password": password,
            "email_confirm": True,
        }
    )

    user_id = UUID(response.user.id)
    logger.info(f"Created Supabase test user: {email} ({user_id})")

    # Sign in to get a JWT token
    token = await sign_in_test_user(email, password)

    return TestUser(id=user_id, email=email, token=token)


async def sign_in_test_user(email: str, password: str = "TestPass123!") -> str:
    """Sign in a test user and return the JWT access token."""
    from supabase import create_client

    client = create_client(settings.supabase_url, settings.supabase_anon_key)
    response = client.auth.sign_in_with_password({"email": email, "password": password})
    return response.session.access_token


def auth_header(token: str) -> dict[str, str]:
    """Build an Authorization header dict from a JWT token."""
    return {"Authorization": f"Bearer {token}"}
