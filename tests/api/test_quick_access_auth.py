"""Quick Access API authorization boundary tests.

Some quick access endpoints are token-based (pseudo-public for shared links),
while management endpoints require product admin access.
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
FAKE_TOKEN = "fake-token-12345"


class TestQuickAccessRequireAuth:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("get", f"/api/v1/quick-access/products/{FAKE_ID}", None),
            ("post", f"/api/v1/quick-access/products/{FAKE_ID}/enable", None),
            ("post", f"/api/v1/quick-access/products/{FAKE_ID}/disable", None),
            ("post", f"/api/v1/quick-access/products/{FAKE_ID}/regenerate", None),
            ("get", f"/api/v1/quick-access/{FAKE_TOKEN}", None),
            ("get", f"/api/v1/quick-access/{FAKE_TOKEN}/entries", None),
            (
                "get",
                f"/api/v1/quick-access/{FAKE_TOKEN}/entries/{FAKE_ID}/reveal",
                None,
            ),
        ],
    )
    async def test_unauth_returns_401(
        self, unauth_client: AsyncClient, method: str, url: str, body
    ):
        kwargs = {"json": body} if body else {}
        await assert_requires_auth(unauth_client, method, url, **kwargs)


class TestQuickAccessNonMemberBlocked:
    @pytest.mark.anyio
    async def test_get_product_quick_access(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "get",
            f"/api/v1/quick-access/products/{test_product.id}",
        )


class TestQuickAccessViewerCannotManage:
    @pytest.mark.anyio
    async def test_enable(
        self, viewer_client: AsyncClient, test_product, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            f"/api/v1/quick-access/products/{test_product.id}/enable",
        )

    @pytest.mark.anyio
    async def test_disable(
        self, viewer_client: AsyncClient, test_product, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            f"/api/v1/quick-access/products/{test_product.id}/disable",
        )

    @pytest.mark.anyio
    async def test_regenerate(
        self, viewer_client: AsyncClient, test_product, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            f"/api/v1/quick-access/products/{test_product.id}/regenerate",
        )
