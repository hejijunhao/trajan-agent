"""Product API endpoint tests.

Tests CRUD operations against real FastAPI route handlers
with a transaction-rollback DB session.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_list_products(api_client: AsyncClient, test_product, test_subscription):
    """GET /api/v1/products/ returns products the user can access."""
    resp = await api_client.get("/api/v1/products/")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    product_ids = [p["id"] for p in data]
    assert str(test_product.id) in product_ids


@pytest.mark.anyio
async def test_get_product(api_client: AsyncClient, test_product, test_subscription):
    """GET /api/v1/products/{id} returns the product details."""
    resp = await api_client.get(f"/api/v1/products/{test_product.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(test_product.id)
    assert data["name"] == test_product.name


@pytest.mark.anyio
async def test_get_product_not_found(api_client: AsyncClient, test_subscription):
    """GET /api/v1/products/{fake_id} returns 404."""
    fake_id = uuid.uuid4()
    resp = await api_client.get(f"/api/v1/products/{fake_id}")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_create_product(api_client: AsyncClient, test_subscription):
    """POST /api/v1/products/ creates a new product."""
    resp = await api_client.post(
        "/api/v1/products/",
        json={"name": f"New Product {uuid.uuid4().hex[:8]}", "description": "Created via test"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert "name" in data


@pytest.mark.anyio
async def test_create_product_duplicate_name(
    api_client: AsyncClient, test_product, test_subscription
):
    """POST /api/v1/products/ with duplicate name returns 400."""
    resp = await api_client.post(
        "/api/v1/products/",
        json={"name": test_product.name, "description": "Duplicate"},
    )
    assert resp.status_code == 400
    assert "already exists" in resp.json()["detail"]


@pytest.mark.anyio
async def test_update_product(api_client: AsyncClient, test_product, test_subscription):
    """PATCH /api/v1/products/{id} updates the product."""
    new_name = f"Updated {uuid.uuid4().hex[:8]}"
    resp = await api_client.patch(
        f"/api/v1/products/{test_product.id}",
        json={"name": new_name},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == new_name


@pytest.mark.anyio
async def test_update_product_not_found(api_client: AsyncClient, test_subscription):
    """PATCH /api/v1/products/{fake_id} returns 404."""
    fake_id = uuid.uuid4()
    resp = await api_client.patch(
        f"/api/v1/products/{fake_id}",
        json={"name": "Ghost"},
    )
    # Returns 403 (access check fails before 404) or 404
    assert resp.status_code in (403, 404)


@pytest.mark.anyio
async def test_delete_product(api_client: AsyncClient, test_subscription, db_session, test_user, test_org):
    """DELETE /api/v1/products/{id} deletes a product."""
    from app.domain.product_operations import product_ops

    # Create a throwaway product to delete (preserve test_product for other tests)
    throwaway = await product_ops.create(
        db_session,
        obj_in={
            "name": f"Throwaway {uuid.uuid4().hex[:8]}",
            "description": "To be deleted",
            "organization_id": test_org.id,
        },
        user_id=test_user.id,
    )
    resp = await api_client.delete(f"/api/v1/products/{throwaway.id}")
    assert resp.status_code == 204
