"""Org-scoped email digest preference endpoints."""

import uuid as uuid_pkg

from fastapi import Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_with_rls
from app.api.v1.organizations.helpers import require_org_access
from app.domain import org_digest_preference_ops, organization_ops
from app.models.user import User

# --- Schemas ---


class OrgDigestPreferenceRead(BaseModel):
    """Response for a single org's digest preference."""

    organization_id: str
    email_digest: str  # "none" | "daily" | "weekly"
    digest_product_ids: list[str] | None = None
    digest_timezone: str
    digest_hour: int

    class Config:
        from_attributes = True


class OrgDigestPreferenceUpdate(BaseModel):
    """Request body for updating digest preferences."""

    email_digest: str | None = None
    digest_product_ids: list[str] | None = None
    digest_timezone: str | None = None
    digest_hour: int | None = None


# --- Helpers ---


def _to_response(pref) -> OrgDigestPreferenceRead:  # type: ignore[no-untyped-def]
    return OrgDigestPreferenceRead(
        organization_id=str(pref.organization_id),
        email_digest=pref.email_digest,
        digest_product_ids=pref.digest_product_ids,
        digest_timezone=pref.digest_timezone,
        digest_hour=pref.digest_hour,
    )


# --- Endpoints ---


async def get_digest_preferences(
    org_id: uuid_pkg.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> OrgDigestPreferenceRead:
    """
    Get the current user's digest preferences for this organization.

    Returns defaults (digest disabled) if no preference exists yet.
    Requires membership in the organization.
    """
    org = await organization_ops.get(db, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    await require_org_access(db, org_id, user)

    pref = await org_digest_preference_ops.get_or_create(db, user.id, org_id)
    await db.commit()
    return _to_response(pref)


async def update_digest_preferences(
    org_id: uuid_pkg.UUID,
    data: OrgDigestPreferenceUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> OrgDigestPreferenceRead:
    """
    Update the current user's digest preferences for this organization.

    Requires membership in the organization.
    """
    org = await organization_ops.get(db, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    await require_org_access(db, org_id, user)

    pref = await org_digest_preference_ops.get_or_create(db, user.id, org_id)

    updates = data.model_dump(exclude_unset=True)

    # Validate enum values
    if "email_digest" in updates and updates["email_digest"] not in (
        "none",
        "daily",
        "weekly",
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="email_digest must be 'none', 'daily', or 'weekly'",
        )

    if "digest_timezone" in updates:
        from zoneinfo import available_timezones

        if updates["digest_timezone"] not in available_timezones():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid IANA timezone",
            )

    if "digest_hour" in updates and not (0 <= updates["digest_hour"] <= 23):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="digest_hour must be between 0 and 23",
        )

    if updates:
        pref = await org_digest_preference_ops.update(db, pref, updates)

    await db.commit()
    return _to_response(pref)
