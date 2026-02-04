"""Organization settings endpoints."""

import uuid as uuid_pkg

from fastapi import Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_with_rls
from app.api.v1.organizations.helpers import require_org_access
from app.domain import organization_ops
from app.models.organization import MemberRole
from app.models.user import User


class OrgSettingsResponse(BaseModel):
    """Organization settings response."""

    auto_progress_enabled: bool


class OrgSettingsUpdate(BaseModel):
    """Request body for updating organization settings."""

    auto_progress_enabled: bool | None = None


async def get_settings(
    org_id: uuid_pkg.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> OrgSettingsResponse:
    """
    Get organization settings.

    Requires membership in the organization.
    """
    org = await organization_ops.get(db, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    await require_org_access(db, org_id, user)

    auto_progress = await organization_ops.get_auto_progress_enabled(db, org_id)

    return OrgSettingsResponse(auto_progress_enabled=auto_progress)


async def update_settings(
    org_id: uuid_pkg.UUID,
    data: OrgSettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> OrgSettingsResponse:
    """
    Update organization settings.

    Requires admin or owner role.
    """
    org = await organization_ops.get(db, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    await require_org_access(db, org_id, user, min_role=MemberRole.ADMIN)

    if data.auto_progress_enabled is not None:
        await organization_ops.set_auto_progress_enabled(db, org_id, data.auto_progress_enabled)

    await db.commit()

    auto_progress = await organization_ops.get_auto_progress_enabled(db, org_id)

    return OrgSettingsResponse(auto_progress_enabled=auto_progress)
