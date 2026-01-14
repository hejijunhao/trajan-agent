import uuid as uuid_pkg

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.base_operations import BaseOperations
from app.models.app_info import AppInfo, AppInfoBulkEntry


class AppInfoOperations(BaseOperations[AppInfo]):
    """CRUD operations for AppInfo model."""

    def __init__(self) -> None:
        super().__init__(AppInfo)

    async def get_by_product_for_org(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> list[AppInfo]:
        """
        Get app info entries for a product (org-level access).

        Does NOT filter by user_id - used for quick access where any org member
        can view entries created by any other org member.
        """
        statement = (
            select(AppInfo)
            .where(AppInfo.product_id == product_id)  # type: ignore[arg-type]
            .order_by(AppInfo.created_at.desc())  # type: ignore[attr-defined]
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_by_id_for_product(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        entry_id: uuid_pkg.UUID,
    ) -> AppInfo | None:
        """
        Get a single app info entry by ID within a product (org-level access).

        Does NOT filter by user_id - used for quick access reveal.
        """
        statement = select(AppInfo).where(
            AppInfo.id == entry_id,  # type: ignore[arg-type]
            AppInfo.product_id == product_id,  # type: ignore[arg-type]
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

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
            AppInfo.user_id == user_id,  # type: ignore[arg-type]
            AppInfo.product_id == product_id,  # type: ignore[arg-type]
        )

        if category:
            statement = statement.where(AppInfo.category == category)  # type: ignore[arg-type]

        statement = (
            statement.order_by(AppInfo.created_at.desc())  # type: ignore[attr-defined]
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
            AppInfo.user_id == user_id,  # type: ignore[arg-type]
            AppInfo.product_id == product_id,  # type: ignore[arg-type]
            AppInfo.key == key,  # type: ignore[arg-type]
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def get_existing_keys(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
        product_id: uuid_pkg.UUID,
        keys: list[str],
    ) -> set[str]:
        """Get set of keys that already exist for a product."""
        statement = select(AppInfo.key).where(  # type: ignore[call-overload]
            AppInfo.user_id == user_id,
            AppInfo.product_id == product_id,
            AppInfo.key.in_(keys),  # type: ignore[union-attr]
        )
        result = await db.execute(statement)
        return set(result.scalars().all())

    async def bulk_create(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
        product_id: uuid_pkg.UUID,
        entries: list[AppInfoBulkEntry],
    ) -> tuple[list[AppInfo], list[str]]:
        """
        Create multiple app info entries, skipping duplicates.

        Returns:
            Tuple of (created entries, skipped keys)
        """
        if not entries:
            return [], []

        # Get existing keys to skip duplicates
        incoming_keys = [e.key for e in entries]
        existing_keys = await self.get_existing_keys(db, user_id, product_id, incoming_keys)

        # Also handle duplicates within the incoming batch (take last occurrence)
        seen_keys: dict[str, AppInfoBulkEntry] = {}
        for entry in entries:
            seen_keys[entry.key] = entry

        created: list[AppInfo] = []
        skipped: list[str] = []

        for key, entry in seen_keys.items():
            if key in existing_keys:
                skipped.append(key)
                continue

            db_obj = AppInfo(
                user_id=user_id,
                product_id=product_id,
                key=entry.key,
                value=entry.value,
                category=entry.category,
                is_secret=entry.is_secret,
                description=entry.description,
                target_file=entry.target_file,
            )
            db.add(db_obj)
            created.append(db_obj)

        if created:
            await db.flush()
            for obj in created:
                await db.refresh(obj)

        return created, skipped


app_info_ops = AppInfoOperations()
