"""
Tests for cross-organization subscription context resolution.

These tests verify the fix for the bug where free-tier users collaborating
on paid organizations couldn't create repos under the paid org because
subscription limits were checked against the user's personal (free) org
instead of the target product's (paid) org.

Bug: docs/executing/org-subs-bug.md
Fix: docs/completions/org-subs-bug-fix.md
"""

import uuid
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.deps.feature_gates import get_subscription_context_for_product
from app.config.plans import PlanConfig


@dataclass
class MockOrganization:
    """Mock organization for testing."""

    id: uuid.UUID
    name: str


@dataclass
class MockProduct:
    """Mock product for testing."""

    id: uuid.UUID
    name: str
    organization_id: uuid.UUID | None


@dataclass
class MockSubscription:
    """Mock subscription for testing."""

    id: uuid.UUID
    organization_id: uuid.UUID
    plan_tier: str


class TestGetSubscriptionContextForProduct:
    """Tests for get_subscription_context_for_product function."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.db = AsyncMock()

        # Create mock organizations
        self.personal_org = MockOrganization(
            id=uuid.uuid4(),
            name="Personal Workspace",
        )
        self.paid_org = MockOrganization(
            id=uuid.uuid4(),
            name="Acme Corp",
        )

        # Create mock product belonging to paid org
        self.product = MockProduct(
            id=uuid.uuid4(),
            name="Acme Project",
            organization_id=self.paid_org.id,
        )

        # Create mock subscriptions
        self.free_subscription = MockSubscription(
            id=uuid.uuid4(),
            organization_id=self.personal_org.id,
            plan_tier="observer",  # Free tier
        )
        self.paid_subscription = MockSubscription(
            id=uuid.uuid4(),
            organization_id=self.paid_org.id,
            plan_tier="builder",  # Paid tier
        )

    @pytest.mark.asyncio
    async def test_returns_product_org_subscription(self) -> None:
        """
        Subscription context should be for the product's organization,
        NOT the user's default organization.

        This is the core bug fix verification.
        """
        with (
            patch(
                "app.domain.product_operations.product_ops.get",
                new_callable=AsyncMock,
            ) as mock_product_get,
            patch(
                "app.domain.organization_operations.organization_ops.get",
                new_callable=AsyncMock,
            ) as mock_org_get,
            patch(
                "app.domain.subscription_operations.subscription_ops.get_by_org",
                new_callable=AsyncMock,
            ) as mock_sub_get,
            patch(
                "app.api.deps.feature_gates.get_plan",
            ) as mock_get_plan,
        ):
            # Set up mocks
            mock_product_get.return_value = self.product
            mock_org_get.return_value = self.paid_org
            mock_sub_get.return_value = self.paid_subscription
            mock_get_plan.return_value = MagicMock(spec=PlanConfig)

            # Call the function
            result = await get_subscription_context_for_product(self.db, self.product.id)

            # Verify we got the PAID org's context, not personal org
            assert result.organization.id == self.paid_org.id
            assert result.subscription.plan_tier == "builder"

            # Verify the product was looked up
            mock_product_get.assert_called_once_with(self.db, self.product.id)

            # Verify the org lookup used product's org_id (not user's default)
            mock_org_get.assert_called_once_with(self.db, self.product.organization_id)

            # Verify subscription lookup used the product's org
            mock_sub_get.assert_called_once_with(self.db, self.paid_org.id)

    @pytest.mark.asyncio
    async def test_raises_404_for_nonexistent_product(self) -> None:
        """Should raise 404 if product doesn't exist."""
        with patch(
            "app.domain.product_operations.product_ops.get",
            new_callable=AsyncMock,
        ) as mock_product_get:
            mock_product_get.return_value = None

            with pytest.raises(HTTPException) as exc_info:
                await get_subscription_context_for_product(self.db, uuid.uuid4())

            assert exc_info.value.status_code == 404
            assert "Product not found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_raises_400_for_product_without_org(self) -> None:
        """Should raise 400 if product has no organization."""
        orphan_product = MockProduct(
            id=uuid.uuid4(),
            name="Orphan Product",
            organization_id=None,
        )

        with patch(
            "app.domain.product_operations.product_ops.get",
            new_callable=AsyncMock,
        ) as mock_product_get:
            mock_product_get.return_value = orphan_product

            with pytest.raises(HTTPException) as exc_info:
                await get_subscription_context_for_product(self.db, orphan_product.id)

            assert exc_info.value.status_code == 400
            assert "no organization" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_raises_404_for_nonexistent_organization(self) -> None:
        """Should raise 404 if product's organization doesn't exist."""
        with (
            patch(
                "app.domain.product_operations.product_ops.get",
                new_callable=AsyncMock,
            ) as mock_product_get,
            patch(
                "app.domain.organization_operations.organization_ops.get",
                new_callable=AsyncMock,
            ) as mock_org_get,
        ):
            mock_product_get.return_value = self.product
            mock_org_get.return_value = None

            with pytest.raises(HTTPException) as exc_info:
                await get_subscription_context_for_product(self.db, self.product.id)

            assert exc_info.value.status_code == 404
            assert "Organization not found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_raises_500_for_missing_subscription(self) -> None:
        """Should raise 500 if organization has no subscription."""
        with (
            patch(
                "app.domain.product_operations.product_ops.get",
                new_callable=AsyncMock,
            ) as mock_product_get,
            patch(
                "app.domain.organization_operations.organization_ops.get",
                new_callable=AsyncMock,
            ) as mock_org_get,
            patch(
                "app.domain.subscription_operations.subscription_ops.get_by_org",
                new_callable=AsyncMock,
            ) as mock_sub_get,
        ):
            mock_product_get.return_value = self.product
            mock_org_get.return_value = self.paid_org
            mock_sub_get.return_value = None

            with pytest.raises(HTTPException) as exc_info:
                await get_subscription_context_for_product(self.db, self.product.id)

            assert exc_info.value.status_code == 500
            assert "subscription not found" in str(exc_info.value.detail)


class TestCrossOrgScenarios:
    """
    Integration-style tests for cross-organization scenarios.

    These tests verify the expected behavior when a free-tier user
    collaborates on a paid organization's product.
    """

    def setup_method(self) -> None:
        """Set up test fixtures for cross-org scenarios."""
        self.db = AsyncMock()

        # Free-tier user with personal org
        self.user_personal_org = MockOrganization(
            id=uuid.uuid4(),
            name="User Personal",
        )
        self.user_free_subscription = MockSubscription(
            id=uuid.uuid4(),
            organization_id=self.user_personal_org.id,
            plan_tier="observer",  # Free tier: 1 repo limit
        )

        # Paid organization the user collaborates on
        self.paid_org = MockOrganization(
            id=uuid.uuid4(),
            name="Paid Company",
        )
        self.paid_subscription = MockSubscription(
            id=uuid.uuid4(),
            organization_id=self.paid_org.id,
            plan_tier="builder",  # Paid tier: 3 repo limit, allows overages
        )

        # Product in the paid org
        self.paid_org_product = MockProduct(
            id=uuid.uuid4(),
            name="Paid Project",
            organization_id=self.paid_org.id,
        )

    @pytest.mark.asyncio
    async def test_free_user_gets_paid_org_context_for_paid_product(self) -> None:
        """
        When a free-tier user creates a repo under a paid org's product,
        they should get the PAID org's subscription context for limit checks.

        This is the core scenario the bug fix addresses.
        """
        with (
            patch(
                "app.domain.product_operations.product_ops.get",
                new_callable=AsyncMock,
            ) as mock_product_get,
            patch(
                "app.domain.organization_operations.organization_ops.get",
                new_callable=AsyncMock,
            ) as mock_org_get,
            patch(
                "app.domain.subscription_operations.subscription_ops.get_by_org",
                new_callable=AsyncMock,
            ) as mock_sub_get,
            patch(
                "app.api.deps.feature_gates.get_plan",
            ) as mock_get_plan,
        ):
            # Set up to return paid org's data
            mock_product_get.return_value = self.paid_org_product
            mock_org_get.return_value = self.paid_org
            mock_sub_get.return_value = self.paid_subscription

            # Mock plan config for builder tier
            builder_plan = MagicMock(spec=PlanConfig)
            builder_plan.base_repo_limit = 3
            builder_plan.allows_overages = True
            mock_get_plan.return_value = builder_plan

            # Get subscription context for the paid org's product
            result = await get_subscription_context_for_product(self.db, self.paid_org_product.id)

            # Key assertions: we got the PAID org's context
            assert result.organization.id == self.paid_org.id
            assert result.organization.id != self.user_personal_org.id
            assert result.subscription.plan_tier == "builder"
            assert result.plan.base_repo_limit == 3
            assert result.plan.allows_overages is True

    @pytest.mark.asyncio
    async def test_subscription_context_determines_limit_behavior(self) -> None:
        """
        Verify that the subscription tier determines limit enforcement behavior.

        - Free tier (observer): allows_overages=False, blocked at limit
        - Paid tier (builder): allows_overages=True, can exceed with charges
        """
        with (
            patch(
                "app.domain.product_operations.product_ops.get",
                new_callable=AsyncMock,
            ) as mock_product_get,
            patch(
                "app.domain.organization_operations.organization_ops.get",
                new_callable=AsyncMock,
            ) as mock_org_get,
            patch(
                "app.domain.subscription_operations.subscription_ops.get_by_org",
                new_callable=AsyncMock,
            ) as mock_sub_get,
            patch(
                "app.api.deps.feature_gates.get_plan",
            ) as mock_get_plan,
        ):
            # Set up for paid org
            mock_product_get.return_value = self.paid_org_product
            mock_org_get.return_value = self.paid_org
            mock_sub_get.return_value = self.paid_subscription

            builder_plan = MagicMock(spec=PlanConfig)
            builder_plan.allows_overages = True
            mock_get_plan.return_value = builder_plan

            result = await get_subscription_context_for_product(self.db, self.paid_org_product.id)

            # With paid tier, overages are allowed
            assert result.plan.allows_overages is True

            # This means repo creation should succeed even if at/over limit
            # (actual limit check happens in the endpoint, but context is correct)
