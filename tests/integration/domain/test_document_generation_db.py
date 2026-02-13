"""
Document generation lifecycle tests at the DB level.

Tests cover:
- Creating documents with generated vs imported origin
- Querying generated-only documents
- Bulk deleting generated docs while preserving manual ones
- Product-level generation status tracking (JSONB roundtrip)
- Folder-based document organization and queries
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.document_operations import document_ops
from app.models.product import Product


class TestDocumentGenerationLifecycle:
    """Document creation and retrieval for generation workflows."""

    @pytest.mark.anyio
    async def test_create_generated_document(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """Document created with is_generated=True has correct metadata."""
        doc = await document_ops.create(
            db_session,
            obj_in={
                "title": "API Overview",
                "content": "# API Overview\n\nGenerated content.",
                "type": "overview",
                "product_id": test_product.id,
                "is_generated": True,
                "folder": {"path": "blueprints"},
            },
            created_by_user_id=test_user.id,
        )

        assert doc.id is not None
        assert doc.is_generated is True
        assert doc.product_id == test_product.id
        assert doc.created_by_user_id == test_user.id
        assert doc.type == "overview"
        assert doc.folder == {"path": "blueprints"}

    @pytest.mark.anyio
    async def test_create_imported_document(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """Document created with is_generated=False is treated as imported."""
        doc = await document_ops.create(
            db_session,
            obj_in={
                "title": "README.md",
                "content": "# Project README",
                "type": "note",
                "product_id": test_product.id,
                "is_generated": False,
            },
            created_by_user_id=test_user.id,
        )

        assert doc.is_generated is False
        assert doc.title == "README.md"

    @pytest.mark.anyio
    async def test_get_generated_by_product(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """get_generated_by_product returns only AI-generated documents."""
        # Create 2 generated + 1 imported
        await document_ops.create(
            db_session,
            obj_in={
                "title": "Blueprint",
                "content": "Generated",
                "type": "blueprint",
                "product_id": test_product.id,
                "is_generated": True,
            },
            created_by_user_id=test_user.id,
        )
        await document_ops.create(
            db_session,
            obj_in={
                "title": "Architecture",
                "content": "Generated",
                "type": "architecture",
                "product_id": test_product.id,
                "is_generated": True,
            },
            created_by_user_id=test_user.id,
        )
        await document_ops.create(
            db_session,
            obj_in={
                "title": "Manual Note",
                "content": "User-written",
                "type": "note",
                "product_id": test_product.id,
                "is_generated": False,
            },
            created_by_user_id=test_user.id,
        )

        generated = await document_ops.get_generated_by_product(
            db_session, test_product.id
        )
        assert len(generated) == 2
        assert all(d.is_generated for d in generated)

    @pytest.mark.anyio
    async def test_get_generated_by_product_empty(
        self, db_session: AsyncSession, test_product
    ):
        """get_generated_by_product returns empty list when no generated docs exist."""
        generated = await document_ops.get_generated_by_product(
            db_session, test_product.id
        )
        assert generated == []

    @pytest.mark.anyio
    async def test_delete_generated_preserves_manual(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """Bulk delete removes only is_generated=True, keeps manual docs."""
        # Create mixed docs
        await document_ops.create(
            db_session,
            obj_in={
                "title": "Generated Doc",
                "content": "AI",
                "type": "blueprint",
                "product_id": test_product.id,
                "is_generated": True,
            },
            created_by_user_id=test_user.id,
        )
        manual = await document_ops.create(
            db_session,
            obj_in={
                "title": "Manual Doc",
                "content": "Human",
                "type": "note",
                "product_id": test_product.id,
                "is_generated": False,
            },
            created_by_user_id=test_user.id,
        )

        deleted_count = await document_ops.delete_by_product_generated(
            db_session, test_product.id
        )

        assert deleted_count == 1
        # Manual doc should still exist
        remaining = await document_ops.get(db_session, manual.id)
        assert remaining is not None
        assert remaining.title == "Manual Doc"

    @pytest.mark.anyio
    async def test_document_with_section_and_subsection(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """Documents can store section/subsection for v2 organization."""
        doc = await document_ops.create(
            db_session,
            obj_in={
                "title": "Backend Architecture",
                "content": "# Backend\n\nArchitecture details.",
                "type": "architecture",
                "product_id": test_product.id,
                "is_generated": True,
                "section": "technical",
                "subsection": "backend",
            },
            created_by_user_id=test_user.id,
        )

        assert doc.section == "technical"
        assert doc.subsection == "backend"

        # Verify roundtrip via fresh get
        fetched = await document_ops.get(db_session, doc.id)
        assert fetched is not None
        assert fetched.section == "technical"
        assert fetched.subsection == "backend"


class TestDocumentGenerationStatus:
    """Product-level generation status tracking."""

    @pytest.mark.anyio
    async def test_docs_generation_status_initially_null(
        self, db_session: AsyncSession, test_product
    ):
        """New product has no generation status set."""
        assert test_product.docs_generation_status is None

    @pytest.mark.anyio
    async def test_docs_generation_progress_jsonb_roundtrip(
        self, db_session: AsyncSession, test_product
    ):
        """Product docs_generation_progress stores and retrieves JSONB data."""
        progress = {
            "stage": "analyzing",
            "message": "Analyzing codebase...",
            "updated_at": datetime.now(UTC).isoformat(),
        }
        test_product.docs_generation_progress = progress
        test_product.docs_generation_status = "generating"
        db_session.add(test_product)
        await db_session.flush()
        await db_session.refresh(test_product)

        assert test_product.docs_generation_progress["stage"] == "analyzing"
        assert test_product.docs_generation_status == "generating"

    @pytest.mark.anyio
    async def test_docs_codebase_fingerprint_storage(
        self, db_session: AsyncSession, test_product
    ):
        """Codebase fingerprint is stored and retrievable."""
        fingerprint = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
        test_product.docs_codebase_fingerprint = fingerprint
        db_session.add(test_product)
        await db_session.flush()
        await db_session.refresh(test_product)

        assert test_product.docs_codebase_fingerprint == fingerprint

    @pytest.mark.anyio
    async def test_generation_status_transitions(
        self, db_session: AsyncSession, test_product
    ):
        """Generation status can transition through idle → generating → completed."""
        for status in ["idle", "generating", "completed"]:
            test_product.docs_generation_status = status
            db_session.add(test_product)
            await db_session.flush()
            await db_session.refresh(test_product)
            assert test_product.docs_generation_status == status


class TestDocumentFolderOperations:
    """Document folder/section operations relevant to generation."""

    @pytest.mark.anyio
    async def test_get_by_product_grouped(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """get_by_product_grouped organizes docs by folder path."""
        # Create docs in different folders
        await document_ops.create(
            db_session,
            obj_in={
                "title": "Blueprint Doc",
                "content": "Content",
                "type": "blueprint",
                "product_id": test_product.id,
                "is_generated": True,
                "folder": {"path": "blueprints"},
            },
            created_by_user_id=test_user.id,
        )
        await document_ops.create(
            db_session,
            obj_in={
                "title": "Plan Doc",
                "content": "Content",
                "type": "plan",
                "product_id": test_product.id,
                "is_generated": True,
                "folder": {"path": "plans"},
            },
            created_by_user_id=test_user.id,
        )
        await document_ops.create(
            db_session,
            obj_in={
                "title": "Changelog",
                "content": "# Changelog",
                "type": "changelog",
                "product_id": test_product.id,
                "is_generated": True,
            },
            created_by_user_id=test_user.id,
        )

        grouped = await document_ops.get_by_product_grouped(
            db_session, test_product.id
        )

        assert len(grouped["blueprints"]) == 1
        assert len(grouped["plans"]) == 1
        assert len(grouped["changelog"]) == 1
        assert grouped["blueprints"][0].title == "Blueprint Doc"

    @pytest.mark.anyio
    async def test_get_by_folder(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """get_by_folder returns only documents in specified folder."""
        await document_ops.create(
            db_session,
            obj_in={
                "title": "In Blueprints",
                "content": "Content",
                "type": "blueprint",
                "product_id": test_product.id,
                "is_generated": True,
                "folder": {"path": "blueprints"},
            },
            created_by_user_id=test_user.id,
        )
        await document_ops.create(
            db_session,
            obj_in={
                "title": "In Plans",
                "content": "Content",
                "type": "plan",
                "product_id": test_product.id,
                "is_generated": True,
                "folder": {"path": "plans"},
            },
            created_by_user_id=test_user.id,
        )

        blueprints = await document_ops.get_by_folder(
            db_session, test_product.id, "blueprints"
        )
        assert len(blueprints) == 1
        assert blueprints[0].title == "In Blueprints"

    @pytest.mark.anyio
    async def test_get_changelog_found(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """get_changelog returns the changelog document when it exists."""
        await document_ops.create(
            db_session,
            obj_in={
                "title": "Changelog",
                "content": "# Changelog\n\nAll notable changes.",
                "type": "changelog",
                "product_id": test_product.id,
                "is_generated": True,
            },
            created_by_user_id=test_user.id,
        )

        changelog = await document_ops.get_changelog(db_session, test_product.id)
        assert changelog is not None
        assert changelog.type == "changelog"

    @pytest.mark.anyio
    async def test_get_changelog_not_found(
        self, db_session: AsyncSession, test_product
    ):
        """get_changelog returns None when no changelog exists."""
        changelog = await document_ops.get_changelog(db_session, test_product.id)
        assert changelog is None

    @pytest.mark.anyio
    async def test_nested_folder_grouped_to_root(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """Documents in nested folders (e.g. blueprints/backend) group to root."""
        await document_ops.create(
            db_session,
            obj_in={
                "title": "Nested Blueprint",
                "content": "Content",
                "type": "architecture",
                "product_id": test_product.id,
                "is_generated": True,
                "folder": {"path": "blueprints/backend"},
            },
            created_by_user_id=test_user.id,
        )

        grouped = await document_ops.get_by_product_grouped(
            db_session, test_product.id
        )
        assert len(grouped["blueprints"]) == 1
        assert grouped["blueprints"][0].title == "Nested Blueprint"
