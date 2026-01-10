"""Domain operations for OrganizationMember model."""

import uuid as uuid_pkg
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.organization import MemberRole, OrganizationMember
from app.models.user import User


class OrgMemberOperations:
    """CRUD operations for OrganizationMember model."""

    async def get(
        self,
        db: AsyncSession,
        id: uuid_pkg.UUID,
    ) -> OrganizationMember | None:
        """Get a membership by ID."""
        statement = select(OrganizationMember).where(OrganizationMember.id == id)
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_org_and_user(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
    ) -> OrganizationMember | None:
        """Get a specific membership by org and user."""
        statement = select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_org(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
    ) -> list[OrganizationMember]:
        """Get all members of an organization."""
        statement = (
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == organization_id)
            .options(selectinload(OrganizationMember.user))
            .order_by(OrganizationMember.joined_at.desc())
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_by_user(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
    ) -> list[OrganizationMember]:
        """Get all memberships for a user."""
        statement = (
            select(OrganizationMember)
            .where(OrganizationMember.user_id == user_id)
            .options(selectinload(OrganizationMember.organization))
            .order_by(OrganizationMember.joined_at.desc())
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def count_by_org(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
    ) -> int:
        """Count members in an organization."""
        statement = (
            select(func.count())
            .select_from(OrganizationMember)
            .where(OrganizationMember.organization_id == organization_id)
        )
        result = await db.execute(statement)
        return result.scalar() or 0

    async def add_member(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
        role: str = MemberRole.MEMBER.value,
        invited_by: uuid_pkg.UUID | None = None,
    ) -> OrganizationMember:
        """Add a user to an organization."""
        member = OrganizationMember(
            organization_id=organization_id,
            user_id=user_id,
            role=role,
            invited_by=invited_by,
            invited_at=datetime.utcnow() if invited_by else None,
        )
        db.add(member)
        await db.flush()
        await db.refresh(member)
        return member

    async def update_role(
        self,
        db: AsyncSession,
        membership: OrganizationMember,
        new_role: MemberRole,
    ) -> OrganizationMember:
        """Update a member's role."""
        membership.role = new_role
        db.add(membership)
        await db.flush()
        await db.refresh(membership)
        return membership

    async def remove_member(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
    ) -> bool:
        """Remove a user from an organization."""
        member = await self.get_by_org_and_user(db, organization_id, user_id)
        if member:
            await db.delete(member)
            await db.flush()
            return True
        return False

    async def find_user_by_email(
        self,
        db: AsyncSession,
        email: str,
    ) -> User | None:
        """Find a user by email for invitations."""
        statement = select(User).where(User.email == email)
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def get_owners(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
    ) -> list[OrganizationMember]:
        """Get all owners of an organization."""
        statement = (
            select(OrganizationMember)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.role == MemberRole.OWNER.value,
            )
            .options(selectinload(OrganizationMember.user))
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def is_only_owner(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
    ) -> bool:
        """Check if a user is the only owner of an organization."""
        owners = await self.get_owners(db, organization_id)
        return len(owners) == 1 and owners[0].user_id == user_id


org_member_ops = OrgMemberOperations()
