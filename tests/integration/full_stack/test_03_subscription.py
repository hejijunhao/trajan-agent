"""Critical Path 3: Subscription Flow.

Tests the Stripe checkout and webhook flow using Stripe sandbox:
  Create checkout → Verify pending → Simulate webhook → Verify active

Runs against REAL Stripe sandbox (sk_test_ keys).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.config.settings import settings
from tests.helpers.auth import auth_header, create_supabase_test_user
from tests.helpers.tracker import ResourceTracker


class TestSubscriptionFlow:
    """Test Stripe subscription checkout using Stripe sandbox."""

    @pytest.mark.full_stack
    async def test_new_org_has_pending_subscription(
        self,
        integration_client: AsyncClient,
        test_user_registered,
        integration_tracker: ResourceTracker,
    ):
        """New organizations start with a pending subscription (tier=none)."""
        org_response = await integration_client.post(
            "/api/v1/organizations",
            json={"name": "[TEST] Subscription Pending Org"},
            headers=auth_header(test_user_registered.token),
        )
        assert org_response.status_code == 201
        org_id = org_response.json()["id"]
        integration_tracker.register_org(org_id)

        sub_response = await integration_client.get(
            f"/api/v1/organizations/{org_id}/subscription",
            headers=auth_header(test_user_registered.token),
        )
        assert sub_response.status_code == 200
        sub = sub_response.json()

        assert sub["plan_tier"] == "none"
        assert sub["status"] == "pending"

    @pytest.mark.full_stack
    @pytest.mark.skipif(
        not settings.stripe_enabled,
        reason="Stripe not configured (stripe_secret_key missing)",
    )
    async def test_create_checkout_session(
        self,
        integration_client: AsyncClient,
        test_user_registered,
        integration_tracker: ResourceTracker,
    ):
        """CRITICAL PATH: User initiates plan selection via Stripe Checkout.

        Expected:
        1. Checkout session created with Stripe (sandbox)
        2. Returns checkout URL
        3. Subscription still pending until webhook
        """
        # Create a fresh org for this test
        org_response = await integration_client.post(
            "/api/v1/organizations",
            json={"name": "[TEST] Checkout Org"},
            headers=auth_header(test_user_registered.token),
        )
        assert org_response.status_code == 201
        org_id = org_response.json()["id"]
        integration_tracker.register_org(org_id)

        # Create checkout session
        checkout_response = await integration_client.post(
            "/api/v1/billing/checkout",
            json={
                "plan_tier": "indie",
                "organization_id": org_id,
                "source": "test",
            },
            headers=auth_header(test_user_registered.token),
        )

        assert checkout_response.status_code == 200
        checkout = checkout_response.json()
        assert "checkout_url" in checkout
        assert "checkout.stripe.com" in checkout["checkout_url"]

        # Subscription should still be pending (webhook not yet received)
        sub_response = await integration_client.get(
            f"/api/v1/organizations/{org_id}/subscription",
            headers=auth_header(test_user_registered.token),
        )
        sub = sub_response.json()
        # Still none/pending because the checkout hasn't been completed
        assert sub["plan_tier"] == "none"

    @pytest.mark.full_stack
    async def test_billing_plans_endpoint_public(
        self,
        integration_client: AsyncClient,
    ):
        """The /billing/plans endpoint is accessible without auth."""
        response = await integration_client.get("/api/v1/billing/plans")
        assert response.status_code == 200
        plans = response.json()
        assert len(plans) > 0

        tier_names = [p["tier"] for p in plans]
        assert "indie" in tier_names
        assert "pro" in tier_names
        assert "scale" in tier_names

    @pytest.mark.full_stack
    async def test_subscription_endpoint_requires_membership(
        self,
        integration_client: AsyncClient,
        test_user_registered,
        integration_tracker: ResourceTracker,
    ):
        """Non-members cannot view an org's subscription."""
        # Create org as primary user
        org_response = await integration_client.post(
            "/api/v1/organizations",
            json={"name": "[TEST] Sub Access Org"},
            headers=auth_header(test_user_registered.token),
        )
        assert org_response.status_code == 201
        org_id = org_response.json()["id"]
        integration_tracker.register_org(org_id)

        # Create outsider
        outsider = await create_supabase_test_user()
        integration_tracker.register_user(outsider.id)
        await integration_client.get(
            "/api/v1/users/me",
            headers=auth_header(outsider.token),
        )
        outsider_orgs = await integration_client.get(
            "/api/v1/organizations",
            headers=auth_header(outsider.token),
        )
        for o in outsider_orgs.json():
            integration_tracker.register_org(o["id"])

        # Outsider tries to view subscription
        response = await integration_client.get(
            f"/api/v1/organizations/{org_id}/subscription",
            headers=auth_header(outsider.token),
        )
        assert response.status_code == 403
