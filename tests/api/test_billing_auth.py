"""Billing API authorization boundary tests.

/billing/plans is public (no auth).
All other billing endpoints require auth, and write operations
require owner/admin role in the organization.
"""
# ruff: noqa: ARG002

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.helpers.auth_assertions import (
    assert_non_member_blocked,
    assert_requires_auth,
    assert_viewer_cannot_write,
)

FAKE_ORG_ID = str(uuid.uuid4())


class TestBillingRequireAuth:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "method,url,body",
        [
            # /billing/plans is public — skip
            ("get", f"/api/v1/billing/subscription/{FAKE_ORG_ID}", None),
            (
                "post",
                "/api/v1/billing/checkout",
                {"plan_tier": "indie", "organization_id": FAKE_ORG_ID},
            ),
            ("post", "/api/v1/billing/portal", {"organization_id": FAKE_ORG_ID}),
            ("post", "/api/v1/billing/cancel", {"organization_id": FAKE_ORG_ID}),
            ("post", "/api/v1/billing/reactivate", {"organization_id": FAKE_ORG_ID}),
            (
                "post",
                "/api/v1/billing/downgrade",
                {
                    "organization_id": FAKE_ORG_ID,
                    "target_plan_tier": "indie",
                    "repos_to_keep": [],
                },
            ),
        ],
    )
    async def test_unauth_returns_401(
        self, unauth_client: AsyncClient, method: str, url: str, body
    ):
        kwargs = {"json": body} if body else {}
        await assert_requires_auth(unauth_client, method, url, **kwargs)


class TestBillingPlansPublic:
    """GET /billing/plans should be accessible without auth."""

    @pytest.mark.anyio
    async def test_plans_no_auth(self, unauth_client: AsyncClient):
        resp = await unauth_client.get("/api/v1/billing/plans")
        assert resp.status_code == 200


class TestBillingNonMemberBlocked:
    @pytest.mark.anyio
    async def test_get_subscription(
        self, second_user_client: AsyncClient, test_org, test_subscription
    ):
        await assert_non_member_blocked(
            second_user_client,
            "get",
            f"/api/v1/billing/subscription/{test_org.id}",
        )

    @pytest.mark.anyio
    async def test_checkout(
        self, second_user_client: AsyncClient, test_org, test_subscription
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            "/api/v1/billing/checkout",
            json={
                "plan_tier": "pro",
                "organization_id": str(test_org.id),
            },
        )

    @pytest.mark.anyio
    async def test_cancel(
        self, second_user_client: AsyncClient, test_org, test_subscription
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            "/api/v1/billing/cancel",
            json={"organization_id": str(test_org.id)},
        )

    @pytest.mark.anyio
    async def test_reactivate(
        self, second_user_client: AsyncClient, test_org, test_subscription
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            "/api/v1/billing/reactivate",
            json={"organization_id": str(test_org.id)},
        )


class TestBillingViewerCannotManage:
    """Viewers cannot perform billing operations (owner/admin only)."""

    @pytest.mark.anyio
    async def test_checkout(
        self, viewer_client: AsyncClient, test_org, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            "/api/v1/billing/checkout",
            json={
                "plan_tier": "pro",
                "organization_id": str(test_org.id),
            },
        )

    @pytest.mark.anyio
    async def test_cancel(
        self, viewer_client: AsyncClient, test_org, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            "/api/v1/billing/cancel",
            json={"organization_id": str(test_org.id)},
        )

    @pytest.mark.anyio
    async def test_reactivate(
        self, viewer_client: AsyncClient, test_org, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            "/api/v1/billing/reactivate",
            json={"organization_id": str(test_org.id)},
        )
