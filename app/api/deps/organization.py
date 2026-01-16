"""Organization access control dependencies."""

import uuid as uuid_pkg

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domain.organization_operations import organization_ops
from app.models.organization import MemberRole, Organization
from app.models.user import User

from .auth import get_current_user


async def get_current_organization(
    org_id: uuid_pkg.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    """
    Get the current organization context.

    Resolution order:
    1. If org_id is provided (query param), use that org (must be a member)
    2. Otherwise, use the user's first/default organization

    Raises 403 if user is not a member of the requested organization.
    Raises 404 if no organization found.
    """
    if org_id:
        # Check if user is a member of the specified organization
        is_member = await organization_ops.is_member(db, org_id, current_user.id)
        if not is_member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a member of this organization",
            )
        org = await organization_ops.get(db, org_id)
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found",
            )
        return org

    # Default to user's first organization (personal workspace)
    orgs = await organization_ops.get_for_user(db, current_user.id)
    if not orgs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No organization found for user",
        )

    return orgs[0]


async def require_org_admin(
    current_user: User = Depends(get_current_user),
    current_org: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    """
    Require the current user to be an admin or owner of the current organization.

    Returns the organization if authorized, raises 403 otherwise.
    """
    role = await organization_ops.get_member_role(db, current_org.id, current_user.id)
    if role not in (MemberRole.OWNER.value, MemberRole.ADMIN.value):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or owner access required",
        )
    return current_org


async def require_org_owner(
    current_user: User = Depends(get_current_user),
    current_org: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    """
    Require the current user to be an owner of the current organization.

    Returns the organization if authorized, raises 403 otherwise.
    """
    role = await organization_ops.get_member_role(db, current_org.id, current_user.id)
    if role != MemberRole.OWNER.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner access required",
        )
    return current_org


async def require_system_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Require the current user to be a system admin.

    Returns the user if authorized, raises 403 otherwise.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System admin access required",
        )
    return current_user
