"""Feedback API endpoint tests."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.fixture(autouse=True)
def mock_feedback_interpreter():
    """Prevent real AI calls during feedback submission."""
    with patch("app.api.v1.feedback.FeedbackInterpreter") as mock:
        mock.return_value.interpret = AsyncMock(return_value="Test summary")
        yield mock


@pytest.mark.anyio
async def test_submit_feedback(api_client: AsyncClient):
    """POST /api/v1/feedback/ submits feedback."""
    resp = await api_client.post(
        "/api/v1/feedback/",
        json={
            "type": "bug",
            "title": f"Test Bug {uuid.uuid4().hex[:8]}",
            "description": "Something is broken.",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["type"] == "bug"
    assert "title" in data


@pytest.mark.anyio
async def test_list_feedback(api_client: AsyncClient, test_feedback):
    """GET /api/v1/feedback/ returns user's feedback."""
    resp = await api_client.get("/api/v1/feedback/")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    ids = [f["id"] for f in data]
    assert str(test_feedback.id) in ids


@pytest.mark.anyio
async def test_get_feedback(api_client: AsyncClient, test_feedback):
    """GET /api/v1/feedback/{id} returns the feedback item."""
    resp = await api_client.get(f"/api/v1/feedback/{test_feedback.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(test_feedback.id)
    assert data["title"] == test_feedback.title


@pytest.mark.anyio
async def test_get_feedback_not_found(api_client: AsyncClient):
    """GET /api/v1/feedback/{fake_id} returns 404."""
    resp = await api_client.get(f"/api/v1/feedback/{uuid.uuid4()}")
    assert resp.status_code == 404
