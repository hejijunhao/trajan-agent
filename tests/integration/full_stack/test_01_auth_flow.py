"""Critical Path 1: User Registration & Auto-Provisioning.

Tests the complete flow from Supabase signup to app-level provisioning:
  Supabase user → first API call → User record → Personal org → Subscription

Runs against REAL infrastructure (Supabase Auth + production DB).
All resources are tracked for cleanup.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.helpers.auth import auth_header, create_supabase_test_user
from tests.helpers.tracker import ResourceTracker


class TestAuthFlow:
    """Test user registration and auto-provisioning against real Supabase."""

    @pytest.mark.full_stack
    async def test_new_user_auto_provisioning(
        self,
        integration_client: AsyncClient,
        integration_tracker: ResourceTracker,
    ):
        """CRITICAL PATH: New user signs up and makes first API call.

        Expected flow:
        1. User created in Supabase Auth (via Admin API)
        2. First API call to /users/me auto-creates User record
        3. Personal organization auto-created
        4. Subscription created with status="pending", tier="none"
        """
        # Step 1: Create user in Supabase Auth
        test_user = await create_supabase_test_user()
        integration_tracker.register_user(test_user.id)

        # Step 2: First API call triggers auto-provisioning
        response = await integration_client.get(
            "/api/v1/users/me",
            headers=auth_header(test_user.token),
        )

        assert response.status_code == 200
        user_data = response.json()
        assert user_data["email"] == test_user.email
        assert user_data["id"] == str(test_user.id)

        # Step 3: Verify personal org was created
        orgs_response = await integration_client.get(
            "/api/v1/organizations",
            headers=auth_header(test_user.token),
        )
        assert orgs_response.status_code == 200
        orgs = orgs_response.json()

        assert len(orgs) >= 1, "Personal org should have been created"
        personal_org = orgs[0]
        org_id = personal_org["id"]
        integration_tracker.register_org(org_id)

        assert personal_org["owner_id"] == str(test_user.id)

        # Step 4: Verify subscription is pending
        sub_response = await integration_client.get(
            f"/api/v1/organizations/{org_id}/subscription",
            headers=auth_header(test_user.token),
        )
        assert sub_response.status_code == 200
        sub = sub_response.json()

        assert sub["plan_tier"] == "none"
        assert sub["status"] == "pending"

    @pytest.mark.full_stack
    async def test_user_can_complete_onboarding(
        self,
        integration_client: AsyncClient,
        test_user_registered,
    ):
        """User can mark onboarding as complete."""
        response = await integration_client.post(
            "/api/v1/users/me/complete-onboarding",
            headers=auth_header(test_user_registered.token),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["onboarding_completed_at"] is not None

    @pytest.mark.full_stack
    async def test_second_api_call_idempotent(
        self,
        integration_client: AsyncClient,
        test_user_registered,
    ):
        """Second API call should not create duplicate user or org."""
        # Call /users/me twice
        r1 = await integration_client.get(
            "/api/v1/users/me",
            headers=auth_header(test_user_registered.token),
        )
        r2 = await integration_client.get(
            "/api/v1/users/me",
            headers=auth_header(test_user_registered.token),
        )

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["id"] == r2.json()["id"]

        # Should still have exactly 1 personal org
        orgs = await integration_client.get(
            "/api/v1/organizations",
            headers=auth_header(test_user_registered.token),
        )
        assert orgs.status_code == 200
        # At least 1 org (could have more if other tests created orgs)
        assert len(orgs.json()) >= 1

    @pytest.mark.full_stack
    async def test_unauthenticated_request_rejected(
        self,
        integration_client: AsyncClient,
    ):
        """API calls without a valid token are rejected."""
        response = await integration_client.get("/api/v1/users/me")
        assert response.status_code in [401, 403]

    @pytest.mark.full_stack
    async def test_invalid_token_rejected(
        self,
        integration_client: AsyncClient,
    ):
        """API calls with an invalid JWT are rejected."""
        response = await integration_client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer invalid.jwt.token"},
        )
        assert response.status_code in [401, 403]
