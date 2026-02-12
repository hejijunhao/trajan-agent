"""Work Item API endpoint tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_list_work_items(
    api_client: AsyncClient, test_product, test_work_item, test_subscription
):
    """GET /api/v1/work-items/?product_id={id} returns work items."""
    resp = await api_client.get(
        "/api/v1/work-items/", params={"product_id": str(test_product.id)}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    item_ids = [i["id"] for i in data]
    assert str(test_work_item.id) in item_ids


@pytest.mark.anyio
async def test_get_work_item(
    api_client: AsyncClient, test_work_item, test_subscription
):
    """GET /api/v1/work-items/{id} returns the work item."""
    resp = await api_client.get(f"/api/v1/work-items/{test_work_item.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(test_work_item.id)
    assert data["title"] == test_work_item.title
    assert data["status"] == "todo"


@pytest.mark.anyio
async def test_get_work_item_not_found(api_client: AsyncClient, test_subscription):
    """GET /api/v1/work-items/{fake_id} returns 404."""
    resp = await api_client.get(f"/api/v1/work-items/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_create_work_item(
    api_client: AsyncClient, test_product, test_subscription
):
    """POST /api/v1/work-items/ creates a new work item."""
    resp = await api_client.post(
        "/api/v1/work-items/",
        json={
            "product_id": str(test_product.id),
            "title": f"New Task {uuid.uuid4().hex[:8]}",
            "type": "feature",
            "status": "todo",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert "title" in data


@pytest.mark.anyio
async def test_update_work_item(
    api_client: AsyncClient, test_work_item, test_subscription
):
    """PATCH /api/v1/work-items/{id} updates the work item."""
    resp = await api_client.patch(
        f"/api/v1/work-items/{test_work_item.id}",
        json={"status": "in_progress"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"


@pytest.mark.anyio
async def test_delete_work_item(
    api_client: AsyncClient, test_product, test_subscription, db_session, test_user
):
    """DELETE /api/v1/work-items/{id} deletes a work item."""
    from app.domain.work_item_operations import work_item_ops

    throwaway = await work_item_ops.create(
        db_session,
        obj_in={
            "product_id": test_product.id,
            "title": f"Throwaway {uuid.uuid4().hex[:8]}",
            "type": "feature",
            "status": "todo",
        },
        created_by_user_id=test_user.id,
    )
    resp = await api_client.delete(f"/api/v1/work-items/{throwaway.id}")
    assert resp.status_code == 204
