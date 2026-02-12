"""DB integration tests for ProductAccessOperations.

Tests real SQL against PostgreSQL via rollback fixture.
Covers: set_access (create + update), effective_access (owner=admin,
member+explicit, member without explicit), remove_access, and bulk
effective_access.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.product_access_operations import product_access_ops
from app.models.organization import MemberRole
from app.models.product_access import ProductAccessLevel


# ─────────────────────────────────────────────────────────────────────────────
# set_access (create + update)
# ─────────────────────────────────────────────────────────────────────────────


class TestSetAccess:
    """Test creating and updating product access."""

    async def test_set_access_creates_new(
        self, db_session: AsyncSession, test_product, second_user
    ):
        """set_access creates a new record if none exists."""
        access = await product_access_ops.set_access(
            db_session, test_product.id, second_user.id, ProductAccessLevel.EDITOR.value
        )

        assert access.id is not None
        assert access.product_id == test_product.id
        assert access.user_id == second_user.id
        assert access.access_level == ProductAccessLevel.EDITOR.value

    async def test_set_access_updates_existing(
        self, db_session: AsyncSession, test_product, second_user
    ):
        """set_access updates existing record if one exists."""
        # Create
        original = await product_access_ops.set_access(
            db_session, test_product.id, second_user.id, ProductAccessLevel.VIEWER.value
        )

        # Update
        updated = await product_access_ops.set_access(
            db_session, test_product.id, second_user.id, ProductAccessLevel.ADMIN.value
        )

        assert updated.id == original.id  # Same record
        assert updated.access_level == ProductAccessLevel.ADMIN.value


# ─────────────────────────────────────────────────────────────────────────────
# Effective access (org role + explicit access)
# ─────────────────────────────────────────────────────────────────────────────


class TestEffectiveAccess:
    """Test effective access computation with real DB."""

    async def test_owner_always_admin(
        self, db_session: AsyncSession, test_product, test_user
    ):
        """Org owner always gets admin access, regardless of explicit access."""
        access = await product_access_ops.get_effective_access(
            db_session, test_product.id, test_user.id, MemberRole.OWNER.value
        )
        assert access == ProductAccessLevel.ADMIN.value

    async def test_admin_always_admin(
        self, db_session: AsyncSession, test_product, second_user
    ):
        """Org admin always gets admin access."""
        access = await product_access_ops.get_effective_access(
            db_session, test_product.id, second_user.id, MemberRole.ADMIN.value
        )
        assert access == ProductAccessLevel.ADMIN.value

    async def test_member_with_explicit_access(
        self, db_session: AsyncSession, test_product, second_user
    ):
        """Member with explicit access gets that access level."""
        await product_access_ops.set_access(
            db_session, test_product.id, second_user.id, ProductAccessLevel.EDITOR.value
        )

        access = await product_access_ops.get_effective_access(
            db_session, test_product.id, second_user.id, MemberRole.MEMBER.value
        )
        assert access == ProductAccessLevel.EDITOR.value

    async def test_member_without_explicit_access(
        self, db_session: AsyncSession, test_product, second_user
    ):
        """Member without explicit access gets 'none'."""
        access = await product_access_ops.get_effective_access(
            db_session, test_product.id, second_user.id, MemberRole.MEMBER.value
        )
        assert access == ProductAccessLevel.NONE.value


# ─────────────────────────────────────────────────────────────────────────────
# Remove access
# ─────────────────────────────────────────────────────────────────────────────


class TestRemoveAccess:
    """Test removing explicit product access."""

    async def test_remove_existing_access(
        self, db_session: AsyncSession, test_product, second_user
    ):
        """Can remove explicit access for a user."""
        await product_access_ops.set_access(
            db_session, test_product.id, second_user.id, ProductAccessLevel.EDITOR.value
        )

        removed = await product_access_ops.remove_access(
            db_session, test_product.id, second_user.id
        )
        assert removed is True

        # Verify access is gone
        level = await product_access_ops.get_user_access_level(
            db_session, test_product.id, second_user.id
        )
        assert level is None

    async def test_remove_nonexistent_access(
        self, db_session: AsyncSession, test_product, second_user
    ):
        """Removing access that doesn't exist returns False."""
        removed = await product_access_ops.remove_access(
            db_session, test_product.id, second_user.id
        )
        assert removed is False


# ─────────────────────────────────────────────────────────────────────────────
# Bulk effective access
# ─────────────────────────────────────────────────────────────────────────────


class TestBulkAccess:
    """Test bulk access operations."""

    async def test_bulk_effective_access_owner(
        self, db_session: AsyncSession, test_user, test_product, test_org, test_subscription
    ):
        """Owner gets admin access to all products in bulk."""
        from app.domain.product_operations import product_ops

        product2 = await product_ops.create(
            db_session,
            obj_in={
                "name": "Bulk Test Product",
                "organization_id": test_org.id,
            },
            user_id=test_user.id,
        )

        result = await product_access_ops.get_effective_access_bulk(
            db_session,
            [test_product.id, product2.id],
            test_user.id,
            MemberRole.OWNER.value,
        )

        assert result[test_product.id] == ProductAccessLevel.ADMIN.value
        assert result[product2.id] == ProductAccessLevel.ADMIN.value

    async def test_bulk_effective_access_member(
        self, db_session: AsyncSession, test_user, second_user, test_product, test_org, test_subscription
    ):
        """Member gets mixed access based on explicit product access."""
        from app.domain.product_operations import product_ops

        product2 = await product_ops.create(
            db_session,
            obj_in={
                "name": "Member Bulk Test",
                "organization_id": test_org.id,
            },
            user_id=test_user.id,
        )

        # Give second_user explicit editor access to product2 only
        await product_access_ops.set_access(
            db_session, product2.id, second_user.id, ProductAccessLevel.EDITOR.value
        )

        result = await product_access_ops.get_effective_access_bulk(
            db_session,
            [test_product.id, product2.id],
            second_user.id,
            MemberRole.MEMBER.value,
        )

        assert result[test_product.id] == ProductAccessLevel.NONE.value
        assert result[product2.id] == ProductAccessLevel.EDITOR.value

    async def test_get_product_collaborators(
        self, db_session: AsyncSession, test_product, second_user
    ):
        """get_product_collaborators returns non-NONE access entries."""
        await product_access_ops.set_access(
            db_session, test_product.id, second_user.id, ProductAccessLevel.VIEWER.value
        )

        collabs = await product_access_ops.get_product_collaborators(
            db_session, test_product.id
        )
        collab_ids = [c.user_id for c in collabs]
        assert second_user.id in collab_ids
