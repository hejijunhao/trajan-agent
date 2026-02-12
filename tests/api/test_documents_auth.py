"""Document API authorization boundary tests."""
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


class TestDocumentsRequireAuth:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "method,url,body",
        [
            # CRUD
            ("get", f"/api/v1/documents?product_id={FAKE_ID}", None),
            ("get", f"/api/v1/documents/{FAKE_ID}", None),
            (
                "post",
                "/api/v1/documents",
                {
                    "product_id": FAKE_ID,
                    "title": "t",
                    "content": "c",
                    "type": "note",
                },
            ),
            ("patch", f"/api/v1/documents/{FAKE_ID}", {"title": "t"}),
            ("delete", f"/api/v1/documents/{FAKE_ID}", None),
            # Grouped & changelog
            ("get", f"/api/v1/documents/products/{FAKE_ID}/grouped", None),
            (
                "post",
                f"/api/v1/documents/products/{FAKE_ID}/changelog/add-entry",
                {"entries": []},
            ),
            ("delete", f"/api/v1/documents/products/{FAKE_ID}/generated", None),
            # Lifecycle
            ("post", f"/api/v1/documents/{FAKE_ID}/move-to-executing", None),
            ("post", f"/api/v1/documents/{FAKE_ID}/move-to-completed", None),
            ("post", f"/api/v1/documents/{FAKE_ID}/archive", None),
            # Sections
            ("get", f"/api/v1/documents/products/{FAKE_ID}/sections", None),
            (
                "post",
                f"/api/v1/documents/products/{FAKE_ID}/sections",
                {"name": "s"},
            ),
            ("patch", f"/api/v1/documents/sections/{FAKE_ID}", {"name": "s"}),
            ("delete", f"/api/v1/documents/sections/{FAKE_ID}", None),
            # Custom doc generation
            (
                "post",
                f"/api/v1/documents/products/{FAKE_ID}/custom/generate",
                {"prompt": "test"},
            ),
            (
                "get",
                f"/api/v1/documents/products/{FAKE_ID}/custom/status/{FAKE_ID}",
                None,
            ),
            # Repo docs
            ("get", f"/api/v1/documents/products/{FAKE_ID}/repo-docs-tree", None),
            (
                "get",
                f"/api/v1/documents/repositories/{FAKE_ID}/file-content?path=README.md",
                None,
            ),
            # Sync & refresh
            ("post", f"/api/v1/documents/products/{FAKE_ID}/import-docs", None),
            ("get", f"/api/v1/documents/products/{FAKE_ID}/docs-sync-status", None),
            ("post", f"/api/v1/documents/{FAKE_ID}/refresh", None),
            # Phase 5: Previously uncovered endpoints
            ("post", f"/api/v1/documents/products/{FAKE_ID}/refresh-all-docs", None),
            ("post", f"/api/v1/documents/{FAKE_ID}/pull-remote", None),
            ("post", f"/api/v1/documents/products/{FAKE_ID}/sync-docs", None),
            (
                "delete",
                f"/api/v1/documents/products/{FAKE_ID}/custom/cancel/{FAKE_ID}",
                None,
            ),
            (
                "post",
                f"/api/v1/documents/products/{FAKE_ID}/assessment/code/generate",
                None,
            ),
            (
                "patch",
                f"/api/v1/documents/products/{FAKE_ID}/sections/reorder",
                {"section_ids": []},
            ),
            (
                "post",
                f"/api/v1/documents/sections/{FAKE_ID}/subsections",
                {"name": "s"},
            ),
            ("patch", f"/api/v1/documents/subsections/{FAKE_ID}", {"name": "s"}),
            ("delete", f"/api/v1/documents/subsections/{FAKE_ID}", None),
            (
                "patch",
                f"/api/v1/documents/sections/{FAKE_ID}/subsections/reorder",
                {"subsection_ids": []},
            ),
            (
                "patch",
                f"/api/v1/documents/{FAKE_ID}/move-to-section",
                {"section_id": FAKE_ID},
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


class TestDocumentsNonMemberBlocked:
    @pytest.mark.anyio
    async def test_list_documents(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_document,
        test_subscription,
    ):
        resp = await second_user_client.get(f"/api/v1/documents?product_id={test_product.id}")
        assert resp.status_code in (403, 404)

    @pytest.mark.anyio
    async def test_get_document(
        self,
        second_user_client: AsyncClient,
        test_document,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client, "get", f"/api/v1/documents/{test_document.id}"
        )

    @pytest.mark.anyio
    async def test_create_document(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            "/api/v1/documents",
            json={
                "product_id": str(test_product.id),
                "title": "evil",
                "content": "x",
                "type": "note",
            },
        )

    @pytest.mark.anyio
    async def test_update_document(
        self,
        second_user_client: AsyncClient,
        test_document,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "patch",
            f"/api/v1/documents/{test_document.id}",
            json={"title": "hacked"},
        )

    @pytest.mark.anyio
    async def test_delete_document(
        self,
        second_user_client: AsyncClient,
        test_document,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client, "delete", f"/api/v1/documents/{test_document.id}"
        )

    @pytest.mark.anyio
    async def test_grouped_documents(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "get",
            f"/api/v1/documents/products/{test_product.id}/grouped",
        )

    @pytest.mark.anyio
    async def test_sections(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "get",
            f"/api/v1/documents/products/{test_product.id}/sections",
        )

    @pytest.mark.anyio
    async def test_repo_docs_tree(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "get",
            f"/api/v1/documents/products/{test_product.id}/repo-docs-tree",
        )

    # ── Task 1.1 — Lifecycle endpoints ──────────────────────────────────

    @pytest.mark.anyio
    async def test_move_to_executing(
        self,
        second_user_client: AsyncClient,
        test_document,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            f"/api/v1/documents/{test_document.id}/move-to-executing",
        )

    @pytest.mark.anyio
    async def test_move_to_completed(
        self,
        second_user_client: AsyncClient,
        test_document,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            f"/api/v1/documents/{test_document.id}/move-to-completed",
        )

    @pytest.mark.anyio
    async def test_archive(
        self,
        second_user_client: AsyncClient,
        test_document,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            f"/api/v1/documents/{test_document.id}/archive",
        )

    # ── Task 1.2 — Sync & refresh endpoints ─────────────────────────────

    @pytest.mark.anyio
    async def test_import_docs(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            f"/api/v1/documents/products/{test_product.id}/import-docs",
        )

    @pytest.mark.anyio
    async def test_pull_remote(
        self,
        second_user_client: AsyncClient,
        test_document,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            f"/api/v1/documents/{test_document.id}/pull-remote",
        )

    @pytest.mark.anyio
    async def test_sync_docs(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            f"/api/v1/documents/products/{test_product.id}/sync-docs",
        )

    @pytest.mark.anyio
    async def test_refresh_document(
        self,
        second_user_client: AsyncClient,
        test_document,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            f"/api/v1/documents/{test_document.id}/refresh",
        )

    @pytest.mark.anyio
    async def test_refresh_all_docs(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            f"/api/v1/documents/products/{test_product.id}/refresh-all-docs",
        )

    # ── Task 1.3 — Custom doc & assessment endpoints ────────────────────

    @pytest.mark.anyio
    async def test_custom_generate(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            f"/api/v1/documents/products/{test_product.id}/custom/generate",
            json={"prompt": "test"},
        )

    @pytest.mark.anyio
    async def test_custom_status(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "get",
            f"/api/v1/documents/products/{test_product.id}/custom/status/{FAKE_ID}",
        )

    @pytest.mark.anyio
    async def test_cancel_custom_doc_job(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "delete",
            f"/api/v1/documents/products/{test_product.id}/custom/cancel/{FAKE_ID}",
        )

    @pytest.mark.anyio
    async def test_assessment_code_generate(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            f"/api/v1/documents/products/{test_product.id}/assessment/code/generate",
        )

    # ── Task 1.4 — Section & subsection mutations ───────────────────────

    @pytest.mark.anyio
    async def test_create_section(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            f"/api/v1/documents/products/{test_product.id}/sections",
            json={"name": "evil-section"},
        )

    @pytest.mark.anyio
    async def test_update_section(
        self,
        second_user_client: AsyncClient,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "patch",
            f"/api/v1/documents/sections/{FAKE_ID}",
            json={"name": "evil-section"},
        )

    @pytest.mark.anyio
    async def test_delete_section(
        self,
        second_user_client: AsyncClient,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "delete",
            f"/api/v1/documents/sections/{FAKE_ID}",
        )

    @pytest.mark.anyio
    async def test_reorder_sections(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "patch",
            f"/api/v1/documents/products/{test_product.id}/sections/reorder",
            json={"section_ids": []},
        )

    @pytest.mark.anyio
    async def test_create_subsection(
        self,
        second_user_client: AsyncClient,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            f"/api/v1/documents/sections/{FAKE_ID}/subsections",
            json={"name": "evil-subsection"},
        )

    @pytest.mark.anyio
    async def test_move_to_section(
        self,
        second_user_client: AsyncClient,
        test_document,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "patch",
            f"/api/v1/documents/{test_document.id}/move-to-section",
            json={"section_id": FAKE_ID},
        )

    # ── Task 1.5 — Changelog & delete-generated ─────────────────────────

    @pytest.mark.anyio
    async def test_changelog_add_entry(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "post",
            f"/api/v1/documents/products/{test_product.id}/changelog/add-entry",
            json={"entries": []},
        )

    @pytest.mark.anyio
    async def test_delete_generated(
        self,
        second_user_client: AsyncClient,
        test_product,
        test_subscription,
    ):
        await assert_non_member_blocked(
            second_user_client,
            "delete",
            f"/api/v1/documents/products/{test_product.id}/generated",
        )


# ─────────────────────────────────────────────────────────────────────────────
# 403 — Viewer cannot write
# ─────────────────────────────────────────────────────────────────────────────


class TestDocumentsViewerCannotWrite:
    @pytest.mark.anyio
    async def test_create_document(
        self, viewer_client: AsyncClient, test_product, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            "/api/v1/documents",
            json={
                "product_id": str(test_product.id),
                "title": "sneaky",
                "content": "x",
                "type": "note",
            },
        )

    @pytest.mark.anyio
    async def test_update_document(
        self,
        viewer_client: AsyncClient,
        test_document,
        test_subscription,
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "patch",
            f"/api/v1/documents/{test_document.id}",
            json={"title": "sneaky"},
        )

    @pytest.mark.anyio
    async def test_delete_document(
        self,
        viewer_client: AsyncClient,
        test_document,
        test_subscription,
    ):
        await assert_viewer_cannot_write(
            viewer_client, "delete", f"/api/v1/documents/{test_document.id}"
        )

    @pytest.mark.anyio
    async def test_lifecycle_move_to_executing(
        self,
        viewer_client: AsyncClient,
        test_document,
        test_subscription,
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            f"/api/v1/documents/{test_document.id}/move-to-executing",
        )

    @pytest.mark.anyio
    async def test_lifecycle_move_to_completed(
        self,
        viewer_client: AsyncClient,
        test_document,
        test_subscription,
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            f"/api/v1/documents/{test_document.id}/move-to-completed",
        )

    @pytest.mark.anyio
    async def test_lifecycle_archive(
        self,
        viewer_client: AsyncClient,
        test_document,
        test_subscription,
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            f"/api/v1/documents/{test_document.id}/archive",
        )

    @pytest.mark.anyio
    async def test_refresh_document(
        self,
        viewer_client: AsyncClient,
        test_document,
        test_subscription,
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            f"/api/v1/documents/{test_document.id}/refresh",
        )

    @pytest.mark.anyio
    async def test_refresh_all_docs(
        self, viewer_client: AsyncClient, test_product, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            f"/api/v1/documents/products/{test_product.id}/refresh-all-docs",
        )

    @pytest.mark.anyio
    async def test_pull_remote(
        self,
        viewer_client: AsyncClient,
        test_document,
        test_subscription,
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            f"/api/v1/documents/{test_document.id}/pull-remote",
        )

    @pytest.mark.anyio
    async def test_sync_docs(self, viewer_client: AsyncClient, test_product, test_subscription):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            f"/api/v1/documents/products/{test_product.id}/sync-docs",
        )

    @pytest.mark.anyio
    async def test_import_docs(self, viewer_client: AsyncClient, test_product, test_subscription):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            f"/api/v1/documents/products/{test_product.id}/import-docs",
        )

    @pytest.mark.anyio
    async def test_cancel_custom_doc_job(
        self, viewer_client: AsyncClient, test_product, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "delete",
            f"/api/v1/documents/products/{test_product.id}/custom/cancel/{FAKE_ID}",
        )

    @pytest.mark.anyio
    async def test_assessment_generation(
        self, viewer_client: AsyncClient, test_product, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            f"/api/v1/documents/products/{test_product.id}/assessment/code/generate",
        )

    @pytest.mark.anyio
    async def test_create_section(
        self, viewer_client: AsyncClient, test_product, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            f"/api/v1/documents/products/{test_product.id}/sections",
            json={"name": "sneaky"},
        )

    @pytest.mark.anyio
    async def test_reorder_sections(
        self, viewer_client: AsyncClient, test_product, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "patch",
            f"/api/v1/documents/products/{test_product.id}/sections/reorder",
            json={"section_ids": []},
        )

    @pytest.mark.anyio
    async def test_create_subsection(self, viewer_client: AsyncClient, test_subscription):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            f"/api/v1/documents/sections/{FAKE_ID}/subsections",
            json={"name": "sneaky"},
        )

    @pytest.mark.anyio
    async def test_update_subsection(self, viewer_client: AsyncClient, test_subscription):
        await assert_viewer_cannot_write(
            viewer_client,
            "patch",
            f"/api/v1/documents/subsections/{FAKE_ID}",
            json={"name": "sneaky"},
        )

    @pytest.mark.anyio
    async def test_delete_subsection(self, viewer_client: AsyncClient, test_subscription):
        await assert_viewer_cannot_write(
            viewer_client,
            "delete",
            f"/api/v1/documents/subsections/{FAKE_ID}",
        )

    @pytest.mark.anyio
    async def test_reorder_subsections(self, viewer_client: AsyncClient, test_subscription):
        await assert_viewer_cannot_write(
            viewer_client,
            "patch",
            f"/api/v1/documents/sections/{FAKE_ID}/subsections/reorder",
            json={"subsection_ids": []},
        )

    @pytest.mark.anyio
    async def test_move_to_section(
        self,
        viewer_client: AsyncClient,
        test_document,
        test_subscription,
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "patch",
            f"/api/v1/documents/{test_document.id}/move-to-section",
            json={"section_id": FAKE_ID},
        )

    @pytest.mark.anyio
    async def test_create_changelog(
        self, viewer_client: AsyncClient, test_product, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "post",
            f"/api/v1/documents/products/{test_product.id}/changelog/add-entry",
            json={"entries": []},
        )

    @pytest.mark.anyio
    async def test_delete_generated(
        self, viewer_client: AsyncClient, test_product, test_subscription
    ):
        await assert_viewer_cannot_write(
            viewer_client,
            "delete",
            f"/api/v1/documents/products/{test_product.id}/generated",
        )
