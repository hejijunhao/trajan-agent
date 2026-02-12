"""Admin API authorization boundary tests.

Admin endpoints must return 403 for non-admin users.
"""
# ruff: noqa: ARG002

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.helpers.auth_assertions import assert_requires_auth

FAKE_ID = str(uuid.uuid4())


class TestAdminRequireAuth:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("get", "/api/v1/admin/organizations", None),
            ("get", f"/api/v1/admin/organizations/{FAKE_ID}", None),
            ("get", f"/api/v1/admin/organizations/{FAKE_ID}/subscription", None),
            (
                "patch",
                f"/api/v1/admin/organizations/{FAKE_ID}/subscription",
                {"plan_tier": "pro"},
            ),
            ("get", "/api/v1/admin/plans", None),
        ],
    )
    async def test_unauth_returns_401(
        self, unauth_client: AsyncClient, method: str, url: str, body
    ):
        kwargs = {"json": body} if body else {}
        await assert_requires_auth(unauth_client, method, url, **kwargs)


class TestAdminRequiresSystemAdmin:
    """Regular authenticated users cannot access admin endpoints."""

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("get", "/api/v1/admin/organizations", None),
            ("get", f"/api/v1/admin/organizations/{FAKE_ID}", None),
            ("get", f"/api/v1/admin/organizations/{FAKE_ID}/subscription", None),
            ("get", "/api/v1/admin/plans", None),
            (
                "patch",
                f"/api/v1/admin/organizations/{FAKE_ID}/subscription",
                {"plan_tier": "pro"},
            ),
        ],
    )
    async def test_regular_user_gets_403(
        self, api_client: AsyncClient, method: str, url: str, body
    ):
        kwargs = {"json": body} if body else {}
        resp = await getattr(api_client, method)(url, **kwargs)
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_viewer_gets_403(self, viewer_client: AsyncClient, test_subscription):
        resp = await viewer_client.get("/api/v1/admin/organizations")
        assert resp.status_code == 403
