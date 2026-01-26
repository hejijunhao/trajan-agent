import asyncio
import logging
import uuid as uuid_pkg
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.document import Document
from app.models.organization import Organization, OrganizationMember
from app.models.product import Product
from app.models.user import User
from app.models.work_item import WorkItem

logger = logging.getLogger(__name__)


@dataclass
class OrgMemberInfo:
    """Info about an organization member (for ownership transfer selection)."""

    id: uuid_pkg.UUID
    email: str | None
    name: str | None
    role: str


@dataclass
class OrgDeletionPreview:
    """Preview of what happens to an owned organization during account deletion."""

    org_id: uuid_pkg.UUID
    org_name: str
    is_sole_member: bool
    member_count: int
    other_members: list[OrgMemberInfo]
    product_count: int
    work_item_count: int
    document_count: int
    has_active_subscription: bool


@dataclass
class BasicOrgInfo:
    """Minimal info about an org where user is just a member."""

    id: uuid_pkg.UUID
    name: str


@dataclass
class DeletionPreviewResult:
    """Complete deletion preview result."""

    owned_orgs: list[OrgDeletionPreview]
    member_only_orgs: list[BasicOrgInfo]
    total_products_affected: int
    total_work_items_affected: int
    total_documents_affected: int


class UserOperations:
    """Operations for User model."""

    async def get_by_id(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
    ) -> User | None:
        """Get a user by ID."""
        statement = select(User).where(User.id == user_id)
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def update(
        self,
        db: AsyncSession,
        user: User,
        obj_in: dict,
    ) -> User:
        """Update a user's profile fields."""
        for field, value in obj_in.items():
            if value is not None and hasattr(user, field):
                setattr(user, field, value)
        db.add(user)
        await db.flush()
        await db.refresh(user)
        return user

    async def delete(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
    ) -> bool:
        """
        Delete a user and all their data.

        Note: Related data (products, work items, etc.) will cascade delete
        via foreign key constraints.
        """
        user = await self.get_by_id(db, user_id)
        if user:
            await db.delete(user)
            await db.flush()
            return True
        return False

    async def get_deletion_preview(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
    ) -> DeletionPreviewResult:
        """
        Get a preview of what will be affected by account deletion.

        Returns detailed information about:
        - Organizations the user owns (with member counts and data counts)
        - Organizations the user is just a member of (will lose membership)
        - Total counts of products, work items, and documents that will be deleted
        """
        # 1. Get all organizations where user is owner
        owned_orgs_stmt = (
            select(Organization)
            .where(Organization.owner_id == user_id)
            .options(
                selectinload(Organization.members).selectinload(OrganizationMember.user),
                selectinload(Organization.subscription),
            )
        )
        owned_orgs_result = await db.execute(owned_orgs_stmt)
        owned_orgs = list(owned_orgs_result.scalars().all())

        # 2. Get all organizations where user is just a member (not owner)
        member_only_stmt = (
            select(Organization)
            .join(OrganizationMember)
            .where(
                OrganizationMember.user_id == user_id,
                Organization.owner_id != user_id,
            )
        )
        member_only_result = await db.execute(member_only_stmt)
        member_only_orgs = list(member_only_result.scalars().all())

        # 3. Build preview for each owned org
        owned_previews: list[OrgDeletionPreview] = []
        total_products = 0
        total_work_items = 0
        total_documents = 0

        for org in owned_orgs:
            # Count products for this org
            product_count_stmt = (
                select(func.count()).select_from(Product).where(Product.organization_id == org.id)
            )
            product_count = (await db.execute(product_count_stmt)).scalar() or 0

            # Count work items for this org's products
            work_item_count_stmt = (
                select(func.count())
                .select_from(WorkItem)
                .join(Product)
                .where(Product.organization_id == org.id)
            )
            work_item_count = (await db.execute(work_item_count_stmt)).scalar() or 0

            # Count documents for this org's products
            document_count_stmt = (
                select(func.count())
                .select_from(Document)
                .join(Product)
                .where(Product.organization_id == org.id)
            )
            document_count = (await db.execute(document_count_stmt)).scalar() or 0

            # Get other members (excluding current user)
            other_members = [
                OrgMemberInfo(
                    id=m.user_id,
                    email=m.user.email if m.user else None,
                    name=m.user.display_name if m.user else None,
                    role=m.role,
                )
                for m in org.members
                if m.user_id != user_id
            ]

            member_count = len(org.members)
            is_sole_member = member_count == 1

            # Check subscription status
            has_active_subscription = (
                org.subscription is not None and org.subscription.status == "active"
            )

            owned_previews.append(
                OrgDeletionPreview(
                    org_id=org.id,
                    org_name=org.name,
                    is_sole_member=is_sole_member,
                    member_count=member_count,
                    other_members=other_members,
                    product_count=product_count,
                    work_item_count=work_item_count,
                    document_count=document_count,
                    has_active_subscription=has_active_subscription,
                )
            )

            # Only count towards total if org will be deleted (sole member)
            if is_sole_member:
                total_products += product_count
                total_work_items += work_item_count
                total_documents += document_count

        # 4. Build member-only org list
        member_only_list = [BasicOrgInfo(id=org.id, name=org.name) for org in member_only_orgs]

        return DeletionPreviewResult(
            owned_orgs=owned_previews,
            member_only_orgs=member_only_list,
            total_products_affected=total_products,
            total_work_items_affected=total_work_items,
            total_documents_affected=total_documents,
        )

    async def delete_with_cascade(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
        orgs_to_delete: list[uuid_pkg.UUID],
    ) -> tuple[bool, list[str]]:
        """
        Delete user with proper cascade handling for owned organizations.

        Args:
            user_id: The user to delete
            orgs_to_delete: List of org IDs where user is sole member, choosing to delete

        Returns:
            Tuple of (success, list of error messages)

        Raises:
            ValueError: If validation fails (multi-member orgs not transferred, etc.)
        """
        # Import here to avoid circular imports
        from app.domain.organization_operations import organization_ops

        errors: list[str] = []

        # 1. Get fresh preview to validate current state
        preview = await self.get_deletion_preview(db, user_id)

        # 2. Validate: all multi-member orgs must have been transferred
        for org in preview.owned_orgs:
            if not org.is_sole_member:
                # Re-check current ownership - user should no longer be owner
                current_org = await organization_ops.get(db, org.org_id)
                if current_org and current_org.owner_id == user_id:
                    errors.append(
                        f"Must transfer ownership of '{org.org_name}' before deletion. "
                        f"This organization has {org.member_count - 1} other member(s)."
                    )

        # 3. Validate: all sole-member orgs must be in orgs_to_delete
        sole_member_org_ids = {org.org_id for org in preview.owned_orgs if org.is_sole_member}
        orgs_to_delete_set = set(orgs_to_delete)

        missing_orgs = sole_member_org_ids - orgs_to_delete_set
        if missing_orgs:
            # Find names for better error message
            missing_names = [
                org.org_name for org in preview.owned_orgs if org.org_id in missing_orgs
            ]
            errors.append(
                f"Must explicitly include sole-member organizations in deletion: {', '.join(missing_names)}"
            )

        # Extra orgs specified that aren't sole-member (shouldn't be deleted this way)
        extra_orgs = orgs_to_delete_set - sole_member_org_ids
        if extra_orgs:
            errors.append(
                "Cannot delete organizations with other members. "
                "Transfer ownership first or ensure all members leave."
            )

        if errors:
            raise ValueError("; ".join(errors))

        # 4. Delete sole-member organizations (CASCADE handles products, etc.)
        for org_id in orgs_to_delete:
            await organization_ops.delete(db, org_id)

        # 5. Delete user record (CASCADE handles preferences, memberships in other orgs, etc.)
        user = await self.get_by_id(db, user_id)
        if not user:
            raise ValueError("User not found")

        await db.delete(user)
        await db.flush()

        # 6. Delete Supabase auth record (non-blocking, best-effort)
        await self._delete_supabase_auth_user(user_id)

        return True, []

    async def _delete_supabase_auth_user(self, user_id: uuid_pkg.UUID) -> bool:
        """
        Delete user from Supabase auth.users table.

        Uses Supabase Admin API with service_role key to delete the
        authentication record. This is a best-effort operation — if it
        fails, the app-level deletion still succeeds (the auth record
        becomes orphaned but harmless).

        Args:
            user_id: The user's UUID (same as auth.users.id)

        Returns:
            True if deleted successfully, False if failed (logged but not raised)
        """
        try:
            from app.services.supabase import get_supabase_admin_client

            supabase = get_supabase_admin_client()

            # Run in thread pool since supabase-py is synchronous
            await asyncio.to_thread(
                supabase.auth.admin.delete_user,
                str(user_id),
            )

            logger.info(f"Deleted Supabase auth record for user {user_id}")
            return True

        except ValueError as e:
            # Service role key not configured — log and continue
            logger.warning(f"Supabase service role key not configured: {e}")
            return False

        except Exception as e:
            # Log error but don't fail the deletion
            # The user is already deleted from our database
            error_msg = str(e).lower()

            if "user not found" in error_msg or "not found" in error_msg:
                # User doesn't exist in Supabase — that's fine
                logger.info(f"Supabase auth record already deleted for user {user_id}")
                return True

            logger.error(
                f"Failed to delete Supabase auth record for user {user_id}: {e}",
                exc_info=True,
            )
            return False


user_ops = UserOperations()
