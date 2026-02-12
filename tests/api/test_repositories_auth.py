"""Repository API authorization boundary tests."""
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


class TestRepositoriesRequireAuth:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("get", f"/api/v1/repositories?product_id={FAKE_ID}", None),
            ("get", f"/api/v1/repositories/{FAKE_ID}", None),
            (
                "post",
                "/api/v1/repositories",
                {"product_id": FAKE_ID, "name": "r", "full_name": "o/r"},
            ),
            ("patch", f"/api/v1/repositories/{FAKE_ID}", {"name": "r"}),
            ("delete", f"/api/v1/repositories/{FAKE_ID}", None),
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


class TestRepositoriesNonMemberBlocked:
    @pytest.mark.anyio
    async def test_list_repos(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_repository,
        test_subscription,
    ):
        resp = await second_user_client.get(
            f"/api/v1/repositories?product_id={test_product.id}"
        )
        # Non-member gets 403 from product access check
        assert resp.status_code in (403, 404)

    @pytest.mark.anyio
    async def test_get_repo(
        self,
        second_user_client: AsyncClient,
        test_repository,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client, "get", f"/api/v1/repositories/{test_repository.id}"
        )

    @pytest.mark.anyio
    async def test_create_repo(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            "/api/v1/repositories",
            json={
                "product_id": str(test_product.id),
                "name": "evil-repo",
                "full_name": "evil/repo",
            },
        )

    @pytest.mark.anyio
    async def test_update_repo(
        self,
        second_user_client: AsyncClient,
        test_repository,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "patch",
            f"/api/v1/repositories/{test_repository.id}",
            json={"name": "hacked"},
        )

    @pytest.mark.anyio
    async def test_delete_repo(
        self,
        second_user_client: AsyncClient,
        test_repository,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client, "delete", f"/api/v1/repositories/{test_repository.id}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 403 — Viewer cannot write
# ─────────────────────────────────────────────────────────────────────────────


class TestRepositoriesViewerCannotWrite:
    @pytest.mark.anyio
    async def test_create_repo(
        self, viewer_client: AsyncClient, test_product, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            "/api/v1/repositories",
            json={
                "product_id": str(test_product.id),
                "name": "sneaky-repo",
                "full_name": "sneaky/repo",
            },
        )

    @pytest.mark.anyio
    async def test_update_repo(
        self,
        viewer_client: AsyncClient,
        test_repository,
        test_subscription,
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "patch",
            f"/api/v1/repositories/{test_repository.id}",
            json={"name": "sneaky"},
        )

    @pytest.mark.anyio
    async def test_delete_repo(
        self,
        viewer_client: AsyncClient,
        test_repository,
        test_subscription,
    ):
        await assert_viewer_cannot_write(
            viewer_client, "delete", f"/api/v1/repositories/{test_repository.id}"
        )
