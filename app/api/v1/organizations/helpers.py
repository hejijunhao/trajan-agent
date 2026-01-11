"""Shared helpers for organization endpoints."""

import uuid as uuid_pkg

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import ROLE_HIERARCHY
from app.domain import organization_ops
from app.models.organization import MemberRole
from app.models.user import User


async def require_org_access(
    db: AsyncSession,
    org_id: uuid_pkg.UUID,
    user: User,
    min_role: MemberRole | None = None,
) -> str:
    """
    Check if user has access to the organization.

    Returns the user's role if authorized, raises HTTPException otherwise.
    """
    role = await organization_ops.get_member_role(db, org_id, user.id)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this organization",
        )

    if min_role and ROLE_HIERARCHY.get(role, 0) < ROLE_HIERARCHY.get(min_role.value, 0):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires {min_role.value} role or higher",
        )

    return role
