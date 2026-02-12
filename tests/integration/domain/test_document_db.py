"""DB integration tests for DocumentOperations.

Tests real SQL against PostgreSQL via rollback fixture.
Covers: create, product scoping, type/generated filters, changelog lookup,
folder JSONB, move operations, and bulk delete of generated docs.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.document_operations import document_ops


# ─────────────────────────────────────────────────────────────────────────────
# CRUD and lookups
# ─────────────────────────────────────────────────────────────────────────────


class TestDocumentCRUD:
    """Test document create, read, update, delete."""

    async def test_create_document(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """Can create a document linked to a product."""
        doc = await document_ops.create(
            db_session,
            obj_in={
                "title": "Architecture Overview",
                "content": "# Architecture\n\nOverview here.",
                "type": "blueprint",
                "product_id": test_product.id,
                "is_generated": True,
                "folder": {"path": "blueprints"},
            },
            created_by_user_id=test_user.id,
        )

        assert doc.id is not None
        assert doc.title == "Architecture Overview"
        assert doc.type == "blueprint"
        assert doc.is_generated is True
        assert doc.created_by_user_id == test_user.id
        assert doc.folder == {"path": "blueprints"}

    async def test_get_by_product(
        self, db_session: AsyncSession, test_product, test_document
    ):
        """get_by_product returns documents for the product."""
        docs = await document_ops.get_by_product(db_session, test_product.id)
        doc_ids = [d.id for d in docs]
        assert test_document.id in doc_ids

    async def test_get_by_product_type_filter(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """Can filter documents by type."""
        await document_ops.create(
            db_session,
            obj_in={
                "title": "Test Changelog",
                "type": "changelog",
                "product_id": test_product.id,
            },
            created_by_user_id=test_user.id,
        )

        changelogs = await document_ops.get_by_product(
            db_session, test_product.id, doc_type="changelog"
        )
        assert all(d.type == "changelog" for d in changelogs)
        assert len(changelogs) >= 1

    async def test_get_by_product_generated_filter(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """Can filter to only AI-generated or only imported documents."""
        # Create an imported (non-generated) doc
        await document_ops.create(
            db_session,
            obj_in={
                "title": "Imported README",
                "type": "note",
                "product_id": test_product.id,
                "is_generated": False,
            },
            created_by_user_id=test_user.id,
        )

        generated = await document_ops.get_by_product(
            db_session, test_product.id, is_generated=True
        )
        imported = await document_ops.get_by_product(
            db_session, test_product.id, is_generated=False
        )

        assert all(d.is_generated is True for d in generated)
        assert all(d.is_generated is False for d in imported)
        assert len(imported) >= 1

    async def test_delete_document(
        self, db_session: AsyncSession, test_document
    ):
        """Can delete a document by ID."""
        deleted = await document_ops.delete(db_session, test_document.id)
        assert deleted is True

        found = await document_ops.get(db_session, test_document.id)
        assert found is None


# ─────────────────────────────────────────────────────────────────────────────
# Changelog and folder queries
# ─────────────────────────────────────────────────────────────────────────────


class TestDocumentQueries:
    """Test specialized document queries."""

    async def test_get_changelog(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """get_changelog returns the changelog document for a product."""
        await document_ops.create(
            db_session,
            obj_in={
                "title": "Changelog",
                "type": "changelog",
                "product_id": test_product.id,
            },
            created_by_user_id=test_user.id,
        )

        changelog = await document_ops.get_changelog(db_session, test_product.id)
        assert changelog is not None
        assert changelog.type == "changelog"

    async def test_get_changelog_not_found(
        self, db_session: AsyncSession, test_product
    ):
        """get_changelog returns None if no changelog exists."""
        changelog = await document_ops.get_changelog(db_session, test_product.id)
        assert changelog is None

    async def test_move_to_folder(
        self, db_session: AsyncSession, test_document
    ):
        """move_to_folder updates the JSONB folder path."""
        moved = await document_ops.move_to_folder(
            db_session, test_document.id, "executing"
        )
        assert moved is not None
        assert moved.folder == {"path": "executing"}


# ─────────────────────────────────────────────────────────────────────────────
# Bulk operations
# ─────────────────────────────────────────────────────────────────────────────


class TestDocumentBulkOps:
    """Test bulk document operations."""

    async def test_delete_by_product_generated(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """delete_by_product_generated removes only AI-generated docs."""
        # Create 2 generated + 1 imported
        for i in range(2):
            await document_ops.create(
                db_session,
                obj_in={
                    "title": f"Generated Doc {i}",
                    "product_id": test_product.id,
                    "is_generated": True,
                },
                created_by_user_id=test_user.id,
            )
        imported = await document_ops.create(
            db_session,
            obj_in={
                "title": "Imported Doc",
                "product_id": test_product.id,
                "is_generated": False,
            },
            created_by_user_id=test_user.id,
        )

        deleted_count = await document_ops.delete_by_product_generated(
            db_session, test_product.id
        )
        assert deleted_count >= 2

        # Imported doc should still exist
        remaining = await document_ops.get(db_session, imported.id)
        assert remaining is not None
        assert remaining.is_generated is False

    async def test_sync_status_tracking(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """Documents with github_path can track sync status."""
        doc = await document_ops.create(
            db_session,
            obj_in={
                "title": "Synced Doc",
                "product_id": test_product.id,
                "github_path": "docs/README.md",
                "sync_status": "synced",
            },
            created_by_user_id=test_user.id,
        )

        # mark_local_changes updates sync_status
        marked = await document_ops.mark_local_changes(db_session, doc.id)
        assert marked is not None
        assert marked.sync_status == "local_changes"

        # get_with_local_changes returns it
        changed = await document_ops.get_with_local_changes(db_session, test_product.id)
        changed_ids = [d.id for d in changed]
        assert doc.id in changed_ids
