"""Organization API endpoint tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_list_organizations(api_client: AsyncClient, test_org):
    """GET /api/v1/organizations/ returns user's organizations."""
    resp = await api_client.get("/api/v1/organizations/")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    org_ids = [o["id"] for o in data]
    assert str(test_org.id) in org_ids


@pytest.mark.anyio
async def test_create_organization(api_client: AsyncClient):
    """POST /api/v1/organizations/ creates a new organization."""
    resp = await api_client.post(
        "/api/v1/organizations/",
        json={"name": f"New Org {uuid.uuid4().hex[:8]}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert "owner_id" in data


@pytest.mark.anyio
async def test_get_organization(api_client: AsyncClient, test_org):
    """GET /api/v1/organizations/{id} returns organization details."""
    resp = await api_client.get(f"/api/v1/organizations/{test_org.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == test_org.name
    assert data["slug"] == test_org.slug


@pytest.mark.anyio
async def test_update_organization(api_client: AsyncClient, test_org):
    """PATCH /api/v1/organizations/{id} updates the organization."""
    new_name = f"Updated Org {uuid.uuid4().hex[:8]}"
    resp = await api_client.patch(
        f"/api/v1/organizations/{test_org.id}",
        json={"name": new_name},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == new_name


@pytest.mark.anyio
async def test_delete_organization(api_client: AsyncClient, db_session, test_user):
    """DELETE /api/v1/organizations/{id} deletes an organization."""
    from app.domain.organization_operations import organization_ops

    # Create a throwaway org to delete (preserve test_org)
    throwaway = await organization_ops.create(
        db_session,
        name=f"Throwaway Org {uuid.uuid4().hex[:8]}",
        owner_id=test_user.id,
    )
    resp = await api_client.delete(f"/api/v1/organizations/{throwaway.id}")
    assert resp.status_code == 204


@pytest.mark.anyio
async def test_list_members(api_client: AsyncClient, test_org, test_user):
    """GET /api/v1/organizations/{id}/members returns members list."""
    resp = await api_client.get(f"/api/v1/organizations/{test_org.id}/members")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    user_ids = [m["user_id"] for m in data]
    assert str(test_user.id) in user_ids


@pytest.mark.anyio
async def test_get_subscription(api_client: AsyncClient, test_org, test_subscription):
    """GET /api/v1/organizations/{id}/subscription returns subscription info."""
    resp = await api_client.get(f"/api/v1/organizations/{test_org.id}/subscription")
    assert resp.status_code == 200
    data = resp.json()
    assert data["plan_tier"] == "indie"


@pytest.mark.anyio
async def test_non_member_access(second_user_client: AsyncClient, test_org):
    """GET /api/v1/organizations/{id} returns 403 for non-members."""
    resp = await second_user_client.get(f"/api/v1/organizations/{test_org.id}")
    assert resp.status_code == 403
