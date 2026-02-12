"""User API authorization boundary tests.

User endpoints are scoped to the authenticated user's own data.
"""
# ruff: noqa: ARG002

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.helpers.auth_assertions import assert_requires_auth

FAKE_ID = str(uuid.uuid4())


class TestUsersRequireAuth:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("get", "/api/v1/users/me", None),
            ("patch", "/api/v1/users/me", {"display_name": "x"}),
            ("get", "/api/v1/users/me/deletion-preview", None),
            ("delete", "/api/v1/users/me", None),
            ("post", "/api/v1/users/me/complete-onboarding", None),
            ("get", "/api/v1/users/me/onboarding-context", None),
        ],
    )
    async def test_unauth_returns_401(
        self, unauth_client: AsyncClient, method: str, url: str, body
    ):
        kwargs = {"json": body} if body else {}
        await assert_requires_auth(unauth_client, method, url, **kwargs)


class TestUsersReturnOwnData:
    """Users can only access their own data."""

    @pytest.mark.anyio
    async def test_me_returns_own_profile(self, api_client: AsyncClient, test_user):
        resp = await api_client.get("/api/v1/users/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(test_user.id)

    @pytest.mark.anyio
    async def test_second_user_gets_own_profile(
        self, second_user_client: AsyncClient, second_user
    ):
        resp = await second_user_client.get("/api/v1/users/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(second_user.id)
