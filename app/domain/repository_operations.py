import uuid as uuid_pkg

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.base_operations import BaseOperations
from app.models.repository import Repository


class RepositoryOperations(BaseOperations[Repository]):
    """CRUD operations for Repository model."""

    def __init__(self):
        super().__init__(Repository)

    async def get_by_product(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
        product_id: uuid_pkg.UUID | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Repository]:
        """Get repositories with optional filtering by product."""
        statement = select(Repository).where(Repository.user_id == user_id)

        if product_id:
            statement = statement.where(Repository.product_id == product_id)

        statement = (
            statement.order_by(Repository.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_by_github_id(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
        github_id: int,
    ) -> Repository | None:
        """Find a repository by GitHub ID."""
        statement = select(Repository).where(
            Repository.user_id == user_id,
            Repository.github_id == github_id,
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def get_github_repos_by_product(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
        product_id: uuid_pkg.UUID,
    ) -> list[Repository]:
        """Get all GitHub-linked repositories for a product."""
        statement = (
            select(Repository)
            .where(
                Repository.user_id == user_id,
                Repository.product_id == product_id,
                Repository.github_id.isnot(None),
            )
            .order_by(Repository.created_at.desc())
        )
        result = await db.execute(statement)
        return list(result.scalars().all())


repository_ops = RepositoryOperations()
