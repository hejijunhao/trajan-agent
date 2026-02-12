"""Work Item API authorization boundary tests."""
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


class TestWorkItemsRequireAuth:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("get", f"/api/v1/work-items?product_id={FAKE_ID}", None),
            ("get", f"/api/v1/work-items/{FAKE_ID}", None),
            (
                "post",
                "/api/v1/work-items",
                {
                    "product_id": FAKE_ID,
                    "title": "t",
                    "type": "feature",
                    "status": "todo",
                },
            ),
            ("patch", f"/api/v1/work-items/{FAKE_ID}", {"title": "t"}),
            ("delete", f"/api/v1/work-items/{FAKE_ID}", None),
        ],
    )
    async def test_unauth_returns_401(
        self, unauth_client: AsyncClient, method: str, url: str, body
    ):
        kwargs = {"json": body} if body else {}
        await assert_requires_auth(unauth_client, method, url, **kwargs)


class TestWorkItemsNonMemberBlocked:
    @pytest.mark.anyio
    async def test_list_work_items(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_work_item,
        test_subscription,
    ):
        resp = await second_user_client.get(
            f"/api/v1/work-items?product_id={test_product.id}"
        )
        assert resp.status_code in (403, 404)

    @pytest.mark.anyio
    async def test_get_work_item(
        self,
        second_user_client: AsyncClient,
        test_work_item,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client, "get", f"/api/v1/work-items/{test_work_item.id}"
        )

    @pytest.mark.anyio
    async def test_create_work_item(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            "/api/v1/work-items",
            json={
                "product_id": str(test_product.id),
                "title": "evil",
                "type": "feature",
                "status": "todo",
            },
        )

    @pytest.mark.anyio
    async def test_update_work_item(
        self,
        second_user_client: AsyncClient,
        test_work_item,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "patch",
            f"/api/v1/work-items/{test_work_item.id}",
            json={"title": "hacked"},
        )

    @pytest.mark.anyio
    async def test_delete_work_item(
        self,
        second_user_client: AsyncClient,
        test_work_item,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client, "delete", f"/api/v1/work-items/{test_work_item.id}"
        )


class TestWorkItemsViewerCannotWrite:
    @pytest.mark.anyio
    async def test_create_work_item(
        self, viewer_client: AsyncClient, test_product, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            "/api/v1/work-items",
            json={
                "product_id": str(test_product.id),
                "title": "sneaky",
                "type": "feature",
                "status": "todo",
            },
        )

    @pytest.mark.anyio
    async def test_update_work_item(
        self,
        viewer_client: AsyncClient,
        test_work_item,
        test_subscription,
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "patch",
            f"/api/v1/work-items/{test_work_item.id}",
            json={"title": "sneaky"},
        )

    @pytest.mark.anyio
    async def test_delete_work_item(
        self,
        viewer_client: AsyncClient,
        test_work_item,
        test_subscription,
    ):
        await assert_viewer_cannot_write(
            viewer_client, "delete", f"/api/v1/work-items/{test_work_item.id}"
        )
