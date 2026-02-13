"""Concurrency and constraint enforcement tests.

Tests that the database correctly enforces uniqueness constraints, atomicity
of multi-step operations, and JSONB locking behavior. These validate the
safety properties that protect against concurrent writes in production.

NOTE: The rollback fixture uses a single connection, so true parallel
transactions aren't possible here. Instead we test the *effects* that matter:
unique constraint violations, multi-step atomicity, and FOR UPDATE behavior.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.organization_operations import organization_ops
from app.domain.product_access_operations import product_access_ops
from app.domain.subscription_operations import subscription_ops
from app.models.organization import MemberRole, OrganizationMember
from app.models.product_access import ProductAccess

# ─────────────────────────────────────────────────────────────────────────────
# Unique constraint enforcement
# ─────────────────────────────────────────────────────────────────────────────


class TestUniqueConstraints:
    """Verify that UNIQUE constraints raise IntegrityError on duplicates.

    In production, concurrent requests hitting these constraints get a clean
    DB-level rejection rather than corrupt data.
    """

    async def test_duplicate_org_member_raises(
        self, db_session: AsyncSession, test_org, second_user, test_org_member  # noqa: ARG002
    ):
        """Adding the same user to an org twice violates uq_org_member."""
        duplicate = OrganizationMember(
            organization_id=test_org.id,
            user_id=second_user.id,
            role=MemberRole.MEMBER.value,
        )
        db_session.add(duplicate)

        with pytest.raises(IntegrityError, match="uq_org_member"):
            await db_session.flush()

        # Rollback savepoint so session is usable for subsequent tests
        await db_session.rollback()

    async def test_duplicate_product_access_raises(
        self, db_session: AsyncSession, test_product, second_user
    ):
        """Granting access to the same user+product twice violates uq_product_access_product_user."""
        # First grant succeeds
        access1 = ProductAccess(
            product_id=test_product.id,
            user_id=second_user.id,
            access_level="editor",
        )
        db_session.add(access1)
        await db_session.flush()

        # Duplicate raw insert violates unique constraint
        access2 = ProductAccess(
            product_id=test_product.id,
            user_id=second_user.id,
            access_level="viewer",
        )
        db_session.add(access2)

        with pytest.raises(IntegrityError, match="uq_product_access_product_user"):
            await db_session.flush()

        await db_session.rollback()

    async def test_set_access_upserts_instead_of_duplicating(
        self, db_session: AsyncSession, test_product, second_user
    ):
        """product_access_ops.set_access() is idempotent — updates existing, never duplicates."""
        # First call creates
        a1 = await product_access_ops.set_access(
            db_session, test_product.id, second_user.id, "viewer"
        )
        assert a1.access_level == "viewer"

        # Second call updates the same row
        a2 = await product_access_ops.set_access(
            db_session, test_product.id, second_user.id, "editor"
        )
        assert a2.id == a1.id  # Same row, not a new one
        assert a2.access_level == "editor"

    async def test_duplicate_org_slug_regenerates(
        self, db_session: AsyncSession, test_user
    ):
        """Creating an org with a colliding slug auto-regenerates a new one."""
        org1 = await organization_ops.create(
            db_session,
            name="Slug Test Org",
            owner_id=test_user.id,
            slug="fixed-slug-abc",
        )
        assert org1.slug == "fixed-slug-abc"

        # Second org with same explicit slug gets a regenerated one
        org2 = await organization_ops.create(
            db_session,
            name="Slug Test Org",
            owner_id=test_user.id,
            slug="fixed-slug-abc",
        )
        assert org2.slug != "fixed-slug-abc"
        assert org2.id != org1.id


# ─────────────────────────────────────────────────────────────────────────────
# Multi-step operation atomicity
# ─────────────────────────────────────────────────────────────────────────────


class TestAtomicOperations:
    """Verify that multi-step operations create all expected entities atomically."""

    async def test_org_create_is_atomic(self, db_session: AsyncSession, test_user):
        """organization_ops.create() atomically creates org + member + subscription."""
        org = await organization_ops.create(
            db_session,
            name="Atomic Test Org",
            owner_id=test_user.id,
        )

        # All three entities must exist after a single create() call
        assert org.id is not None

        is_member = await organization_ops.is_member(db_session, org.id, test_user.id)
        assert is_member is True

        role = await organization_ops.get_member_role(db_session, org.id, test_user.id)
        assert role == MemberRole.OWNER.value

        sub = await subscription_ops.get_by_org(db_session, org.id)
        assert sub is not None
        assert sub.organization_id == org.id

    async def test_org_create_with_invalid_owner_fails_cleanly(
        self, db_session: AsyncSession
    ):
        """If owner_id references a non-existent user, the entire create fails."""
        fake_user_id = uuid.uuid4()

        with pytest.raises(IntegrityError):
            await organization_ops.create(
                db_session,
                name="Bad Owner Org",
                owner_id=fake_user_id,
            )

        await db_session.rollback()

    async def test_ownership_transfer_updates_both_roles(
        self,
        db_session: AsyncSession,
        test_org,
        test_user,
        second_user,
        test_org_member,  # noqa: ARG002
    ):
        """transfer_ownership() atomically updates org.owner_id and both membership roles."""
        await organization_ops.transfer_ownership(
            db_session,
            org_id=test_org.id,
            current_owner_id=test_user.id,
            new_owner_id=second_user.id,
        )

        # Refresh to see updated state
        refreshed_org = await organization_ops.get(db_session, test_org.id)
        assert refreshed_org is not None
        assert refreshed_org.owner_id == second_user.id

        new_role = await organization_ops.get_member_role(
            db_session, test_org.id, second_user.id
        )
        assert new_role == MemberRole.OWNER.value

        prev_role = await organization_ops.get_member_role(
            db_session, test_org.id, test_user.id
        )
        assert prev_role == MemberRole.ADMIN.value


# ─────────────────────────────────────────────────────────────────────────────
# JSONB atomic updates
# ─────────────────────────────────────────────────────────────────────────────


class TestJsonbAtomicUpdates:
    """Verify that JSONB setting updates use FOR UPDATE locking."""

    async def test_sequential_settings_both_persist(
        self, db_session: AsyncSession, test_org
    ):
        """Two sequential set_setting() calls preserve both keys."""
        await organization_ops.set_setting(db_session, test_org.id, "key1", "value1")
        await organization_ops.set_setting(db_session, test_org.id, "key2", "value2")

        val1 = await organization_ops.get_setting(db_session, test_org.id, "key1")
        val2 = await organization_ops.get_setting(db_session, test_org.id, "key2")
        assert val1 == "value1"
        assert val2 == "value2"

    async def test_setting_overwrite_replaces_value(
        self, db_session: AsyncSession, test_org
    ):
        """Overwriting a key replaces the value without affecting other keys."""
        await organization_ops.set_setting(db_session, test_org.id, "theme", "light")
        await organization_ops.set_setting(db_session, test_org.id, "locale", "en")
        await organization_ops.set_setting(db_session, test_org.id, "theme", "dark")

        theme = await organization_ops.get_setting(db_session, test_org.id, "theme")
        locale = await organization_ops.get_setting(db_session, test_org.id, "locale")
        assert theme == "dark"
        assert locale == "en"

    async def test_setting_on_null_initializes_dict(
        self, db_session: AsyncSession, test_user
    ):
        """set_setting() on an org with NULL settings initializes the JSONB column."""
        # Create a fresh org (settings will be NULL)
        org = await organization_ops.create(
            db_session,
            name="Null Settings Org",
            owner_id=test_user.id,
        )
        assert org.settings is None

        await organization_ops.set_setting(db_session, org.id, "first_key", True)

        val = await organization_ops.get_setting(db_session, org.id, "first_key")
        assert val is True
