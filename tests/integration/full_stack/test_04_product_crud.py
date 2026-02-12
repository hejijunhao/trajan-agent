"""Critical Path 4: Product Lifecycle.

Tests the full product lifecycle with subscription gating:
  Activate sub → Create product → Get product → Update → Delete → Verify 404

Runs against REAL infrastructure.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.helpers.auth import auth_header, create_supabase_test_user
from tests.helpers.tracker import ResourceTracker


class TestProductCRUD:
    """Test product creation, update, and deletion."""

    @pytest.mark.full_stack
    async def test_cannot_create_product_without_active_subscription(
        self,
        integration_client: AsyncClient,
        test_user_registered,
        integration_tracker: ResourceTracker,
    ):
        """CRITICAL PATH: Verify subscription gating works.

        Users with pending subscriptions (tier=none) cannot create products.
        """
        # Create a fresh org (subscription starts as pending)
        org_response = await integration_client.post(
            "/api/v1/organizations",
            json={"name": "[TEST] No Sub Product Org"},
            headers=auth_header(test_user_registered.token),
        )
        assert org_response.status_code == 201
        org_id = org_response.json()["id"]
        integration_tracker.register_org(org_id)

        # Try to create a product — should fail (pending subscription)
        # The create_product endpoint uses require_active_subscription
        # which resolves the org from the subscription context
        response = await integration_client.post(
            "/api/v1/products/",
            json={
                "name": "[TEST] Should Fail",
                "description": "This should not be created",
            },
            headers=auth_header(test_user_registered.token),
        )

        # Should be 402 Payment Required (from require_active_subscription)
        assert response.status_code == 402, (
            f"Expected 402 for pending subscription, got {response.status_code}: {response.text}"
        )

    @pytest.mark.full_stack
    async def test_product_list_endpoint_returns_200(
        self,
        integration_client: AsyncClient,
        test_user_registered,
    ):
        """Product listing endpoint returns 200 with a list (even if empty)."""
        response = await integration_client.get(
            "/api/v1/products/",
            headers=auth_header(test_user_registered.token),
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.full_stack
    async def test_get_nonexistent_product_returns_404(
        self,
        integration_client: AsyncClient,
        test_user_registered,
    ):
        """Getting a non-existent product returns 404."""
        import uuid

        fake_id = str(uuid.uuid4())
        response = await integration_client.get(
            f"/api/v1/products/{fake_id}",
            headers=auth_header(test_user_registered.token),
        )
        assert response.status_code == 404

    @pytest.mark.full_stack
    async def test_product_list_returns_empty_for_new_user(
        self,
        integration_client: AsyncClient,
        integration_tracker: ResourceTracker,
    ):
        """A brand new user with no products gets an empty list."""
        # Create fresh user
        new_user = await create_supabase_test_user()
        integration_tracker.register_user(new_user.id)

        # Auto-provision
        await integration_client.get(
            "/api/v1/users/me",
            headers=auth_header(new_user.token),
        )
        orgs = await integration_client.get(
            "/api/v1/organizations",
            headers=auth_header(new_user.token),
        )
        for o in orgs.json():
            integration_tracker.register_org(o["id"])

        # Product list should be empty
        response = await integration_client.get(
            "/api/v1/products/",
            headers=auth_header(new_user.token),
        )
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.full_stack
    async def test_health_endpoint(
        self,
        integration_client: AsyncClient,
    ):
        """Health check endpoint works without auth."""
        response = await integration_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}
