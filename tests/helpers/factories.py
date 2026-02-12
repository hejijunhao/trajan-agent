"""Test data factories for creating real DB entities.

Used in DB integration tests (transaction rollback) and full-stack tests.
All entities use identifiable names with [TEST] prefix or __test_ prefix.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.organization_operations import organization_ops
from app.domain.product_operations import product_ops
from app.domain.subscription_operations import subscription_ops
from app.models.organization import Organization
from app.models.product import Product
from app.models.subscription import Subscription
from app.models.user import User


class TestDataFactory:
    """Creates test entities with identifiable names."""

    @staticmethod
    async def create_user(db: AsyncSession, **overrides: object) -> User:
        """Create a user record in the app database."""
        user = User(
            id=overrides.get("id", uuid.uuid4()),
            email=overrides.get("email", f"__test_{uuid.uuid4().hex[:8]}@example.com"),
            display_name=overrides.get("display_name", "Test User"),
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)
        return user

    @staticmethod
    async def create_organization(
        db: AsyncSession,
        owner: User,
        **overrides: object,
    ) -> Organization:
        """Create an organization with the owner as a member."""
        name = overrides.get("name", f"[TEST] Org {uuid.uuid4().hex[:8]}")
        org = await organization_ops.create(
            db,
            name=name,
            owner_id=owner.id,
        )
        await db.flush()
        return org

    @staticmethod
    async def create_product(
        db: AsyncSession,
        user: User,
        org: Organization,
        **overrides: object,
    ) -> Product:
        """Create a product in the given organization."""
        defaults = {
            "name": f"[TEST] Product {uuid.uuid4().hex[:8]}",
            "description": "Auto-created by test suite",
        }
        for k, v in overrides.items():
            defaults[k] = v

        product = await product_ops.create(
            db,
            obj_in={**defaults, "organization_id": org.id},
            user_id=user.id,
        )
        await db.flush()
        return product

    @staticmethod
    async def activate_subscription(
        db: AsyncSession,
        org: Organization,
        tier: str = "indie",
    ) -> Subscription:
        """Activate an organization's subscription (for tests requiring active sub)."""
        sub = await subscription_ops.get_by_org(db, org.id)
        if not sub:
            raise ValueError(f"No subscription found for org {org.id}")

        from app.config.plans import get_plan

        plan = get_plan(tier)
        await subscription_ops.update(
            db,
            sub,
            {
                "plan_tier": tier,
                "status": "active",
                "base_repo_limit": plan.base_repo_limit,
                "is_manually_assigned": True,
                "manual_assignment_note": "Integration test activation",
            },
        )
        await db.flush()
        await db.refresh(sub)
        return sub
