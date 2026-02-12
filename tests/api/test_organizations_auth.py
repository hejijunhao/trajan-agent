"""Organization API authorization boundary tests.

Organization endpoints use require_org_access with min_role checks.
Non-members get 403, members below min_role get 403.
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

FAKE_ID = str(uuid.uuid4())


# ─────────────────────────────────────────────────────────────────────────────
# 401 — Unauthenticated
# ─────────────────────────────────────────────────────────────────────────────


class TestOrganizationsRequireAuth:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("get", "/api/v1/organizations", None),
            ("post", "/api/v1/organizations", {"name": "x"}),
            ("get", "/api/v1/organizations/plans", None),
            ("get", f"/api/v1/organizations/{FAKE_ID}", None),
            ("patch", f"/api/v1/organizations/{FAKE_ID}", {"name": "x"}),
            ("delete", f"/api/v1/organizations/{FAKE_ID}", None),
            (
                "post",
                f"/api/v1/organizations/{FAKE_ID}/transfer-ownership",
                {"new_owner_id": str(uuid.uuid4())},
            ),
            # Members
            ("get", f"/api/v1/organizations/{FAKE_ID}/members", None),
            (
                "post",
                f"/api/v1/organizations/{FAKE_ID}/members",
                {"email": "a@b.com", "role": "member"},
            ),
            (
                "patch",
                f"/api/v1/organizations/{FAKE_ID}/members/{uuid.uuid4()}",
                {"role": "member"},
            ),
            ("delete", f"/api/v1/organizations/{FAKE_ID}/members/{uuid.uuid4()}", None),
            (
                "post",
                f"/api/v1/organizations/{FAKE_ID}/members/{uuid.uuid4()}/resend-invite",
                None,
            ),
            # Member access
            (
                "get",
                f"/api/v1/organizations/{FAKE_ID}/members/{uuid.uuid4()}/product-access",
                None,
            ),
            # Settings
            ("get", f"/api/v1/organizations/{FAKE_ID}/settings", None),
            ("patch", f"/api/v1/organizations/{FAKE_ID}/settings", {"key": "val"}),
            # Subscriptions
            ("get", f"/api/v1/organizations/{FAKE_ID}/subscription", None),
            (
                "get",
                f"/api/v1/organizations/{FAKE_ID}/repo-limit-status",
                None,
            ),
            # Repositories
            ("get", f"/api/v1/organizations/{FAKE_ID}/repositories", None),
        ],
    )
    async def test_unauth_returns_401(
        self, unauth_client: AsyncClient, method: str, url: str, body
    ):
        kwargs = {"json": body} if body else {}
        await assert_requires_auth(unauth_client, method, url, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# 403/404 — Non-member
# ─────────────────────────────────────────────────────────────────────────────


class TestOrganizationsNonMemberBlocked:
    @pytest.mark.anyio
    async def test_get_org(self, second_user_client: AsyncClient, test_org, test_subscription):
        await assert_non_member_blocked(
            second_user_client, "get", f"/api/v1/organizations/{test_org.id}"
        )

    @pytest.mark.anyio
    async def test_update_org(self, second_user_client: AsyncClient, test_org, test_subscription):
        await assert_non_member_blocked(
            second_user_client,
            "patch",
            f"/api/v1/organizations/{test_org.id}",
            json={"name": "hacked"},
        )

    @pytest.mark.anyio
    async def test_delete_org(self, second_user_client: AsyncClient, test_org, test_subscription):
        await assert_non_member_blocked(
            second_user_client, "delete", f"/api/v1/organizations/{test_org.id}"
        )

    @pytest.mark.anyio
    async def test_list_members(self, second_user_client: AsyncClient, test_org, test_subscription):
        await assert_non_member_blocked(
            second_user_client, "get", f"/api/v1/organizations/{test_org.id}/members"
        )

    @pytest.mark.anyio
    async def test_add_member(self, second_user_client: AsyncClient, test_org, test_subscription):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            f"/api/v1/organizations/{test_org.id}/members",
            json={"email": "intruder@evil.com", "role": "admin"},
        )

    @pytest.mark.anyio
    async def test_get_settings(self, second_user_client: AsyncClient, test_org, test_subscription):
        await assert_non_member_blocked(
            second_user_client, "get", f"/api/v1/organizations/{test_org.id}/settings"
        )

    @pytest.mark.anyio
    async def test_get_subscription(
        self, second_user_client: AsyncClient, test_org, test_subscription
    ):
        await assert_non_member_blocked(
            second_user_client,
            "get",
            f"/api/v1/organizations/{test_org.id}/subscription",
        )

    @pytest.mark.anyio
    async def test_get_repositories(
        self, second_user_client: AsyncClient, test_org, test_subscription
    ):
        await assert_non_member_blocked(
            second_user_client,
            "get",
            f"/api/v1/organizations/{test_org.id}/repositories",
        )


# ─────────────────────────────────────────────────────────────────────────────
# 403 — Viewer cannot perform admin actions
# ─────────────────────────────────────────────────────────────────────────────


class TestOrganizationsViewerCannotAdmin:
    """Viewer members cannot perform admin-only org operations."""

    @pytest.mark.anyio
    async def test_update_org(self, viewer_client: AsyncClient, test_org, test_subscription):
        await assert_viewer_cannot_write(
            viewer_client,
            "patch",
            f"/api/v1/organizations/{test_org.id}",
            json={"name": "sneaky"},
        )

    @pytest.mark.anyio
    async def test_delete_org(self, viewer_client: AsyncClient, test_org, test_subscription):
        await assert_viewer_cannot_write(
            viewer_client, "delete", f"/api/v1/organizations/{test_org.id}"
        )

    @pytest.mark.anyio
    async def test_add_member(self, viewer_client: AsyncClient, test_org, test_subscription):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            f"/api/v1/organizations/{test_org.id}/members",
            json={"email": "sneaky@evil.com", "role": "member"},
        )

    @pytest.mark.anyio
    async def test_update_settings(self, viewer_client: AsyncClient, test_org, test_subscription):
        await assert_viewer_cannot_write(
            viewer_client,
            "patch",
            f"/api/v1/organizations/{test_org.id}/settings",
            json={"key": "val"},
        )

    @pytest.mark.anyio
    async def test_transfer_ownership(
        self, viewer_client: AsyncClient, test_org, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            f"/api/v1/organizations/{test_org.id}/transfer-ownership",
            json={"new_owner_id": str(uuid.uuid4())},
        )
