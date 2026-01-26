"""Domain operations for Organization model."""

import re
import secrets
import uuid as uuid_pkg

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.organization import MemberRole, Organization, OrganizationMember
from app.models.subscription import PlanTier, Subscription, SubscriptionStatus


def generate_slug(name: str) -> str:
    """Generate a URL-friendly slug from a name."""
    # Lowercase and replace spaces/special chars with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower())
    # Remove leading/trailing hyphens
    slug = slug.strip("-")
    # Add random suffix for uniqueness
    suffix = secrets.token_hex(3)
    return f"{slug}-{suffix}"


class OrganizationOperations:
    """CRUD operations for Organization model."""

    async def get(
        self,
        db: AsyncSession,
        id: uuid_pkg.UUID,
    ) -> Organization | None:
        """Get an organization by ID."""
        statement = select(Organization).where(Organization.id == id)
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def get_with_members(
        self,
        db: AsyncSession,
        id: uuid_pkg.UUID,
    ) -> Organization | None:
        """Get an organization with all members eagerly loaded."""
        statement = (
            select(Organization)
            .where(Organization.id == id)
            .options(selectinload(Organization.members))
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_slug(
        self,
        db: AsyncSession,
        slug: str,
    ) -> Organization | None:
        """Get an organization by its slug."""
        statement = select(Organization).where(Organization.slug == slug)
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_owner(
        self,
        db: AsyncSession,
        owner_id: uuid_pkg.UUID,
    ) -> list[Organization]:
        """Get all organizations owned by a user."""
        statement = (
            select(Organization)
            .where(Organization.owner_id == owner_id)
            .order_by(Organization.created_at.desc())
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_for_user(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
    ) -> list[Organization]:
        """Get all organizations a user is a member of (including owned)."""
        statement = (
            select(Organization)
            .join(OrganizationMember)
            .where(OrganizationMember.user_id == user_id)
            .order_by(Organization.created_at.desc())
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_all(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Organization]:
        """Get all organizations (admin only)."""
        statement = (
            select(Organization).offset(skip).limit(limit).order_by(Organization.created_at.desc())
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def count(
        self,
        db: AsyncSession,
    ) -> int:
        """Count all organizations."""
        statement = select(func.count()).select_from(Organization)
        result = await db.execute(statement)
        return result.scalar() or 0

    async def create(
        self,
        db: AsyncSession,
        name: str,
        owner_id: uuid_pkg.UUID,
        slug: str | None = None,
        plan_tier: str = PlanTier.NONE.value,
        subscription_status: str = SubscriptionStatus.PENDING.value,
    ) -> Organization:
        """
        Create a new organization.

        Also creates:
        - An owner membership for the creator
        - A subscription (defaults to pending "none" tier for new signups)

        Args:
            plan_tier: Defaults to "none" for new signups awaiting plan selection.
            subscription_status: Defaults to "pending" for new signups.
        """
        if not slug:
            slug = generate_slug(name)

        # Ensure slug is unique
        existing = await self.get_by_slug(db, slug)
        if existing:
            slug = generate_slug(name)  # Regenerate with new suffix

        org = Organization(
            name=name,
            slug=slug,
            owner_id=owner_id,
        )
        db.add(org)
        await db.flush()

        # Add owner as a member with OWNER role
        member = OrganizationMember(
            organization_id=org.id,
            user_id=owner_id,
            role=MemberRole.OWNER.value,
        )
        db.add(member)

        # Create subscription
        # Import get_plan here to avoid circular imports
        from app.config.plans import get_plan

        plan = get_plan(plan_tier)
        subscription = Subscription(
            organization_id=org.id,
            plan_tier=plan_tier,
            status=subscription_status,
            base_repo_limit=plan.base_repo_limit,
        )
        db.add(subscription)

        await db.flush()
        await db.refresh(org)

        return org

    async def create_personal_org(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
        user_name: str | None = None,
        user_email: str | None = None,
    ) -> Organization:
        """
        Create a personal organization for a user.

        Called during user signup to create their default workspace.
        """
        # Generate name from display name, email, or fallback
        if user_name:
            name = f"{user_name}'s Workspace"
        elif user_email:
            name = f"{user_email.split('@')[0]}'s Workspace"
        else:
            name = "My Workspace"

        return await self.create(db, name=name, owner_id=user_id)

    async def update(
        self,
        db: AsyncSession,
        org: Organization,
        updates: dict,
    ) -> Organization:
        """Update an organization."""
        for field, value in updates.items():
            if value is not None:
                setattr(org, field, value)
        db.add(org)
        await db.flush()
        await db.refresh(org)
        return org

    async def delete(
        self,
        db: AsyncSession,
        id: uuid_pkg.UUID,
    ) -> bool:
        """Delete an organization by ID."""
        org = await self.get(db, id)
        if org:
            await db.delete(org)
            await db.flush()
            return True
        return False

    async def is_member(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
    ) -> bool:
        """Check if a user is a member of an organization."""
        statement = select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none() is not None

    async def get_member_role(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
    ) -> MemberRole | None:
        """Get a user's role in an organization."""
        statement = select(OrganizationMember.role).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def get_member(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
    ) -> OrganizationMember | None:
        """Get a specific membership record."""
        statement = select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def transfer_ownership(
        self,
        db: AsyncSession,
        org_id: uuid_pkg.UUID,
        current_owner_id: uuid_pkg.UUID,
        new_owner_id: uuid_pkg.UUID,
        remove_previous_owner: bool = False,
    ) -> Organization:
        """
        Transfer ownership of an organization to an existing member.

        Args:
            org_id: The organization to transfer
            current_owner_id: The current owner (for verification)
            new_owner_id: The user to become the new owner (must be existing member)
            remove_previous_owner: If True, remove previous owner's membership entirely.
                                   If False, downgrade to ADMIN role.

        Returns:
            The updated organization

        Raises:
            ValueError: If validation fails (not owner, target not a member, etc.)
        """
        # 1. Verify org exists and current user is owner
        org = await self.get(db, org_id)
        if not org:
            raise ValueError("Organization not found")
        if org.owner_id != current_owner_id:
            raise ValueError("Only the owner can transfer ownership")

        # 2. Prevent transferring to yourself
        if new_owner_id == current_owner_id:
            raise ValueError("Cannot transfer ownership to yourself")

        # 3. Verify new owner is an existing member
        new_owner_membership = await self.get_member(db, org_id, new_owner_id)
        if not new_owner_membership:
            raise ValueError("New owner must be an existing member of the organization")

        # 4. Get current owner's membership
        current_owner_membership = await self.get_member(db, org_id, current_owner_id)
        if not current_owner_membership:
            raise ValueError("Current owner membership not found")

        # 5. Update org.owner_id
        org.owner_id = new_owner_id

        # 6. Update new owner's role to OWNER
        new_owner_membership.role = MemberRole.OWNER.value

        # 7. Handle previous owner's membership
        if remove_previous_owner:
            await db.delete(current_owner_membership)
        else:
            current_owner_membership.role = MemberRole.ADMIN.value

        db.add(org)
        db.add(new_owner_membership)
        if not remove_previous_owner:
            db.add(current_owner_membership)

        await db.flush()
        await db.refresh(org)

        return org


organization_ops = OrganizationOperations()
