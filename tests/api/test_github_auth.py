"""GitHub API authorization boundary tests.

GitHub endpoints are currently untested (Issue #6).
Auth tests provide minimum coverage.
"""
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


class TestGitHubRequireAuth:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("get", "/api/v1/github/repos", None),
            ("post", "/api/v1/github/import", {"product_id": FAKE_ID, "github_ids": []}),
            ("post", f"/api/v1/github/refresh/{FAKE_ID}", None),
            ("post", "/api/v1/github/refresh-all", {"product_id": FAKE_ID}),
        ],
    )
    async def test_unauth_returns_401(
        self, unauth_client: AsyncClient, method: str, url: str, body
    ):
        kwargs = {"json": body} if body else {}
        await assert_requires_auth(unauth_client, method, url, **kwargs)


class TestGitHubNonMemberBlocked:
    @pytest.mark.anyio
    async def test_import_to_other_product(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            "/api/v1/github/import",
            json={"product_id": str(test_product.id), "github_ids": []},
        )

    @pytest.mark.anyio
    async def test_refresh_all_other_product(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            "/api/v1/github/refresh-all",
            json={"product_id": str(test_product.id)},
        )

    @pytest.mark.anyio
    async def test_refresh_other_repo(
        self,
        second_user_client: AsyncClient,
        test_repository,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            f"/api/v1/github/refresh/{test_repository.id}",
        )
