"""Product API authorization boundary tests.

Verifies that product endpoints properly enforce:
- 401 for unauthenticated requests
- 403/404 for non-members accessing another org's products
- 403 for viewers attempting write operations
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


class TestProductsRequireAuth:
    """All product endpoints require authentication."""

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("get", "/api/v1/products/", None),
            ("get", f"/api/v1/products/{FAKE_ID}", None),
            ("post", "/api/v1/products/", {"name": "x"}),
            ("patch", f"/api/v1/products/{FAKE_ID}", {"name": "x"}),
            ("delete", f"/api/v1/products/{FAKE_ID}", None),
            # Sub-endpoints
            ("post", f"/api/v1/products/{FAKE_ID}/analyze", None),
            ("post", f"/api/v1/products/{FAKE_ID}/generate-docs", {"mode": "full"}),
            ("get", f"/api/v1/products/{FAKE_ID}/docs-status", None),
            ("post", f"/api/v1/products/{FAKE_ID}/reset-docs-generation", None),
            ("get", f"/api/v1/products/{FAKE_ID}/access", None),
            ("get", f"/api/v1/products/{FAKE_ID}/collaborators", None),
            (
                "post",
                f"/api/v1/products/{FAKE_ID}/collaborators",
                {"user_id": str(uuid.uuid4()), "access_level": "viewer"},
            ),
            (
                "delete",
                f"/api/v1/products/{FAKE_ID}/collaborators/{uuid.uuid4()}",
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


class TestProductsNonMemberBlocked:
    """Non-members cannot access products in another org."""

    @pytest.mark.anyio
    async def test_get_product(
        self, second_user_client: AsyncClient, test_product, test_subscription
    ):
        await assert_non_member_blocked(
            second_user_client, "get", f"/api/v1/products/{test_product.id}"
        )

    @pytest.mark.anyio
    async def test_update_product(
        self, second_user_client: AsyncClient, test_product, test_subscription
    ):
        await assert_non_member_blocked(
            second_user_client,
            "patch",
            f"/api/v1/products/{test_product.id}",
            json={"name": "hacked"},
        )

    @pytest.mark.anyio
    async def test_delete_product(
        self, second_user_client: AsyncClient, test_product, test_subscription
    ):
        await assert_non_member_blocked(
            second_user_client, "delete", f"/api/v1/products/{test_product.id}"
        )

    @pytest.mark.anyio
    async def test_analyze_product(
        self, second_user_client: AsyncClient, test_product, test_subscription
    ):
        await assert_non_member_blocked(
            second_user_client, "post", f"/api/v1/products/{test_product.id}/analyze"
        )

    @pytest.mark.anyio
    async def test_generate_docs(
        self, second_user_client: AsyncClient, test_product, test_subscription
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            f"/api/v1/products/{test_product.id}/generate-docs",
            json={"mode": "full"},
        )

    @pytest.mark.anyio
    async def test_docs_status(
        self, second_user_client: AsyncClient, test_product, test_subscription
    ):
        await assert_non_member_blocked(
            second_user_client, "get", f"/api/v1/products/{test_product.id}/docs-status"
        )

    @pytest.mark.anyio
    async def test_get_collaborators(
        self, second_user_client: AsyncClient, test_product, test_subscription
    ):
        await assert_non_member_blocked(
            second_user_client,
            "get",
            f"/api/v1/products/{test_product.id}/collaborators",
        )

    @pytest.mark.anyio
    async def test_add_collaborator(
        self, second_user_client: AsyncClient, test_product, test_subscription
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            f"/api/v1/products/{test_product.id}/collaborators",
            json={"user_id": str(uuid.uuid4()), "access_level": "viewer"},
        )

    @pytest.mark.anyio
    async def test_reset_docs_generation(
        self, second_user_client: AsyncClient, test_product, test_subscription
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            f"/api/v1/products/{test_product.id}/reset-docs-generation",
        )

    @pytest.mark.anyio
    async def test_remove_collaborator(
        self, second_user_client: AsyncClient, test_product, test_subscription
    ):
        await assert_non_member_blocked(
            second_user_client,
            "delete",
            f"/api/v1/products/{test_product.id}/collaborators/{uuid.uuid4()}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# 403 — Viewer cannot write
# ─────────────────────────────────────────────────────────────────────────────


class TestProductsViewerCannotWrite:
    """Viewers can read products but cannot mutate them."""

    @pytest.mark.anyio
    async def test_create_product(self, viewer_client: AsyncClient, test_subscription):
        await assert_viewer_cannot_write(
            viewer_client, "post", "/api/v1/products/", json={"name": "sneaky"}
        )

    @pytest.mark.anyio
    async def test_update_product(
        self, viewer_client: AsyncClient, test_product, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "patch",
            f"/api/v1/products/{test_product.id}",
            json={"name": "sneaky"},
        )

    @pytest.mark.anyio
    async def test_delete_product(
        self, viewer_client: AsyncClient, test_product, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client, "delete", f"/api/v1/products/{test_product.id}"
        )

    @pytest.mark.anyio
    async def test_analyze_product(
        self, viewer_client: AsyncClient, test_product, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client, "post", f"/api/v1/products/{test_product.id}/analyze"
        )

    @pytest.mark.anyio
    async def test_generate_docs(self, viewer_client: AsyncClient, test_product, test_subscription):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            f"/api/v1/products/{test_product.id}/generate-docs",
            json={"mode": "full"},
        )

    @pytest.mark.anyio
    async def test_add_collaborator(
        self, viewer_client: AsyncClient, test_product, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            f"/api/v1/products/{test_product.id}/collaborators",
            json={"user_id": str(uuid.uuid4()), "access_level": "viewer"},
        )

    @pytest.mark.anyio
    async def test_reset_docs_generation(
        self, viewer_client: AsyncClient, test_product, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            f"/api/v1/products/{test_product.id}/reset-docs-generation",
        )

    @pytest.mark.anyio
    async def test_remove_collaborator(
        self, viewer_client: AsyncClient, test_product, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "delete",
            f"/api/v1/products/{test_product.id}/collaborators/{uuid.uuid4()}",
        )
