"""Timeline API authorization boundary tests."""
# ruff: noqa: ARG002

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.helpers.auth_assertions import (
    assert_non_member_blocked,
    assert_requires_auth,
)

FAKE_ID = str(uuid.uuid4())


# ─────────────────────────────────────────────────────────────────────────────
# 401 — Unauthenticated
# ─────────────────────────────────────────────────────────────────────────────


class TestTimelineRequireAuth:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("get", f"/api/v1/timeline/products/{FAKE_ID}", None),
            (
                "get",
                f"/api/v1/timeline/commits/owner/repo/{FAKE_ID}/files",
                None,
            ),
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


class TestTimelineNonMemberBlocked:
    @pytest.mark.anyio
    async def test_get_product_timeline(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "get",
            f"/api/v1/timeline/products/{test_product.id}",
        )
