"""Domain operations for org-scoped email digest preferences."""

import uuid as uuid_pkg
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org_digest_preference import OrgDigestPreference


class OrgDigestPreferenceOperations:
    """
    CRUD for per-org digest preferences.

    Each (user_id, organization_id) pair has at most one row.
    """

    def __init__(self) -> None:
        self.model = OrgDigestPreference

    async def get_by_user_and_org(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
        organization_id: uuid_pkg.UUID,
    ) -> OrgDigestPreference | None:
        """Get the digest preference for a specific user + org."""
        stmt = select(OrgDigestPreference).where(
            and_(
                OrgDigestPreference.user_id == user_id,  # type: ignore[arg-type]
                OrgDigestPreference.organization_id == organization_id,  # type: ignore[arg-type]
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
        organization_id: uuid_pkg.UUID,
    ) -> OrgDigestPreference:
        """Get existing preference or create with defaults (digest disabled)."""
        pref = await self.get_by_user_and_org(db, user_id, organization_id)
        if pref:
            return pref

        pref = OrgDigestPreference(user_id=user_id, organization_id=organization_id)
        db.add(pref)
        await db.flush()
        await db.refresh(pref)
        return pref

    async def get_all_for_user(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
    ) -> list[OrgDigestPreference]:
        """Get all org digest preferences for a user."""
        stmt = select(OrgDigestPreference).where(
            OrgDigestPreference.user_id == user_id  # type: ignore[arg-type]
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_all_active_for_frequency(
        self,
        db: AsyncSession,
        frequency: str,
    ) -> list[OrgDigestPreference]:
        """Get all preferences with the given frequency (for the digest job).

        Returns all rows where email_digest matches the requested frequency,
        across all users and orgs.
        """
        stmt = select(OrgDigestPreference).where(
            OrgDigestPreference.email_digest == frequency  # type: ignore[arg-type]
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        db: AsyncSession,
        pref: OrgDigestPreference,
        updates: dict[str, Any],
    ) -> OrgDigestPreference:
        """Update an existing org digest preference."""
        allowed_fields = {
            "email_digest",
            "digest_product_ids",
            "digest_timezone",
            "digest_hour",
        }
        for field, value in updates.items():
            if field in allowed_fields:
                setattr(pref, field, value)
        pref.updated_at = datetime.now(UTC)
        db.add(pref)
        await db.flush()
        await db.refresh(pref)
        return pref

    async def upsert_from_migration(
        self,
        db: AsyncSession,
        user_id: uuid_pkg.UUID,
        organization_id: uuid_pkg.UUID,
        email_digest: str,
        digest_product_ids: list[str] | None,
        digest_timezone: str,
        digest_hour: int,
    ) -> OrgDigestPreference:
        """Atomic upsert used by the data migration to copy global prefs into per-org rows."""
        now = datetime.now(UTC)
        stmt = (
            insert(self.model)
            .values(
                user_id=user_id,
                organization_id=organization_id,
                email_digest=email_digest,
                digest_product_ids=digest_product_ids,
                digest_timezone=digest_timezone,
                digest_hour=digest_hour,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "organization_id"],
                set_={
                    "email_digest": email_digest,
                    "digest_product_ids": digest_product_ids,
                    "digest_timezone": digest_timezone,
                    "digest_hour": digest_hour,
                    "updated_at": now,
                },
            )
            .returning(OrgDigestPreference)
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.scalar_one()

    async def delete(
        self,
        db: AsyncSession,
        pref: OrgDigestPreference,
    ) -> None:
        """Delete an org digest preference."""
        await db.delete(pref)
        await db.flush()


org_digest_preference_ops = OrgDigestPreferenceOperations()
