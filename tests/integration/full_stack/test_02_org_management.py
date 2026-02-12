"""Critical Path 2: Organization Management.

Tests org creation, member management, and role-based access:
  Create org → Invite member → Verify access → Update role → Remove member

Runs against REAL infrastructure.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.helpers.auth import auth_header, create_supabase_test_user
from tests.helpers.tracker import ResourceTracker


class TestOrganizationManagement:
    """Test org creation and member management against real Supabase."""

    @pytest.mark.full_stack
    async def test_create_organization(
        self,
        integration_client: AsyncClient,
        test_user_registered,
        integration_tracker: ResourceTracker,
    ):
        """CRITICAL PATH: User creates a new organization.

        Expected:
        1. Organization created with user as owner
        2. Subscription auto-created (pending, tier=none)
        3. User appears in members list with owner role
        """
        response = await integration_client.post(
            "/api/v1/organizations",
            json={"name": "[TEST] Integration Org"},
            headers=auth_header(test_user_registered.token),
        )

        assert response.status_code == 201
        org = response.json()
        integration_tracker.register_org(org["id"])

        assert org["name"] == "[TEST] Integration Org"
        assert org["owner_id"] == str(test_user_registered.id)
        assert org["role"] == "owner"

        # Verify subscription exists
        sub_response = await integration_client.get(
            f"/api/v1/organizations/{org['id']}/subscription",
            headers=auth_header(test_user_registered.token),
        )
        assert sub_response.status_code == 200

        # Verify owner appears in members list
        members_response = await integration_client.get(
            f"/api/v1/organizations/{org['id']}/members",
            headers=auth_header(test_user_registered.token),
        )
        assert members_response.status_code == 200
        members = members_response.json()

        assert len(members) == 1
        assert members[0]["role"] == "owner"
        assert members[0]["user_id"] == str(test_user_registered.id)

    @pytest.mark.full_stack
    async def test_invite_member_to_organization(
        self,
        integration_client: AsyncClient,
        test_user_registered,
        integration_tracker: ResourceTracker,
    ):
        """CRITICAL PATH: Owner invites a new member.

        Creates a second test user and invites them to the org.
        Verifies the invitee can see the org in their list.
        """
        # Create org for this test
        org_response = await integration_client.post(
            "/api/v1/organizations",
            json={"name": "[TEST] Invite Test Org"},
            headers=auth_header(test_user_registered.token),
        )
        assert org_response.status_code == 201
        org = org_response.json()
        org_id = org["id"]
        integration_tracker.register_org(org_id)

        # Create a second test user
        invitee = await create_supabase_test_user()
        integration_tracker.register_user(invitee.id)

        # Auto-provision the invitee by hitting /users/me
        provision_response = await integration_client.get(
            "/api/v1/users/me",
            headers=auth_header(invitee.token),
        )
        assert provision_response.status_code == 200

        # Track invitee's personal org
        invitee_orgs = await integration_client.get(
            "/api/v1/organizations",
            headers=auth_header(invitee.token),
        )
        for o in invitee_orgs.json():
            integration_tracker.register_org(o["id"])

        # Owner invites the second user
        invite_response = await integration_client.post(
            f"/api/v1/organizations/{org_id}/members",
            json={"email": invitee.email, "role": "member"},
            headers=auth_header(test_user_registered.token),
        )
        assert invite_response.status_code == 201
        integration_tracker.register_org_member(org_id, invitee.id)

        # Verify invitee can see the org
        invitee_orgs_after = await integration_client.get(
            "/api/v1/organizations",
            headers=auth_header(invitee.token),
        )
        assert invitee_orgs_after.status_code == 200
        org_ids = [o["id"] for o in invitee_orgs_after.json()]
        assert org_id in org_ids

    @pytest.mark.full_stack
    async def test_list_organization_members(
        self,
        integration_client: AsyncClient,
        test_user_registered,
        integration_tracker: ResourceTracker,
    ):
        """Members list shows correct roles and member count."""
        # Create org
        org_response = await integration_client.post(
            "/api/v1/organizations",
            json={"name": "[TEST] Members List Org"},
            headers=auth_header(test_user_registered.token),
        )
        assert org_response.status_code == 201
        org_id = org_response.json()["id"]
        integration_tracker.register_org(org_id)

        # Check members
        members_response = await integration_client.get(
            f"/api/v1/organizations/{org_id}/members",
            headers=auth_header(test_user_registered.token),
        )
        assert members_response.status_code == 200
        members = members_response.json()

        assert len(members) == 1
        assert members[0]["role"] == "owner"

    @pytest.mark.full_stack
    async def test_non_member_cannot_access_org(
        self,
        integration_client: AsyncClient,
        test_user_registered,
        integration_tracker: ResourceTracker,
    ):
        """A user who is not a member gets 404 for org details."""
        # Create org as primary user
        org_response = await integration_client.post(
            "/api/v1/organizations",
            json={"name": "[TEST] Access Control Org"},
            headers=auth_header(test_user_registered.token),
        )
        assert org_response.status_code == 201
        org_id = org_response.json()["id"]
        integration_tracker.register_org(org_id)

        # Create an unrelated user
        outsider = await create_supabase_test_user()
        integration_tracker.register_user(outsider.id)

        # Auto-provision outsider
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

        # Outsider tries to access the org
        response = await integration_client.get(
            f"/api/v1/organizations/{org_id}",
            headers=auth_header(outsider.token),
        )
        assert response.status_code in [403, 404]
