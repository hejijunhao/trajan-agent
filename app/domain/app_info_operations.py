import uuid as uuid_pkg

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.base_operations import BaseOperations
from app.models.app_info import AppInfo


class AppInfoOperations(BaseOperations[AppInfo]):
    """CRUD operations for AppInfo model."""

    def __init__(self):
        super().__init__(AppInfo)

    async def get_by_product(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
        product_id: uuid_pkg.UUID,
        category: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[AppInfo]:
        """Get app info entries for a product."""
        statement = select(AppInfo).where(
            AppInfo.user_id == user_id,
            AppInfo.product_id == product_id,
        )

        if category:
            statement = statement.where(AppInfo.category == category)

        statement = (
            statement.order_by(AppInfo.created_at.desc())
            .offset(skip)
            .limit(limit)
        )

        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_by_key(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
        product_id: uuid_pkg.UUID,
        key: str,
    ) -> AppInfo | None:
        """Get a specific app info entry by key."""
        statement = select(AppInfo).where(
            AppInfo.user_id == user_id,
            AppInfo.product_id == product_id,
            AppInfo.key == key,
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()


app_info_ops = AppInfoOperations()
