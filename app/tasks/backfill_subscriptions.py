"""
One-time backfill: Create subscriptions for organizations that don't have them.

This script handles the case where organizations were created before v0.1.25
(when subscription auto-creation was added to organization_operations.create()).

Usage:
    cd backend
    source .venv/bin/activate
    python -m app.tasks.backfill_subscriptions
"""

import asyncio
import logging

from sqlalchemy import select

from app.config.plans import get_plan
from app.core.database import async_session_maker
from app.models.organization import Organization
from app.models.subscription import PlanTier, Subscription, SubscriptionStatus

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def backfill_subscriptions() -> None:
    """
    Create subscriptions for organizations that don't have them.

    All new subscriptions default to the Core tier ($299/mo, 10 repos).
    """
    logger.info("Starting subscription backfill...")

    async with async_session_maker() as db:
        # Get all organizations
        result = await db.execute(select(Organization))
        orgs = list(result.scalars().all())
        logger.info(f"Found {len(orgs)} organizations to check")

        created_count = 0
        skipped_count = 0

        for org in orgs:
            # Check if org already has a subscription
            result = await db.execute(
                select(Subscription).where(Subscription.organization_id == org.id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                logger.debug(f"Organization '{org.name}' already has subscription, skipping")
                skipped_count += 1
                continue

            # Create subscription with Core tier
            plan = get_plan(PlanTier.CORE.value)
            subscription = Subscription(
                organization_id=org.id,
                plan_tier=PlanTier.CORE.value,
                status=SubscriptionStatus.ACTIVE.value,
                base_repo_limit=plan.base_repo_limit,
            )
            db.add(subscription)
            logger.info(f"Created Core subscription for organization '{org.name}'")
            created_count += 1

        await db.commit()

        logger.info("=" * 60)
        logger.info("Backfill complete!")
        logger.info(f"  Subscriptions created: {created_count}")
        logger.info(f"  Organizations skipped (already had subscription): {skipped_count}")
        logger.info("=" * 60)


def main() -> None:
    """Run the backfill."""
    asyncio.run(backfill_subscriptions())


if __name__ == "__main__":
    main()
