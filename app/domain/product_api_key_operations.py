"""Domain operations for product API keys."""

import hashlib
import secrets
import time
import uuid as uuid_pkg
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.base_operations import BaseOperations
from app.models.product_api_key import ProductApiKey

# In-memory cache: key_hash -> last write timestamp (monotonic seconds).
# Used to debounce last_used_at updates — only write if >60s since last update.
_last_used_write_cache: dict[str, float] = {}
_LAST_USED_DEBOUNCE_SECONDS = 60


class ProductApiKeyOperations(BaseOperations[ProductApiKey]):
    """CRUD operations for ProductApiKey model."""

    def __init__(self) -> None:
        super().__init__(ProductApiKey)

    async def create_key(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
        name: str,
        scopes: list[str],
        created_by_user_id: uuid_pkg.UUID,
    ) -> tuple[ProductApiKey, str]:
        """Create a new API key.

        Generates a random key prefixed with ``trj_pk_``, stores its
        SHA-256 hash, and returns the database record alongside the raw
        key (which is never persisted).
        """
        raw_key = "trj_pk_" + secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_prefix = raw_key[:16]

        db_obj = ProductApiKey(
            product_id=product_id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            name=name,
            scopes=scopes,
            created_by_user_id=created_by_user_id,
        )
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj, raw_key

    async def list_by_product(
        self,
        db: AsyncSession,
        product_id: uuid_pkg.UUID,
    ) -> list[ProductApiKey]:
        """List active (non-revoked) API keys for a product."""
        statement = (
            select(ProductApiKey)
            .where(
                ProductApiKey.product_id == product_id,  # type: ignore[arg-type]
                ProductApiKey.revoked_at.is_(None),  # type: ignore[union-attr]
            )
            .order_by(ProductApiKey.created_at.desc())  # type: ignore[attr-defined]
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def revoke(
        self,
        db: AsyncSession,
        db_obj: ProductApiKey,
    ) -> ProductApiKey:
        """Soft-delete an API key by setting revoked_at."""
        db_obj.revoked_at = datetime.now(UTC)
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj

    async def validate_key(
        self,
        db: AsyncSession,
        raw_key: str,
    ) -> ProductApiKey | None:
        """Validate a raw API key and update last_used_at.

        Returns the ProductApiKey if valid and not revoked, otherwise None.
        """
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        statement = select(ProductApiKey).where(
            ProductApiKey.key_hash == key_hash,  # type: ignore[arg-type]
            ProductApiKey.revoked_at.is_(None),  # type: ignore[union-attr]
        )
        result = await db.execute(statement)
        api_key = result.scalar_one_or_none()
        if api_key is None:
            return None

        # Debounce last_used_at writes — only flush to DB if >60s since last update.
        now_mono = time.monotonic()
        last_write = _last_used_write_cache.get(key_hash, 0.0)
        if now_mono - last_write > _LAST_USED_DEBOUNCE_SECONDS:
            api_key.last_used_at = datetime.now(UTC)
            db.add(api_key)
            await db.flush()
            _last_used_write_cache[key_hash] = now_mono

        return api_key

    @staticmethod
    def check_scope(api_key: ProductApiKey, required_scope: str) -> bool:
        """Check whether an API key has the required scope."""
        return required_scope in api_key.scopes


# Singleton instance
api_key_ops = ProductApiKeyOperations()
