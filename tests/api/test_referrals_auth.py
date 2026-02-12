"""Referral API authorization boundary tests.

Some referral endpoints are public (validate, link).
Scoped endpoints require auth.
"""
# ruff: noqa: ARG002

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.helpers.auth_assertions import assert_requires_auth

FAKE_CODE = "TESTCODE123"


class TestReferralsRequireAuth:
    """Authenticated referral endpoints require auth."""

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("get", "/api/v1/referrals/codes", None),
            ("get", "/api/v1/referrals/stats", None),
            ("post", "/api/v1/referrals/codes", None),
            ("post", "/api/v1/referrals/redeem", {"code": FAKE_CODE}),
            ("get", f"/api/v1/referrals/link/{FAKE_CODE}", None),
        ],
    )
    async def test_unauth_returns_401(
        self, unauth_client: AsyncClient, method: str, url: str, body
    ):
        kwargs = {"json": body} if body else {}
        await assert_requires_auth(unauth_client, method, url, **kwargs)


class TestReferralsPublicEndpoints:
    """Validate endpoint works without auth."""

    @pytest.mark.anyio
    async def test_validate_no_auth(self, unauth_client: AsyncClient):
        resp = await unauth_client.get(f"/api/v1/referrals/validate/{FAKE_CODE}")
        # Should not be 401 — either 200 or 404 (code not found)
        assert resp.status_code != 401
