"""App Info API endpoint tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_list_app_info(
    api_client: AsyncClient, test_product, test_app_info_entry, test_subscription
):
    """GET /api/v1/app-info/?product_id={id} returns entries."""
    resp = await api_client.get(
        "/api/v1/app-info/", params={"product_id": str(test_product.id)}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    entry_ids = [e["id"] for e in data]
    assert str(test_app_info_entry.id) in entry_ids


@pytest.mark.anyio
async def test_get_app_info(
    api_client: AsyncClient, test_app_info_entry, test_subscription
):
    """GET /api/v1/app-info/{id} returns the entry."""
    resp = await api_client.get(f"/api/v1/app-info/{test_app_info_entry.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["key"] == test_app_info_entry.key
    assert data["value"] == test_app_info_entry.value


@pytest.mark.anyio
async def test_create_app_info(
    api_client: AsyncClient, test_product, test_subscription
):
    """POST /api/v1/app-info/ creates a new entry."""
    resp = await api_client.post(
        "/api/v1/app-info/",
        json={
            "product_id": str(test_product.id),
            "key": f"NEW_KEY_{uuid.uuid4().hex[:8]}",
            "value": "new_value",
            "category": "env_var",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert "key" in data


@pytest.mark.anyio
async def test_create_secret_app_info(
    api_client: AsyncClient, test_product, test_subscription
):
    """POST /api/v1/app-info/ with is_secret returns masked value."""
    resp = await api_client.post(
        "/api/v1/app-info/",
        json={
            "product_id": str(test_product.id),
            "key": f"SECRET_{uuid.uuid4().hex[:8]}",
            "value": "super_secret_value",
            "category": "env_var",
            "is_secret": True,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["value"] == "********"
    assert data["is_secret"] is True


@pytest.mark.anyio
async def test_update_app_info(
    api_client: AsyncClient, test_app_info_entry, test_subscription
):
    """PATCH /api/v1/app-info/{id} updates the entry."""
    resp = await api_client.patch(
        f"/api/v1/app-info/{test_app_info_entry.id}",
        json={"value": "updated_value"},
    )
    assert resp.status_code == 200
    assert resp.json()["value"] == "updated_value"


@pytest.mark.anyio
async def test_delete_app_info(
    api_client: AsyncClient, test_product, test_subscription, db_session, test_user
):
    """DELETE /api/v1/app-info/{id} deletes the entry."""
    from app.domain.app_info_operations import app_info_ops

    throwaway = await app_info_ops.create(
        db_session,
        obj_in={
            "product_id": test_product.id,
            "key": f"DEL_{uuid.uuid4().hex[:8]}",
            "value": "to_delete",
            "category": "env_var",
        },
        user_id=test_user.id,
    )
    resp = await api_client.delete(f"/api/v1/app-info/{throwaway.id}")
    assert resp.status_code == 204


@pytest.mark.anyio
async def test_get_tags(
    api_client: AsyncClient, test_product, test_app_info_entry, test_subscription
):
    """GET /api/v1/app-info/tags?product_id={id} returns tag list."""
    resp = await api_client.get(
        "/api/v1/app-info/tags", params={"product_id": str(test_product.id)}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "tags" in data
    assert isinstance(data["tags"], list)


@pytest.mark.anyio
async def test_bulk_create(
    api_client: AsyncClient, test_product, test_app_info_entry, test_subscription
):
    """POST /api/v1/app-info/bulk creates entries, skipping duplicates."""
    resp = await api_client.post(
        "/api/v1/app-info/bulk",
        json={
            "product_id": str(test_product.id),
            "entries": [
                {"key": f"BULK_NEW_{uuid.uuid4().hex[:8]}", "value": "v1"},
                {"key": test_app_info_entry.key, "value": "duplicate"},
            ],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "created" in data
    assert "skipped" in data
    assert len(data["created"]) >= 1
    assert len(data["skipped"]) >= 1
