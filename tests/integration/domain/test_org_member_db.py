"""DB integration tests for OrgMemberOperations.

Tests real SQL against PostgreSQL via rollback fixture.
Covers: add member, get_by_org (eager load), count, update_role,
remove, and is_only_owner guard.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.org_member_operations import org_member_ops
from app.models.organization import MemberRole


# ─────────────────────────────────────────────────────────────────────────────
# Member CRUD
# ─────────────────────────────────────────────────────────────────────────────


class TestOrgMemberCRUD:
    """Test member add, read, update, remove."""

    async def test_add_member(
        self, db_session: AsyncSession, test_org, second_user, test_user
    ):
        """Can add a user as a member of an organization."""
        member = await org_member_ops.add_member(
            db_session,
            organization_id=test_org.id,
            user_id=second_user.id,
            role=MemberRole.MEMBER.value,
            invited_by=test_user.id,
        )

        assert member.id is not None
        assert member.organization_id == test_org.id
        assert member.user_id == second_user.id
        assert member.role == MemberRole.MEMBER.value
        assert member.invited_by == test_user.id
        assert member.invited_at is not None

    async def test_get_by_org_with_eager_load(
        self, db_session: AsyncSession, test_org, test_org_member  # noqa: ARG002
    ):
        """get_by_org returns members with user relationship loaded."""
        members = await org_member_ops.get_by_org(db_session, test_org.id)
        assert len(members) >= 2  # owner + test_org_member

        # User relationship should be loaded (not lazy)
        for m in members:
            assert m.user is not None
            assert m.user.email is not None

    async def test_count_by_org(
        self, db_session: AsyncSession, test_org, test_org_member  # noqa: ARG002
    ):
        """count_by_org returns correct member count."""
        count = await org_member_ops.count_by_org(db_session, test_org.id)
        assert count >= 2  # owner + test_org_member

    async def test_update_role(
        self, db_session: AsyncSession, test_org_member
    ):
        """Can update a member's role."""
        updated = await org_member_ops.update_role(
            db_session, test_org_member, MemberRole.ADMIN.value
        )
        assert updated.role == MemberRole.ADMIN.value

    async def test_remove_member(
        self, db_session: AsyncSession, test_org, second_user, test_org_member  # noqa: ARG002
    ):
        """Can remove a member from an organization."""
        removed = await org_member_ops.remove_member(
            db_session, test_org.id, second_user.id
        )
        assert removed is True

        # Verify they're gone
        member = await org_member_ops.get_by_org_and_user(
            db_session, test_org.id, second_user.id
        )
        assert member is None

    async def test_remove_nonexistent_member(
        self, db_session: AsyncSession, test_org, second_user
    ):
        """Removing a non-member returns False."""
        removed = await org_member_ops.remove_member(
            db_session, test_org.id, second_user.id
        )
        assert removed is False


# ─────────────────────────────────────────────────────────────────────────────
# Ownership guard
# ─────────────────────────────────────────────────────────────────────────────


class TestOrgMemberOwnership:
    """Test is_only_owner guard."""

    async def test_is_only_owner_true(
        self, db_session: AsyncSession, test_org, test_user
    ):
        """Returns True when user is the only owner."""
        assert await org_member_ops.is_only_owner(
            db_session, test_org.id, test_user.id
        ) is True

    async def test_is_only_owner_false_after_transfer(
        self, db_session: AsyncSession, test_org, test_user, second_user, test_org_member  # noqa: ARG002
    ):
        """Returns False when there are multiple owners."""
        # Promote second_user to owner
        member = await org_member_ops.get_by_org_and_user(
            db_session, test_org.id, second_user.id
        )
        await org_member_ops.update_role(db_session, member, MemberRole.OWNER.value)

        assert await org_member_ops.is_only_owner(
            db_session, test_org.id, test_user.id
        ) is False

    async def test_get_owners(
        self, db_session: AsyncSession, test_org, test_user
    ):
        """get_owners returns all owners with user loaded."""
        owners = await org_member_ops.get_owners(db_session, test_org.id)
        assert len(owners) >= 1
        owner_ids = [o.user_id for o in owners]
        assert test_user.id in owner_ids
        # User relationship should be loaded
        assert owners[0].user is not None
