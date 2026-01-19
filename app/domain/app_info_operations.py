import uuid as uuid_pkg

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import token_encryption
from app.domain.base_operations import BaseOperations
from app.models.app_info import AppInfo, AppInfoBulkEntry


class AppInfoOperations(BaseOperations[AppInfo]):
    """CRUD operations for AppInfo model."""

    def __init__(self) -> None:
        super().__init__(AppInfo)

    def _encrypt_value(self, value: str, is_secret: bool) -> str:
        """Encrypt value if it's marked as a secret."""
        if is_secret and value:
            return token_encryption.encrypt(value)
        return value

    def _decrypt_value(self, value: str | None) -> str | None:
        """Decrypt value if it was encrypted."""
        if value:
            return token_encryption.decrypt(value)
        return value

    def decrypt_entry_value(self, entry: AppInfo) -> str | None:
        """Decrypt the value of an app info entry for reveal operations."""
        return self._decrypt_value(entry.value)

    async def create(
        self,
        db: AsyncSession,
        obj_in: dict[str, object],
        user_id: uuid_pkg.UUID,
    ) -> AppInfo:
        """Create a new app info entry with encryption for secrets."""
        # Encrypt value if marked as secret
        value = obj_in.get("value")
        if obj_in.get("is_secret") and value and isinstance(value, str):
            obj_in = dict(obj_in)  # Don't mutate the input
            obj_in["value"] = self._encrypt_value(value, True)

        db_obj = AppInfo(**obj_in, user_id=user_id)
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj

    async def update(
        self,
        db: AsyncSession,
        db_obj: AppInfo,
        obj_in: dict[str, object],
    ) -> AppInfo:
        """Update an app info entry with encryption handling.

        Encrypts the value if:
        - The entry is being changed to a secret (is_secret=True)
        - OR the entry is already a secret and value is being updated
        """
        # Determine if we need to encrypt the value
        is_secret_input = obj_in.get("is_secret")
        is_secret = is_secret_input if is_secret_input is not None else db_obj.is_secret
        value = obj_in.get("value")

        if value is not None and is_secret and isinstance(value, str):
            obj_in = dict(obj_in)  # Don't mutate the input
            obj_in["value"] = self._encrypt_value(value, True)

        for field, field_value in obj_in.items():
            if field_value is not None:
                setattr(db_obj, field, field_value)
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj

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

            # Encrypt value if marked as secret
            encrypted_value = self._encrypt_value(entry.value, entry.is_secret)

            db_obj = AppInfo(
                user_id=user_id,
                product_id=product_id,
                key=entry.key,
                value=encrypted_value,
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
