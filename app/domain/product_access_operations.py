"""Domain operations for ProductAccess model - per-user, project-scoped access control."""

import uuid as uuid_pkg

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.organization import MemberRole
from app.models.product_access import ProductAccess, ProductAccessLevel


class ProductAccessOperations:
    """Operations for managing product access control."""

    async def get_user_access_level(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
    ) -> str | None:
        """
        Get user's explicit access level for a product.

        Returns: 'admin', 'editor', 'viewer', 'none', or None (no explicit access).
        """
        statement = select(ProductAccess).where(
            ProductAccess.product_id == product_id,  # type: ignore[arg-type]
            ProductAccess.user_id == user_id,  # type: ignore[arg-type]
        )
        result = await db.execute(statement)
        access = result.scalar_one_or_none()

        if access:
            return access.access_level

        return None

    async def get_effective_access(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
        org_role: str,
    ) -> str:
        """
        Get user's effective access level, considering org role defaults.

        Args:
            db: Database session
            product_id: The product to check access for
            user_id: The user to check
            org_role: The user's role in the organization (owner, admin, member, viewer)

        Returns:
            Effective access level: 'admin', 'editor', 'viewer', or 'none'
        """
        # Owners and admins always have admin access to all products
        if org_role in (MemberRole.OWNER.value, MemberRole.ADMIN.value):
            return ProductAccessLevel.ADMIN.value

        # Check for explicit product access
        explicit_access = await self.get_user_access_level(db, product_id, user_id)
        if explicit_access:
            return explicit_access

        # No explicit access for members/viewers = no access
        return ProductAccessLevel.NONE.value

    async def get_product_collaborators(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
    ) -> list[ProductAccess]:
        """Get all collaborators with explicit access to a product."""
        statement = (
            select(ProductAccess)
            .where(
                ProductAccess.product_id == product_id,  # type: ignore[arg-type]
                ProductAccess.access_level != ProductAccessLevel.NONE.value,  # type: ignore[arg-type]
            )
            .order_by(ProductAccess.created_at.desc())  # type: ignore[attr-defined]
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_product_collaborators_with_users(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
    ) -> list[ProductAccess]:
        """
        Get all collaborators for a product with user details.

        Returns ProductAccess records with the user relationship loaded.
        """
        statement = (
            select(ProductAccess)
            .options(selectinload(ProductAccess.user))  # type: ignore[arg-type]
            .where(
                ProductAccess.product_id == product_id,  # type: ignore[arg-type]
                ProductAccess.access_level != ProductAccessLevel.NONE.value,  # type: ignore[arg-type]
            )
            .order_by(ProductAccess.created_at.desc())  # type: ignore[attr-defined]
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_product_collaborators_count(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
    ) -> int:
        """Count collaborators with explicit access to a product."""
        statement = select(func.count(ProductAccess.id)).where(  # type: ignore[arg-type]
            ProductAccess.product_id == product_id,  # type: ignore[arg-type]
            ProductAccess.access_level != ProductAccessLevel.NONE.value,  # type: ignore[arg-type]
        )
        result = await db.execute(statement)
        return result.scalar() or 0

    async def set_access(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
        access_level: str,
    ) -> ProductAccess:
        """
        Set or update user's access to a product.

        Creates a new record if none exists, updates existing otherwise.
        """
        statement = select(ProductAccess).where(
            ProductAccess.product_id == product_id,  # type: ignore[arg-type]
            ProductAccess.user_id == user_id,  # type: ignore[arg-type]
        )
        result = await db.execute(statement)
        existing = result.scalar_one_or_none()

        if existing:
            existing.access_level = access_level
            db.add(existing)
        else:
            existing = ProductAccess(
                product_id=product_id,
                user_id=user_id,
                access_level=access_level,
            )
            db.add(existing)

        await db.flush()
        await db.refresh(existing)
        return existing

    async def remove_access(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
    ) -> bool:
        """
        Remove user's explicit access to a product.

        Returns True if access was removed, False if no access existed.
        """
        statement = select(ProductAccess).where(
            ProductAccess.product_id == product_id,  # type: ignore[arg-type]
            ProductAccess.user_id == user_id,  # type: ignore[arg-type]
        )
        result = await db.execute(statement)
        access = result.scalar_one_or_none()

        if access:
            await db.delete(access)
            await db.flush()
            return True
        return False

    async def user_can_access_product(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
        org_role: str,
    ) -> bool:
        """Check if user can see this product at all."""
        access = await self.get_effective_access(db, product_id, user_id, org_role)
        return access in (
            ProductAccessLevel.ADMIN.value,
            ProductAccessLevel.EDITOR.value,
            ProductAccessLevel.VIEWER.value,
        )

    async def user_can_edit_product(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
        org_role: str,
    ) -> bool:
        """Check if user can edit this product (admin or editor)."""
        access = await self.get_effective_access(db, product_id, user_id, org_role)
        return access in (ProductAccessLevel.ADMIN.value, ProductAccessLevel.EDITOR.value)

    async def user_can_access_variables(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
        org_role: str,
    ) -> bool:
        """Check if user can access Variables tab (admin or editor only)."""
        access = await self.get_effective_access(db, product_id, user_id, org_role)
        return access in (ProductAccessLevel.ADMIN.value, ProductAccessLevel.EDITOR.value)

    async def user_is_product_admin(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
        org_role: str,
    ) -> bool:
        """Check if user has admin access to this product."""
        access = await self.get_effective_access(db, product_id, user_id, org_role)
        return access == ProductAccessLevel.ADMIN.value

    async def get_user_access_for_org_products(
        self,
        db: AsyncSession,
        org_id: uuid_pkg.UUID,
        user_id: uuid_pkg.UUID,
    ) -> dict[uuid_pkg.UUID, str]:
        """
        Get all explicit product access for a user within an organization.

        Returns a dict mapping product_id -> access_level for all products
        where the user has explicit access.
        """
        from app.models.product import Product

        statement = (
            select(ProductAccess)
            .join(Product, ProductAccess.product_id == Product.id)  # type: ignore[arg-type]
            .where(
                Product.organization_id == org_id,  # type: ignore[arg-type]
                ProductAccess.user_id == user_id,  # type: ignore[arg-type]
            )
        )
        result = await db.execute(statement)
        access_records = result.scalars().all()

        return {record.product_id: record.access_level for record in access_records}


product_access_ops = ProductAccessOperations()
