"""DB integration tests for OrganizationOperations.

Tests real SQL execution against PostgreSQL via the rollback fixture.
Covers: creation cascade, slug generation, lookups, membership checks,
settings JSONB, and ownership transfer.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.organization_operations import generate_slug, organization_ops
from app.domain.subscription_operations import subscription_ops
from app.models.organization import MemberRole


# ─────────────────────────────────────────────────────────────────────────────
# Creation cascade
# ─────────────────────────────────────────────────────────────────────────────


class TestOrganizationCreation:
    """Test org creation and its automatic side effects."""

    async def test_create_org_returns_organization(self, db_session: AsyncSession, test_user):
        """Creating an org returns a valid Organization with correct fields."""
        org = await organization_ops.create(
            db_session, name="Integration Test Org", owner_id=test_user.id
        )

        assert org.id is not None
        assert org.name == "Integration Test Org"
        assert org.owner_id == test_user.id
        assert org.slug is not None
        assert len(org.slug) > 0

    async def test_create_org_creates_owner_membership(
        self, db_session: AsyncSession, test_user
    ):
        """Creating an org auto-creates an OWNER membership for the creator."""
        org = await organization_ops.create(
            db_session, name="Membership Test Org", owner_id=test_user.id
        )

        is_member = await organization_ops.is_member(db_session, org.id, test_user.id)
        assert is_member is True

        role = await organization_ops.get_member_role(db_session, org.id, test_user.id)
        assert role == MemberRole.OWNER.value

    async def test_create_org_creates_subscription(self, db_session: AsyncSession, test_user):
        """Creating an org auto-creates a subscription (defaults to 'none'/pending)."""
        org = await organization_ops.create(
            db_session, name="Sub Test Org", owner_id=test_user.id
        )

        sub = await subscription_ops.get_by_org(db_session, org.id)
        assert sub is not None
        assert sub.organization_id == org.id
        assert sub.plan_tier == "none"
        assert sub.status == "pending"


# ─────────────────────────────────────────────────────────────────────────────
# Slug generation
# ─────────────────────────────────────────────────────────────────────────────


class TestSlugGeneration:
    """Test slug generation and uniqueness."""

    def test_generate_slug_produces_url_safe_string(self):
        """Slug should be lowercase, hyphenated, with a random suffix."""
        slug = generate_slug("My Cool Organization!")
        assert slug.startswith("my-cool-organization-")
        # 6-char hex suffix
        suffix = slug.split("-")[-1]
        assert len(suffix) == 6

    def test_generate_slug_strips_special_chars(self):
        """Special characters should be replaced with hyphens."""
        slug = generate_slug("Test @#$ Org")
        assert "@" not in slug
        assert "#" not in slug
        assert "$" not in slug

    async def test_create_personal_org_naming(self, db_session: AsyncSession, test_user):
        """Personal org uses display name or email for naming."""
        org = await organization_ops.create_personal_org(
            db_session, user_id=test_user.id, user_name="Alice"
        )
        assert org.name == "Alice's Workspace"

    async def test_create_personal_org_email_fallback(self, db_session: AsyncSession, test_user):
        """Without display name, personal org falls back to email prefix."""
        # Create a second user to avoid conflicts
        from app.models.user import User
        from datetime import UTC, datetime

        user2 = User(
            id=uuid.uuid4(),
            email="bob@example.com",
            created_at=datetime.now(UTC),
        )
        db_session.add(user2)
        await db_session.flush()

        org = await organization_ops.create_personal_org(
            db_session, user_id=user2.id, user_email="bob@example.com"
        )
        assert org.name == "bob's Workspace"


# ─────────────────────────────────────────────────────────────────────────────
# Lookup methods
# ─────────────────────────────────────────────────────────────────────────────


class TestOrganizationLookups:
    """Test org retrieval by various keys."""

    async def test_get_by_slug(self, db_session: AsyncSession, test_org):
        """Can retrieve an org by its slug."""
        found = await organization_ops.get_by_slug(db_session, test_org.slug)
        assert found is not None
        assert found.id == test_org.id

    async def test_get_by_slug_not_found(self, db_session: AsyncSession):
        """Returns None for a non-existent slug."""
        found = await organization_ops.get_by_slug(db_session, "nonexistent-slug-xyz")
        assert found is None

    async def test_get_for_user(self, db_session: AsyncSession, test_user, test_org):
        """get_for_user returns all orgs the user is a member of."""
        orgs = await organization_ops.get_for_user(db_session, test_user.id)
        org_ids = [o.id for o in orgs]
        assert test_org.id in org_ids

    async def test_is_member_true(self, db_session: AsyncSession, test_org, test_user):
        """Owner is recognized as a member."""
        assert await organization_ops.is_member(db_session, test_org.id, test_user.id) is True

    async def test_is_member_false(self, db_session: AsyncSession, test_org, second_user):
        """Non-member is not recognized."""
        assert await organization_ops.is_member(db_session, test_org.id, second_user.id) is False


# ─────────────────────────────────────────────────────────────────────────────
# Ownership transfer
# ─────────────────────────────────────────────────────────────────────────────


class TestOwnershipTransfer:
    """Test organization ownership transfer."""

    async def test_transfer_ownership(
        self, db_session: AsyncSession, test_org, test_user, second_user, test_org_member
    ):
        """Can transfer ownership to an existing member."""
        updated = await organization_ops.transfer_ownership(
            db_session,
            org_id=test_org.id,
            current_owner_id=test_user.id,
            new_owner_id=second_user.id,
        )

        assert updated.owner_id == second_user.id

        # New owner should have OWNER role
        new_role = await organization_ops.get_member_role(
            db_session, test_org.id, second_user.id
        )
        assert new_role == MemberRole.OWNER.value

        # Previous owner should be downgraded to ADMIN
        prev_role = await organization_ops.get_member_role(
            db_session, test_org.id, test_user.id
        )
        assert prev_role == MemberRole.ADMIN.value

    async def test_transfer_to_non_member_raises(
        self, db_session: AsyncSession, test_org, test_user, second_user
    ):
        """Cannot transfer ownership to someone who isn't a member."""
        with pytest.raises(ValueError, match="existing member"):
            await organization_ops.transfer_ownership(
                db_session,
                org_id=test_org.id,
                current_owner_id=test_user.id,
                new_owner_id=second_user.id,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Settings JSONB
# ─────────────────────────────────────────────────────────────────────────────


class TestOrganizationSettings:
    """Test JSONB settings helpers."""

    async def test_set_and_get_setting(self, db_session: AsyncSession, test_org):
        """Can write and read a typed setting."""
        await organization_ops.set_setting(db_session, test_org.id, "theme", "dark")
        value = await organization_ops.get_setting(db_session, test_org.id, "theme")
        assert value == "dark"

    async def test_get_setting_default(self, db_session: AsyncSession, test_org):
        """Missing key returns the specified default."""
        value = await organization_ops.get_setting(
            db_session, test_org.id, "nonexistent", default="fallback"
        )
        assert value == "fallback"

    async def test_auto_progress_toggle(self, db_session: AsyncSession, test_org):
        """Can enable and disable auto-progress."""
        # Default is False
        assert await organization_ops.get_auto_progress_enabled(db_session, test_org.id) is False

        await organization_ops.set_auto_progress_enabled(db_session, test_org.id, True)
        assert await organization_ops.get_auto_progress_enabled(db_session, test_org.id) is True

        await organization_ops.set_auto_progress_enabled(db_session, test_org.id, False)
        assert await organization_ops.get_auto_progress_enabled(db_session, test_org.id) is False

    async def test_get_orgs_with_auto_progress(self, db_session: AsyncSession, test_org):
        """get_orgs_with_auto_progress returns only enabled orgs."""
        await organization_ops.set_auto_progress_enabled(db_session, test_org.id, True)

        orgs = await organization_ops.get_orgs_with_auto_progress(db_session)
        org_ids = [o.id for o in orgs]
        assert test_org.id in org_ids
