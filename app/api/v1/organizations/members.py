"""Organization member management endpoints."""

import uuid as uuid_pkg
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_with_rls
from app.api.v1.organizations.helpers import require_org_access
from app.api.v1.organizations.schemas import MemberResponse
from app.core.roles import ROLE_HIERARCHY
from app.domain import org_member_ops, organization_ops
from app.domain.org_member_operations import InvalidEmailError, SupabaseInviteError
from app.models.organization import (
    MemberRole,
    OrganizationMemberCreate,
    OrganizationMemberUpdate,
)
from app.models.user import User


async def list_members(
    org_id: uuid_pkg.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> list[MemberResponse]:
    """
    List all members of an organization.

    Requires membership in the organization.
    """
    org = await organization_ops.get(db, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    await require_org_access(db, org_id, user)

    members = await org_member_ops.get_by_org(db, org_id)

    return [
        MemberResponse(
            id=str(m.id),
            user_id=str(m.user_id),
            email=m.user.email if m.user else "",
            display_name=m.user.display_name if m.user else None,
            avatar_url=m.user.avatar_url if m.user else None,
            role=m.role,
            joined_at=m.joined_at.isoformat(),
            invited_by=str(m.invited_by) if m.invited_by else None,
            invited_at=m.invited_at.isoformat() if m.invited_at else None,
            has_signed_in=m.user.onboarding_completed_at is not None if m.user else False,
        )
        for m in members
    ]


async def add_member(
    org_id: uuid_pkg.UUID,
    data: OrganizationMemberCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> MemberResponse:
    """
    Add a member to an organization.

    Requires admin or owner role. The user must already have an account.
    """
    org = await organization_ops.get(db, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    caller_role = await require_org_access(db, org_id, user, min_role=MemberRole.ADMIN)

    # Admins can only assign member/viewer roles
    if caller_role == MemberRole.ADMIN.value and ROLE_HIERARCHY.get(
        data.role, 0
    ) >= ROLE_HIERARCHY.get(MemberRole.ADMIN.value, 0):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins can only assign member or viewer roles",
        )

    # Find user by email, or create via Supabase invite if not found
    target_user = await org_member_ops.find_user_by_email(db, data.email)
    if not target_user:
        try:
            # Create user via Supabase Admin API (sends invite email automatically)
            target_user = await org_member_ops.create_user_via_supabase(db, data.email)
        except InvalidEmailError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid email address format",
            ) from e
        except SupabaseInviteError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(e),
            ) from e

    # Check if already a member
    existing = await org_member_ops.get_by_org_and_user(db, org_id, target_user.id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this organization",
        )

    # Add member
    member = await org_member_ops.add_member(
        db,
        organization_id=org_id,
        user_id=target_user.id,
        role=data.role,
        invited_by=user.id,
    )
    await db.commit()
    await db.refresh(member)

    return MemberResponse(
        id=str(member.id),
        user_id=str(member.user_id),
        email=target_user.email,
        display_name=target_user.display_name,
        avatar_url=target_user.avatar_url,
        role=member.role,
        joined_at=member.joined_at.isoformat(),
        invited_by=str(member.invited_by) if member.invited_by else None,
        invited_at=member.invited_at.isoformat() if member.invited_at else None,
        has_signed_in=target_user.onboarding_completed_at is not None,
    )


async def update_member_role(
    org_id: uuid_pkg.UUID,
    member_id: uuid_pkg.UUID,
    data: OrganizationMemberUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> MemberResponse:
    """
    Update a member's role.

    Requires admin (for member/viewer roles) or owner (for admin/owner roles).
    """
    org = await organization_ops.get(db, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    caller_role = await require_org_access(db, org_id, user, min_role=MemberRole.ADMIN)

    # Get the membership
    member = await org_member_ops.get(db, member_id)
    if not member or member.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )

    # Can't change own role
    if member.user_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own role",
        )

    # Admins can only change member/viewer roles
    if caller_role == MemberRole.ADMIN.value:
        if ROLE_HIERARCHY.get(member.role, 0) >= ROLE_HIERARCHY.get(MemberRole.ADMIN.value, 0):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only owners can change admin or owner roles",
            )
        if ROLE_HIERARCHY.get(data.role, 0) >= ROLE_HIERARCHY.get(MemberRole.ADMIN.value, 0):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admins can only assign member or viewer roles",
            )

    # Changing to/from owner requires owner role
    if (
        data.role == MemberRole.OWNER.value or member.role == MemberRole.OWNER.value
    ) and caller_role != MemberRole.OWNER.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owners can assign or revoke owner role",
        )

    # Prevent removing last owner
    if member.role == MemberRole.OWNER.value and data.role != MemberRole.OWNER.value:
        is_only_owner = await org_member_ops.is_only_owner(db, org_id, member.user_id)
        if is_only_owner:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the only owner. Transfer ownership first.",
            )

    # Update role
    member.role = data.role
    db.add(member)
    await db.commit()
    await db.refresh(member, ["user"])

    return MemberResponse(
        id=str(member.id),
        user_id=str(member.user_id),
        email=member.user.email if member.user else "",
        display_name=member.user.display_name if member.user else None,
        avatar_url=member.user.avatar_url if member.user else None,
        role=member.role,
        joined_at=member.joined_at.isoformat(),
        invited_by=str(member.invited_by) if member.invited_by else None,
        invited_at=member.invited_at.isoformat() if member.invited_at else None,
        has_signed_in=(member.user.onboarding_completed_at is not None if member.user else False),
    )


async def remove_member(
    org_id: uuid_pkg.UUID,
    member_id: uuid_pkg.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> None:
    """
    Remove a member from an organization.

    Members can remove themselves. Admins can remove member/viewer.
    Owners can remove anyone except the last owner.
    """
    org = await organization_ops.get(db, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    caller_role = await require_org_access(db, org_id, user)

    # Get the membership
    member = await org_member_ops.get(db, member_id)
    if not member or member.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )

    # Self-removal is always allowed
    is_self = member.user_id == user.id

    if not is_self:
        # Require at least admin to remove others
        if ROLE_HIERARCHY.get(caller_role, 0) < ROLE_HIERARCHY.get(MemberRole.ADMIN.value, 0):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins and owners can remove other members",
            )

        # Admins can only remove member/viewer
        if caller_role == MemberRole.ADMIN.value and ROLE_HIERARCHY.get(
            member.role, 0
        ) >= ROLE_HIERARCHY.get(MemberRole.ADMIN.value, 0):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only owners can remove admins or other owners",
            )

    # Prevent removing last owner
    if member.role == MemberRole.OWNER.value:
        is_only_owner = await org_member_ops.is_only_owner(db, org_id, member.user_id)
        if is_only_owner:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the only owner. Transfer ownership or delete the organization.",
            )

    await org_member_ops.remove_member(db, org_id, member.user_id)
    await db.commit()


async def resend_invite(
    org_id: uuid_pkg.UUID,
    member_id: uuid_pkg.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, str]:
    """
    Resend invite email to a pending organization member.

    Requires admin or owner role. Only works for members who haven't
    completed onboarding yet.
    """
    org = await organization_ops.get(db, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    await require_org_access(db, org_id, user, min_role=MemberRole.ADMIN)

    # Get the membership with user relationship
    member = await org_member_ops.get(db, member_id)
    if not member or member.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )

    # Refresh to ensure we have the user relationship loaded
    await db.refresh(member, ["user"])

    # Verify member is pending (hasn't completed onboarding)
    if member.user and member.user.onboarding_completed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has already joined and completed onboarding",
        )

    if not member.user or not member.user.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Member has no associated email address",
        )

    # Resend invite via Supabase
    try:
        await org_member_ops.resend_invite(member.user.email)
    except SupabaseInviteError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from e

    # Update invited_at timestamp to track last resend
    member.invited_at = datetime.now(UTC)
    db.add(member)
    await db.commit()

    return {"message": "Invite email resent successfully"}
