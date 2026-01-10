"""Organization API endpoints for user-facing organization management."""

import uuid as uuid_pkg
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config.plans import PLANS, get_plan
from app.core.database import get_db
from app.domain import org_member_ops, organization_ops, subscription_ops
from app.models.organization import (
    MemberRole,
    OrganizationCreate,
    OrganizationMemberCreate,
    OrganizationMemberUpdate,
    OrganizationUpdate,
)
from app.models.user import User

router = APIRouter(prefix="/organizations", tags=["organizations"])


# Response schemas
class OrganizationResponse(BaseModel):
    """Organization response with basic info."""

    id: str
    name: str
    slug: str
    owner_id: str
    created_at: str
    updated_at: str | None
    is_personal: bool  # True if user is owner and it's their first org
    role: str  # User's role in this org


class OrganizationDetailResponse(BaseModel):
    """Detailed organization response with members and subscription."""

    id: str
    name: str
    slug: str
    owner_id: str
    settings: dict[str, Any] | None
    created_at: str
    updated_at: str | None
    role: str  # User's role in this org
    member_count: int


class MemberResponse(BaseModel):
    """Organization member response."""

    id: str
    user_id: str
    email: str
    display_name: str | None
    avatar_url: str | None
    role: str
    joined_at: str
    invited_by: str | None
    invited_at: str | None


class SubscriptionResponse(BaseModel):
    """Subscription response for organization."""

    id: str
    plan_tier: str
    plan_display_name: str
    status: str
    base_repo_limit: int
    is_manually_assigned: bool
    created_at: str
    # Plan features
    features: dict[str, bool]
    analysis_frequency: str
    price_monthly: int
    allows_overages: bool
    overage_repo_price: int


class PlanResponse(BaseModel):
    """Plan information for frontend display."""

    tier: str
    display_name: str
    price_monthly: int
    base_repo_limit: int
    overage_repo_price: int
    allows_overages: bool
    features: dict[str, bool]
    analysis_frequency: str


# Helper functions
async def _require_org_access(
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

    if min_role:
        role_hierarchy = {
            MemberRole.VIEWER.value: 0,
            MemberRole.MEMBER.value: 1,
            MemberRole.ADMIN.value: 2,
            MemberRole.OWNER.value: 3,
        }
        if role_hierarchy.get(role, 0) < role_hierarchy.get(min_role.value, 0):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {min_role.value} role or higher",
            )

    return role


# Endpoints
@router.get("")
async def list_organizations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OrganizationResponse]:
    """
    List all organizations the user is a member of.

    Returns organizations ordered by creation date (newest first).
    """
    orgs = await organization_ops.get_for_user(db, user.id)

    result = []
    for org in orgs:
        role = await organization_ops.get_member_role(db, org.id, user.id)
        result.append(
            OrganizationResponse(
                id=str(org.id),
                name=org.name,
                slug=org.slug,
                owner_id=str(org.owner_id),
                created_at=org.created_at.isoformat(),
                updated_at=org.updated_at.isoformat() if org.updated_at else None,
                is_personal=org.owner_id == user.id,
                role=role or MemberRole.MEMBER.value,
            )
        )

    return result


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_organization(
    data: OrganizationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrganizationResponse:
    """
    Create a new organization.

    The creating user becomes the owner.
    """
    org = await organization_ops.create(
        db,
        name=data.name,
        owner_id=user.id,
        slug=data.slug,
    )
    await db.commit()

    return OrganizationResponse(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        owner_id=str(org.owner_id),
        created_at=org.created_at.isoformat(),
        updated_at=org.updated_at.isoformat() if org.updated_at else None,
        is_personal=True,
        role=MemberRole.OWNER.value,
    )


@router.get("/plans")
async def list_plans(
    _user: User = Depends(get_current_user),
) -> list[PlanResponse]:
    """
    List all available plan tiers.

    Returns configuration details for all plans (for pricing display).
    """
    return [
        PlanResponse(
            tier=plan.tier,
            display_name=plan.display_name,
            price_monthly=plan.price_monthly,
            base_repo_limit=plan.base_repo_limit,
            overage_repo_price=plan.overage_repo_price,
            allows_overages=plan.allows_overages,
            features=plan.to_features_dict(),
            analysis_frequency=plan.analysis_frequency,
        )
        for plan in PLANS.values()
    ]


@router.get("/{org_id}")
async def get_organization(
    org_id: uuid_pkg.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrganizationDetailResponse:
    """
    Get detailed information about an organization.

    Requires membership in the organization.
    """
    org = await organization_ops.get(db, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    role = await _require_org_access(db, org_id, user)
    member_count = await org_member_ops.count_by_org(db, org_id)

    return OrganizationDetailResponse(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        owner_id=str(org.owner_id),
        settings=org.settings,
        created_at=org.created_at.isoformat(),
        updated_at=org.updated_at.isoformat() if org.updated_at else None,
        role=role,
        member_count=member_count,
    )


@router.patch("/{org_id}")
async def update_organization(
    org_id: uuid_pkg.UUID,
    data: OrganizationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrganizationDetailResponse:
    """
    Update an organization.

    Requires admin or owner role.
    """
    org = await organization_ops.get(db, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    role = await _require_org_access(db, org_id, user, min_role=MemberRole.ADMIN)

    # Update organization
    updates = data.model_dump(exclude_unset=True)
    if updates:
        org = await organization_ops.update(db, org, updates)

    await db.commit()

    member_count = await org_member_ops.count_by_org(db, org_id)

    return OrganizationDetailResponse(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        owner_id=str(org.owner_id),
        settings=org.settings,
        created_at=org.created_at.isoformat(),
        updated_at=org.updated_at.isoformat() if org.updated_at else None,
        role=role,
        member_count=member_count,
    )


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    org_id: uuid_pkg.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Delete an organization.

    Requires owner role. This will delete all organization data including
    products, repositories, and subscriptions.
    """
    org = await organization_ops.get(db, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    await _require_org_access(db, org_id, user, min_role=MemberRole.OWNER)

    await organization_ops.delete(db, org_id)
    await db.commit()


# Member management endpoints
@router.get("/{org_id}/members")
async def list_members(
    org_id: uuid_pkg.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
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

    await _require_org_access(db, org_id, user)

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
        )
        for m in members
    ]


@router.post("/{org_id}/members", status_code=status.HTTP_201_CREATED)
async def add_member(
    org_id: uuid_pkg.UUID,
    data: OrganizationMemberCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
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

    caller_role = await _require_org_access(db, org_id, user, min_role=MemberRole.ADMIN)

    # Validate role assignment
    role_hierarchy = {
        MemberRole.VIEWER.value: 0,
        MemberRole.MEMBER.value: 1,
        MemberRole.ADMIN.value: 2,
        MemberRole.OWNER.value: 3,
    }

    # Admins can only assign member/viewer roles
    if (
        caller_role == MemberRole.ADMIN.value
        and role_hierarchy.get(data.role, 0) >= role_hierarchy.get(MemberRole.ADMIN.value, 0)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins can only assign member or viewer roles",
        )

    # Find user by email
    target_user = await org_member_ops.find_user_by_email(db, data.email)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found. They must have an account first.",
        )

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
    )


@router.patch("/{org_id}/members/{member_id}")
async def update_member_role(
    org_id: uuid_pkg.UUID,
    member_id: uuid_pkg.UUID,
    data: OrganizationMemberUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
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

    caller_role = await _require_org_access(db, org_id, user, min_role=MemberRole.ADMIN)

    # Get the membership
    member = await org_member_ops.get(db, member_id)
    if not member or member.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )

    # Role hierarchy
    role_hierarchy = {
        MemberRole.VIEWER.value: 0,
        MemberRole.MEMBER.value: 1,
        MemberRole.ADMIN.value: 2,
        MemberRole.OWNER.value: 3,
    }

    # Can't change own role
    if member.user_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own role",
        )

    # Admins can only change member/viewer roles
    if caller_role == MemberRole.ADMIN.value:
        if role_hierarchy.get(member.role, 0) >= role_hierarchy.get(MemberRole.ADMIN.value, 0):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only owners can change admin or owner roles",
            )
        if role_hierarchy.get(data.role, 0) >= role_hierarchy.get(MemberRole.ADMIN.value, 0):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admins can only assign member or viewer roles",
            )

    # Changing to/from owner requires owner role
    if (
        (data.role == MemberRole.OWNER.value or member.role == MemberRole.OWNER.value)
        and caller_role != MemberRole.OWNER.value
    ):
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
    await db.refresh(member)

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
    )


@router.delete("/{org_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    org_id: uuid_pkg.UUID,
    member_id: uuid_pkg.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
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

    caller_role = await _require_org_access(db, org_id, user)

    # Get the membership
    member = await org_member_ops.get(db, member_id)
    if not member or member.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )

    role_hierarchy = {
        MemberRole.VIEWER.value: 0,
        MemberRole.MEMBER.value: 1,
        MemberRole.ADMIN.value: 2,
        MemberRole.OWNER.value: 3,
    }

    # Self-removal is always allowed
    is_self = member.user_id == user.id

    if not is_self:
        # Require at least admin to remove others
        if role_hierarchy.get(caller_role, 0) < role_hierarchy.get(MemberRole.ADMIN.value, 0):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins and owners can remove other members",
            )

        # Admins can only remove member/viewer
        if (
            caller_role == MemberRole.ADMIN.value
            and role_hierarchy.get(member.role, 0) >= role_hierarchy.get(MemberRole.ADMIN.value, 0)
        ):
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


# Subscription endpoint
@router.get("/{org_id}/subscription")
async def get_subscription(
    org_id: uuid_pkg.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionResponse:
    """
    Get subscription details for an organization.

    Requires membership in the organization.
    """
    org = await organization_ops.get(db, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    await _require_org_access(db, org_id, user)

    subscription = await subscription_ops.get_by_org(db, org_id)
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found",
        )

    plan = get_plan(subscription.plan_tier)

    return SubscriptionResponse(
        id=str(subscription.id),
        plan_tier=subscription.plan_tier,
        plan_display_name=plan.display_name,
        status=subscription.status,
        base_repo_limit=subscription.base_repo_limit,
        is_manually_assigned=subscription.is_manually_assigned,
        created_at=subscription.created_at.isoformat(),
        features=plan.to_features_dict(),
        analysis_frequency=plan.analysis_frequency,
        price_monthly=plan.price_monthly,
        allows_overages=plan.allows_overages,
        overage_repo_price=plan.overage_repo_price,
    )
