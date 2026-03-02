"""Domain operations for Subscription model — Community Edition.

Same CRUD operations as production, without billing event audit logging.
"""

import uuid as uuid_pkg
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.plans import get_plan
from app.models.subscription import PlanTier, Subscription, SubscriptionStatus


@dataclass
class RepoLimitStatus:
    """Result of checking repository limits."""

    can_add: bool
    current_count: int
    base_limit: int
    overage_count: int
    overage_cost_cents: int
    allows_overages: bool


class SubscriptionOperations:
    """CRUD operations for Subscription model."""

    async def get(
        self,
        db: AsyncSession,
        id: uuid_pkg.UUID,
    ) -> Subscription | None:
        """Get a subscription by ID."""
        statement = select(Subscription).where(Subscription.id == id)
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_org(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
    ) -> Subscription | None:
        """Get subscription for an organization."""
        statement = select(Subscription).where(
            Subscription.organization_id == organization_id
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def create(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
        plan_tier: str = PlanTier.OBSERVER.value,
    ) -> Subscription:
        """
        Create a new subscription for an organization.

        Defaults to free (Observer) tier.
        """
        plan = get_plan(plan_tier)

        subscription = Subscription(
            organization_id=organization_id,
            plan_tier=plan_tier,
            status=SubscriptionStatus.ACTIVE.value,
            base_repo_limit=plan.base_repo_limit,
        )
        db.add(subscription)
        await db.flush()
        await db.refresh(subscription)

        return subscription

    async def update(
        self,
        db: AsyncSession,
        subscription: Subscription,
        updates: dict[str, Any],
    ) -> Subscription:
        """Update a subscription."""
        for field, value in updates.items():
            setattr(subscription, field, value)
        db.add(subscription)
        await db.flush()
        await db.refresh(subscription)
        return subscription

    async def admin_assign_plan(
        self,
        db: AsyncSession,
        subscription: Subscription,
        plan_tier: str,
        admin_user_id: uuid_pkg.UUID,
        note: str | None = None,
    ) -> Subscription:
        """
        Manually assign a plan tier (admin only).

        Bypasses Stripe and sets the plan directly.
        """
        plan = get_plan(plan_tier)

        # Update subscription
        subscription.plan_tier = plan_tier
        subscription.base_repo_limit = plan.base_repo_limit
        subscription.is_manually_assigned = True
        subscription.manually_assigned_by = admin_user_id
        subscription.manually_assigned_at = datetime.now(UTC)
        subscription.manual_assignment_note = note
        subscription.status = SubscriptionStatus.ACTIVE.value

        db.add(subscription)
        await db.flush()
        await db.refresh(subscription)

        return subscription

    async def is_agent_enabled(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
        current_repo_count: int,
    ) -> bool:
        """
        Check if agent features are enabled for this organization.

        Returns False if free tier and over repo limit.
        """
        subscription = await self.get_by_org(db, organization_id)
        plan = get_plan(subscription.plan_tier if subscription else "observer")

        if plan.allows_overages:
            # Paid plans: agent always enabled
            return True

        # Free tier: check repo limit
        return current_repo_count <= plan.base_repo_limit

    async def check_repo_limit(
        self,
        db: AsyncSession,
        organization_id: uuid_pkg.UUID,
        current_repo_count: int,
        additional_count: int = 1,
    ) -> RepoLimitStatus:
        """
        Check if org can add more repositories and calculate overage costs.

        Returns a RepoLimitStatus with can_add, current_count, overage info.
        """
        subscription = await self.get_by_org(db, organization_id)
        plan = get_plan(subscription.plan_tier if subscription else "observer")

        new_total = current_repo_count + additional_count
        overage_count = max(0, new_total - plan.base_repo_limit)
        overage_cost = overage_count * plan.overage_repo_price

        # Free tier: can't add if at limit
        # Paid tiers: can always add (with overage charges)
        can_add = plan.allows_overages or (new_total <= plan.base_repo_limit)

        return RepoLimitStatus(
            can_add=can_add,
            current_count=current_repo_count,
            base_limit=plan.base_repo_limit,
            overage_count=overage_count,
            overage_cost_cents=overage_cost,
            allows_overages=plan.allows_overages,
        )


subscription_ops = SubscriptionOperations()
