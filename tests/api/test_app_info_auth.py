"""App Info API authorization boundary tests.

Special attention: the reveal endpoint must block non-members from
revealing sensitive values.
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
FAKE_PID = str(uuid.uuid4())


class TestAppInfoRequireAuth:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("get", f"/api/v1/app-info?product_id={FAKE_PID}", None),
            ("get", f"/api/v1/app-info/tags?product_id={FAKE_PID}", None),
            ("get", f"/api/v1/app-info/export?product_id={FAKE_PID}", None),
            ("get", f"/api/v1/app-info/{FAKE_ID}", None),
            (
                "post",
                "/api/v1/app-info",
                {
                    "product_id": FAKE_PID,
                    "key": "K",
                    "value": "V",
                    "category": "env_var",
                },
            ),
            ("patch", f"/api/v1/app-info/{FAKE_ID}", {"value": "V"}),
            ("delete", f"/api/v1/app-info/{FAKE_ID}", None),
            ("get", f"/api/v1/app-info/{FAKE_ID}/reveal", None),
            (
                "post",
                "/api/v1/app-info/bulk",
                {"product_id": FAKE_PID, "entries": []},
            ),
        ],
    )
    async def test_unauth_returns_401(
        self, unauth_client: AsyncClient, method: str, url: str, body
    ):
        kwargs = {"json": body} if body else {}
        await assert_requires_auth(unauth_client, method, url, **kwargs)


class TestAppInfoNonMemberBlocked:
    @pytest.mark.anyio
    async def test_list(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_app_info_entry,
        test_subscription,
    ):
        resp = await second_user_client.get(
            f"/api/v1/app-info?product_id={test_product.id}"
        )
        assert resp.status_code in (403, 404)

    @pytest.mark.anyio
    async def test_reveal_blocked(
        self,
        second_user_client: AsyncClient,
        test_app_info_entry,
        test_subscription,
    ):
        """Non-members must not be able to reveal sensitive values."""
        await assert_non_member_blocked(
            second_user_client,
            "get",
            f"/api/v1/app-info/{test_app_info_entry.id}/reveal",
        )

    @pytest.mark.anyio
    async def test_create(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            "/api/v1/app-info",
            json={
                "product_id": str(test_product.id),
                "key": "EVIL",
                "value": "val",
                "category": "env_var",
            },
        )


class TestAppInfoViewerCannotWrite:
    """Viewers cannot access environment variables (editor+ required)."""

    @pytest.mark.anyio
    async def test_list_blocked(
        self,
        viewer_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        """Viewers are blocked from the Variables tab entirely."""
        resp = await viewer_client.get(
            f"/api/v1/app-info?product_id={test_product.id}"
        )
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_create(
        self,
        viewer_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            "/api/v1/app-info",
            json={
                "product_id": str(test_product.id),
                "key": "SNEAKY",
                "value": "val",
                "category": "env_var",
            },
        )

    @pytest.mark.anyio
    async def test_delete(
        self,
        viewer_client: AsyncClient,
        test_app_info_entry,
        test_subscription,
    ):
        await assert_viewer_cannot_write(
            viewer_client, "delete", f"/api/v1/app-info/{test_app_info_entry.id}"
        )
