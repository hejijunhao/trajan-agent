"""Feedback API authorization boundary tests."""
# ruff: noqa: ARG002

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.helpers.auth_assertions import assert_requires_auth

FAKE_ID = str(uuid.uuid4())


class TestFeedbackRequireAuth:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "method,url,body",
        [
            (
                "post",
                "/api/v1/feedback",
                {"type": "bug", "title": "t", "description": "d"},
            ),
            ("get", "/api/v1/feedback", None),
            ("get", f"/api/v1/feedback/{FAKE_ID}", None),
        ],
    )
    async def test_unauth_returns_401(
        self, unauth_client: AsyncClient, method: str, url: str, body
    ):
        kwargs = {"json": body} if body else {}
        await assert_requires_auth(unauth_client, method, url, **kwargs)


class TestFeedbackScopedToUser:
    """Users can only see their own feedback."""

    @pytest.mark.anyio
    async def test_other_user_feedback_not_visible(
        self,
        second_user_client: AsyncClient,
        test_feedback,
    ):
        """second_user should not see test_user's feedback."""
        resp = await second_user_client.get(
            f"/api/v1/feedback/{test_feedback.id}"
        )
        # Expect 404 (feedback scoped to user) or 403
        assert resp.status_code in (403, 404)
