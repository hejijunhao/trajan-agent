"""Progress API authorization boundary tests."""
# ruff: noqa: ARG002

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.helpers.auth_assertions import (
    assert_requires_auth,
)

FAKE_ID = str(uuid.uuid4())


class TestProgressRequireAuth:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("get", "/api/v1/progress/dashboard", None),
            ("post", "/api/v1/progress/dashboard/generate", None),
        ],
    )
    async def test_unauth_returns_401(
        self, unauth_client: AsyncClient, method: str, url: str, body
    ):
        kwargs = {"json": body} if body else {}
        await assert_requires_auth(unauth_client, method, url, **kwargs)


class TestProgressNonMemberBlocked:
    @pytest.mark.anyio
    async def test_dashboard_with_other_org(
        self, second_user_client: AsyncClient, test_org, test_subscription
    ):
        """Non-member cannot access dashboard scoped to another org."""
        resp = await second_user_client.get(
            f"/api/v1/progress/dashboard?organization_id={test_org.id}"
        )
        assert resp.status_code in (403, 404)
