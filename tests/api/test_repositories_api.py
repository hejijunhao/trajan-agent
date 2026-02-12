"""Repository API endpoint tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_list_repositories_by_product(
    api_client: AsyncClient, test_product, test_repository, test_subscription
):
    """GET /api/v1/repositories/?product_id={id} returns product repos."""
    resp = await api_client.get(
        "/api/v1/repositories/", params={"product_id": str(test_product.id)}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    repo_ids = [r["id"] for r in data]
    assert str(test_repository.id) in repo_ids


@pytest.mark.anyio
async def test_list_repositories_no_product(api_client: AsyncClient, test_subscription):
    """GET /api/v1/repositories/ without product_id returns empty list."""
    resp = await api_client.get("/api/v1/repositories/")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.anyio
async def test_get_repository(
    api_client: AsyncClient, test_repository, test_subscription
):
    """GET /api/v1/repositories/{id} returns the repository."""
    resp = await api_client.get(f"/api/v1/repositories/{test_repository.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(test_repository.id)
    assert data["product_id"] == str(test_repository.product_id)


@pytest.mark.anyio
async def test_get_repository_not_found(api_client: AsyncClient, test_subscription):
    """GET /api/v1/repositories/{fake_id} returns 404."""
    resp = await api_client.get(f"/api/v1/repositories/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_create_repository(
    api_client: AsyncClient, test_product, test_subscription
):
    """POST /api/v1/repositories/ creates a new repository."""
    resp = await api_client.post(
        "/api/v1/repositories/",
        json={
            "product_id": str(test_product.id),
            "name": f"new-repo-{uuid.uuid4().hex[:8]}",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert "name" in data


@pytest.mark.anyio
async def test_update_repository(
    api_client: AsyncClient, test_repository, test_subscription
):
    """PATCH /api/v1/repositories/{id} updates the repository."""
    resp = await api_client.patch(
        f"/api/v1/repositories/{test_repository.id}",
        json={"description": "Updated description"},
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "Updated description"


@pytest.mark.anyio
async def test_delete_repository(
    api_client: AsyncClient, test_product, test_subscription, db_session, test_user
):
    """DELETE /api/v1/repositories/{id} deletes a repository."""
    from app.domain.repository_operations import repository_ops

    throwaway = await repository_ops.create(
        db_session,
        obj_in={
            "product_id": test_product.id,
            "name": f"throwaway-{uuid.uuid4().hex[:8]}",
            "full_name": f"org/throwaway-{uuid.uuid4().hex[:8]}",
        },
        imported_by_user_id=test_user.id,
    )
    resp = await api_client.delete(f"/api/v1/repositories/{throwaway.id}")
    assert resp.status_code == 204
