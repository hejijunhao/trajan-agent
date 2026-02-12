"""Admin API endpoint tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_list_organizations(admin_client: AsyncClient, test_org):
    """GET /api/v1/admin/organizations returns all orgs (admin only)."""
    resp = await admin_client.get("/api/v1/admin/organizations")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0


@pytest.mark.anyio
async def test_get_organization(admin_client: AsyncClient, test_org):
    """GET /api/v1/admin/organizations/{id} returns org details with members."""
    resp = await admin_client.get(f"/api/v1/admin/organizations/{test_org.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(test_org.id)
    assert "members" in data


@pytest.mark.anyio
async def test_set_subscription(
    admin_client: AsyncClient, test_org, test_subscription
):
    """PATCH /api/v1/admin/organizations/{id}/subscription updates plan tier."""
    resp = await admin_client.patch(
        f"/api/v1/admin/organizations/{test_org.id}/subscription",
        json={"plan_tier": "pro", "note": "Test upgrade"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["plan_tier"] == "pro"
    assert data["is_manually_assigned"] is True


@pytest.mark.anyio
async def test_non_admin_access(api_client: AsyncClient, test_org):
    """GET /api/v1/admin/organizations returns 403 for non-admin."""
    resp = await api_client.get("/api/v1/admin/organizations")
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_list_plans(admin_client: AsyncClient):
    """GET /api/v1/admin/plans returns all plan tiers."""
    resp = await admin_client.get("/api/v1/admin/plans")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0
