"""Organization subscription endpoints."""

import uuid as uuid_pkg

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_with_rls
from app.api.v1.organizations.helpers import require_org_access
from app.api.v1.organizations.schemas import RepoLimitStatusResponse, SubscriptionResponse
from app.config.plans import get_plan
from app.domain import organization_ops, repository_ops, subscription_ops
from app.models.user import User


async def get_subscription(
    org_id: uuid_pkg.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
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

    await require_org_access(db, org_id, user)

    subscription = await subscription_ops.get_by_org(db, org_id)
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found",
        )

    plan = get_plan(subscription.plan_tier)

    # Use plan config for non-manual subscriptions, respect DB value for manual assignments
    effective_repo_limit = (
        subscription.base_repo_limit if subscription.is_manually_assigned else plan.base_repo_limit
    )

    return SubscriptionResponse(
        id=str(subscription.id),
        plan_tier=subscription.plan_tier,
        plan_display_name=plan.display_name,
        status=subscription.status,
        base_repo_limit=effective_repo_limit,
        is_manually_assigned=subscription.is_manually_assigned,
        created_at=subscription.created_at.isoformat(),
        features=plan.features,
        analysis_frequency=plan.analysis_frequency,
        price_monthly=plan.price_monthly,
        allows_overages=plan.allows_overages,
        overage_repo_price=plan.overage_repo_price,
        cancel_at_period_end=subscription.cancel_at_period_end,
        current_period_end=(
            subscription.current_period_end.isoformat()
            if subscription.current_period_end
            else None
        ),
    )


async def get_repo_limit_status(
    org_id: uuid_pkg.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> RepoLimitStatusResponse:
    """
    Get repository limit status for an organization.

    Returns current usage, plan limits, and overage pricing.
    Used by frontend to show confirmation modal before incurring overages.

    Requires membership in the organization.
    """
    org = await organization_ops.get(db, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    await require_org_access(db, org_id, user)

    subscription = await subscription_ops.get_by_org(db, org_id)
    plan = get_plan(subscription.plan_tier if subscription else "none")

    # Use plan config for non-manual subscriptions, respect DB value for manual assignments
    effective_repo_limit = (
        subscription.base_repo_limit
        if subscription and subscription.is_manually_assigned
        else plan.base_repo_limit
    )

    current_count = await repository_ops.count_by_org(db, org_id)

    return RepoLimitStatusResponse(
        current_count=current_count,
        base_limit=effective_repo_limit,
        allows_overages=plan.allows_overages,
        overage_price_cents=plan.overage_repo_price,
    )
