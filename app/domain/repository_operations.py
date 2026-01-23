"""Repository operations with product-scoped visibility.

Repositories are visible to all users with Product access (via RLS).
The `imported_by_user_id` field tracks who imported the repo (for audit/token lookup)
but does NOT control visibility.
"""

import uuid as uuid_pkg

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.repository import Repository


class RepositoryOperations:
    """CRUD operations for Repository model.

    Unlike user-owned resources, repositories use Product-based access control.
    RLS policies enforce visibility based on Product access level.
    """

    def __init__(self):
        self.model = Repository

    async def get(self, db: AsyncSession, id: uuid_pkg.UUID) -> Repository | None:
        """Get a repository by ID. RLS enforces product access."""
        statement = select(Repository).where(Repository.id == id)
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def count_by_org(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
    ) -> int:
        """Count all repositories belonging to an organization (via products)."""
        statement = (
            select(func.count(Repository.id))
            .join(Product, Repository.product_id == Product.id)
            .where(Product.organization_id == organization_id)
        )
        result = await db.execute(statement)
        return result.scalar() or 0

    async def get_by_org(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Repository]:
        """Get all repositories belonging to an organization (via products)."""
        statement = (
            select(Repository)
            .join(Product, Repository.product_id == Product.id)
            .where(Product.organization_id == organization_id)
            .order_by(Repository.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_by_product(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Repository]:
        """Get repositories for a product. RLS enforces access control."""
        statement = (
            select(Repository)
            .where(Repository.product_id == product_id)
            .order_by(Repository.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_by_github_id(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        github_id: int,
    ) -> Repository | None:
        """Find a repository by GitHub ID within a product."""
        statement = select(Repository).where(
            Repository.product_id == product_id,
            Repository.github_id == github_id,
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def find_by_github_id(
        self,
        db: AsyncSession,
        github_id: int,
    ) -> Repository | None:
        """Find any repository with this GitHub ID (across all accessible products).

        RLS enforces product access - only returns if user can see the product.
        Useful for checking if a repo is already imported somewhere.
        """
        statement = select(Repository).where(Repository.github_id == github_id).limit(1)
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def get_github_repos_by_product(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
    ) -> list[Repository]:
        """Get all GitHub-linked repositories for a product."""
        statement = (
            select(Repository)
            .where(
                Repository.product_id == product_id,
                Repository.github_id.isnot(None),
            )
            .order_by(Repository.created_at.desc())
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def create(
        self,
        db: AsyncSession,
        obj_in: dict,
        imported_by_user_id: uuid_pkg.UUID,
    ) -> Repository:
        """Create a new repository.

        Args:
            db: Database session
            obj_in: Repository data (name, url, product_id, etc.)
            imported_by_user_id: User who is importing this repository
        """
        db_obj = Repository(**obj_in, imported_by_user_id=imported_by_user_id)
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj

    async def update(
        self,
        db: AsyncSession,
        db_obj: Repository,
        obj_in: dict,
    ) -> Repository:
        """Update an existing repository."""
        for field, value in obj_in.items():
            if value is not None:
                setattr(db_obj, field, value)
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj

    async def delete(self, db: AsyncSession, id: uuid_pkg.UUID) -> bool:
        """Delete a repository by ID. Caller must verify product access."""
        db_obj = await self.get(db, id)
        if db_obj:
            await db.delete(db_obj)
            await db.flush()
            return True
        return False

    async def get_by_full_name(
        self,
        db: AsyncSession,
        full_name: str,
    ) -> Repository | None:
        """Find a repository by its full_name (owner/repo format).

        RLS enforces product access - only returns if user can see the product.
        """
        statement = select(Repository).where(Repository.full_name == full_name).limit(1)
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def update_full_name(
        self,
        db: AsyncSession,
        repo_id: uuid_pkg.UUID,
        new_full_name: str,
    ) -> Repository | None:
        """Update repository full_name after GitHub rename/transfer.

        This is called when GitHub returns a 301 redirect indicating the
        repository was renamed or transferred to a new owner.

        Args:
            db: Database session
            repo_id: Repository ID to update
            new_full_name: New full name in "owner/repo" format

        Returns:
            Updated Repository or None if not found
        """
        repo = await self.get(db, repo_id)
        if not repo:
            return None

        # Extract new name from full_name
        new_name = new_full_name.split("/")[-1] if "/" in new_full_name else new_full_name

        repo.full_name = new_full_name
        repo.name = new_name
        db.add(repo)
        await db.flush()
        await db.refresh(repo)
        return repo


repository_ops = RepositoryOperations()
