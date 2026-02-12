"""Agent API authorization boundary tests."""
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


class TestAgentRequireAuth:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "method,url,body",
        [
            (
                "post",
                "/api/v1/agent/chat",
                {
                    "product_id": FAKE_ID,
                    "messages": [{"role": "user", "content": "hello"}],
                },
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


class TestAgentNonMemberBlocked:
    @pytest.mark.anyio
    async def test_chat_other_product(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            "/api/v1/agent/chat",
            json={
                "product_id": str(test_product.id),
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
