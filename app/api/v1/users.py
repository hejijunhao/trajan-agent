from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_with_rls
from app.domain.org_member_operations import org_member_ops
from app.domain.user_operations import user_ops
from app.models.subscription import PlanTier
from app.models.user import User

router = APIRouter(prefix="/users", tags=["users"])


class UserRead(BaseModel):
    """User profile response."""

    id: str
    email: str | None
    display_name: str | None
    avatar_url: str | None
    github_username: str | None
    auth_provider: str | None
    created_at: str
    onboarding_completed_at: str | None

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    """User profile update request."""

    display_name: str | None = None
    avatar_url: str | None = None


class InvitedOrgInfo(BaseModel):
    """Info about an organization the user was invited to."""

    id: str
    name: str
    slug: str
    inviter_name: str | None  # Display name of person who invited
    inviter_email: str | None  # Fallback if no display name
    invited_at: str | None


class OnboardingContext(BaseModel):
    """Context for frontend to determine which onboarding flow to show."""

    # Orgs user was invited to (not owner)
    invited_orgs: list[InvitedOrgInfo]

    # User's personal org needs setup? (owner + plan_tier = 'none')
    personal_org_incomplete: bool
    personal_org_id: str | None
    personal_org_name: str | None

    # Has user completed onboarding before?
    onboarding_completed: bool

    # Recommended flow: "full" | "invited" | "returning"
    recommended_flow: Literal["full", "invited", "returning"]


def user_to_response(user: User) -> dict:
    """Convert User model to response dict."""
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "github_username": user.github_username,
        "auth_provider": user.auth_provider,
        "created_at": user.created_at.isoformat(),
        "onboarding_completed_at": (
            user.onboarding_completed_at.isoformat() if user.onboarding_completed_at else None
        ),
    }


@router.get("/me", response_model=UserRead)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
):
    """Get the current user's profile."""
    return user_to_response(current_user)


@router.patch("/me", response_model=UserRead)
async def update_current_user_profile(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
):
    """Update the current user's profile."""
    update_data = data.model_dump(exclude_unset=True)

    if not update_data:
        return user_to_response(current_user)

    updated_user = await user_ops.update(db, current_user, update_data)
    return user_to_response(updated_user)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_current_user(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
):
    """
    Delete the current user's account and all associated data.

    This action is irreversible. All products, work items, documents,
    and other user data will be permanently deleted.
    """
    deleted = await user_ops.delete(db, current_user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )


@router.post("/me/complete-onboarding", response_model=UserRead)
async def complete_onboarding(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
):
    """Mark the current user's onboarding as complete."""
    if current_user.onboarding_completed_at is not None:
        # Already completed, just return current state
        return user_to_response(current_user)

    updated_user = await user_ops.update(
        db, current_user, {"onboarding_completed_at": datetime.now(UTC)}
    )
    return user_to_response(updated_user)


@router.get("/me/onboarding-context", response_model=OnboardingContext)
async def get_onboarding_context(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
):
    """
    Get context to determine which onboarding flow to show.

    Returns information about invited organizations and personal org status
    to help the frontend decide between full onboarding, invited user flow,
    or redirect for returning users.
    """
    # Get all memberships with org, subscription, and inviter info
    memberships_with_inviters = await org_member_ops.get_by_user_with_details(db, current_user.id)

    invited_orgs: list[InvitedOrgInfo] = []
    personal_org_incomplete = False
    personal_org_id: str | None = None
    personal_org_name: str | None = None

    for membership, inviter in memberships_with_inviters:
        org = membership.organization
        if not org:
            continue

        subscription = org.subscription

        if org.owner_id == current_user.id:
            # User owns this org - check if setup is incomplete
            plan_tier = subscription.plan_tier if subscription else PlanTier.NONE.value
            if plan_tier == PlanTier.NONE.value:
                personal_org_incomplete = True
                personal_org_id = str(org.id)
                personal_org_name = org.name
        else:
            # User was invited to this org
            invited_orgs.append(
                InvitedOrgInfo(
                    id=str(org.id),
                    name=org.name,
                    slug=org.slug,
                    inviter_name=inviter.display_name if inviter else None,
                    inviter_email=inviter.email if inviter else None,
                    invited_at=(
                        membership.invited_at.isoformat() if membership.invited_at else None
                    ),
                )
            )

    # Determine recommended flow
    onboarding_completed = current_user.onboarding_completed_at is not None

    if onboarding_completed:
        recommended_flow: Literal["full", "invited", "returning"] = "returning"
    elif invited_orgs and personal_org_incomplete:
        # Has invites AND personal org not set up = invited user flow
        recommended_flow = "invited"
    else:
        # Fresh signup or returning to complete setup
        recommended_flow = "full"

    return OnboardingContext(
        invited_orgs=invited_orgs,
        personal_org_incomplete=personal_org_incomplete,
        personal_org_id=personal_org_id,
        personal_org_name=personal_org_name,
        onboarding_completed=onboarding_completed,
        recommended_flow=recommended_flow,
    )
