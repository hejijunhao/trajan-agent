"""Preferences API authorization boundary tests.

Preferences are user-scoped (/users/me/preferences), so non-member tests
don't apply — only 401 (unauthenticated) tests are needed.
"""
# ruff: noqa: ARG002

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.helpers.auth_assertions import assert_requires_auth

# ─────────────────────────────────────────────────────────────────────────────
# 401 — Unauthenticated
# ─────────────────────────────────────────────────────────────────────────────


class TestPreferencesRequireAuth:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("get", "/api/v1/users/me/preferences", None),
            (
                "patch",
                "/api/v1/users/me/preferences",
                {"default_view": "list"},
            ),
            (
                "post",
                "/api/v1/users/me/preferences/test-github-token",
                {"token": "ghp_test"},
            ),
        ],
    )
    async def test_unauth_returns_401(
        self, unauth_client: AsyncClient, method: str, url: str, body
    ):
        kwargs = {"json": body} if body else {}
        await assert_requires_auth(unauth_client, method, url, **kwargs)
