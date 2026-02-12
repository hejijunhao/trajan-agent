"""Document API endpoint tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_list_documents_by_product(
    api_client: AsyncClient, test_product, test_document, test_subscription
):
    """GET /api/v1/documents/?product_id={id} returns product documents."""
    resp = await api_client.get(
        "/api/v1/documents/", params={"product_id": str(test_product.id)}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    doc_ids = [d["id"] for d in data]
    assert str(test_document.id) in doc_ids


@pytest.mark.anyio
async def test_get_document(
    api_client: AsyncClient, test_document, test_subscription
):
    """GET /api/v1/documents/{id} returns the document."""
    resp = await api_client.get(f"/api/v1/documents/{test_document.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(test_document.id)
    assert data["title"] == test_document.title
    assert data["product_id"] == str(test_document.product_id)


@pytest.mark.anyio
async def test_get_document_not_found(api_client: AsyncClient, test_subscription):
    """GET /api/v1/documents/{fake_id} returns 404."""
    resp = await api_client.get(f"/api/v1/documents/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_create_document(
    api_client: AsyncClient, test_product, test_subscription
):
    """POST /api/v1/documents/ creates a document with is_generated=True."""
    resp = await api_client.post(
        "/api/v1/documents/",
        json={
            "product_id": str(test_product.id),
            "title": f"New Doc {uuid.uuid4().hex[:8]}",
            "content": "Created via API test",
            "type": "note",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["is_generated"] is True


@pytest.mark.anyio
async def test_update_document(
    api_client: AsyncClient, test_document, test_subscription
):
    """PATCH /api/v1/documents/{id} updates the document."""
    new_title = f"Updated {uuid.uuid4().hex[:8]}"
    resp = await api_client.patch(
        f"/api/v1/documents/{test_document.id}",
        json={"title": new_title},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == new_title


@pytest.mark.anyio
async def test_delete_document(
    api_client: AsyncClient, test_product, test_subscription, db_session, test_user
):
    """DELETE /api/v1/documents/{id} deletes a document."""
    from app.domain.document_operations import document_ops

    throwaway = await document_ops.create(
        db_session,
        obj_in={
            "product_id": test_product.id,
            "title": f"Throwaway {uuid.uuid4().hex[:8]}",
            "type": "note",
            "is_generated": True,
        },
        created_by_user_id=test_user.id,
    )
    resp = await api_client.delete(f"/api/v1/documents/{throwaway.id}")
    assert resp.status_code == 204


@pytest.mark.anyio
async def test_archive_document(
    api_client: AsyncClient, test_product, test_subscription, db_session, test_user
):
    """POST /api/v1/documents/{id}/archive moves to archive folder."""
    from app.domain.document_operations import document_ops

    doc = await document_ops.create(
        db_session,
        obj_in={
            "product_id": test_product.id,
            "title": f"To Archive {uuid.uuid4().hex[:8]}",
            "type": "note",
            "is_generated": True,
        },
        created_by_user_id=test_user.id,
    )
    resp = await api_client.post(f"/api/v1/documents/{doc.id}/archive")
    assert resp.status_code == 200
    data = resp.json()
    assert data["folder"] is not None
