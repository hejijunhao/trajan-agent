"""Unit tests for DocumentOperations — folder grouping, move, archive."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.document_operations import DocumentOperations

from tests.helpers.mock_factories import make_mock_document


class TestGetByProductGrouped:
    """Tests for document grouping by folder path."""

    def setup_method(self):
        self.ops = DocumentOperations()
        self.db = AsyncMock()
        self.product_id = uuid.uuid4()

    @pytest.mark.asyncio
    @patch.object(DocumentOperations, "get_by_product")
    async def test_groups_changelog_by_type(self, mock_get):
        changelog = make_mock_document(type="changelog", folder=None)
        mock_get.return_value = [changelog]

        result = await self.ops.get_by_product_grouped(self.db, self.product_id)
        assert len(result["changelog"]) == 1
        assert len(result["blueprints"]) == 0

    @pytest.mark.asyncio
    @patch.object(DocumentOperations, "get_by_product")
    async def test_routes_folder_paths_to_root(self, mock_get):
        doc = make_mock_document(type="blueprint", folder={"path": "blueprints/backend"})
        mock_get.return_value = [doc]

        result = await self.ops.get_by_product_grouped(self.db, self.product_id)
        assert len(result["blueprints"]) == 1

    @pytest.mark.asyncio
    @patch.object(DocumentOperations, "get_by_product")
    async def test_defaults_to_blueprints_when_no_folder(self, mock_get):
        doc = make_mock_document(type="blueprint", folder=None)
        mock_get.return_value = [doc]

        result = await self.ops.get_by_product_grouped(self.db, self.product_id)
        assert len(result["blueprints"]) == 1

    @pytest.mark.asyncio
    @patch.object(DocumentOperations, "get_by_product")
    async def test_groups_executing_and_completions(self, mock_get):
        exec_doc = make_mock_document(type="plan", folder={"path": "executing"})
        comp_doc = make_mock_document(type="plan", folder={"path": "completions/2026-02-12"})
        mock_get.return_value = [exec_doc, comp_doc]

        result = await self.ops.get_by_product_grouped(self.db, self.product_id)
        assert len(result["executing"]) == 1
        assert len(result["completions"]) == 1


class TestMoveToFolder:
    """Tests for document folder movement."""

    def setup_method(self):
        self.ops = DocumentOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    @patch.object(DocumentOperations, "get")
    async def test_updates_folder(self, mock_get):
        doc = make_mock_document(sync_status=None)
        mock_get.return_value = doc
        self.db.refresh = AsyncMock()

        result = await self.ops.move_to_folder(self.db, doc.id, "executing")
        assert result.folder == {"path": "executing"}

    @pytest.mark.asyncio
    @patch.object(DocumentOperations, "get")
    async def test_marks_local_changes_if_synced(self, mock_get):
        doc = make_mock_document(sync_status="synced")
        mock_get.return_value = doc
        self.db.refresh = AsyncMock()

        await self.ops.move_to_folder(self.db, doc.id, "archive")
        assert doc.sync_status == "local_changes"


class TestMoveToCompleted:
    """Tests for completed folder path generation."""

    def setup_method(self):
        self.ops = DocumentOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    @patch.object(DocumentOperations, "move_to_folder")
    async def test_generates_date_prefixed_path(self, mock_move):
        mock_move.return_value = make_mock_document()
        doc_id = uuid.uuid4()

        await self.ops.move_to_completed(self.db, doc_id)

        call_args = mock_move.call_args[0]
        folder = call_args[2]
        # Should be "completions/YYYY-MM-DD"
        assert folder.startswith("completions/")
        assert len(folder.split("/")[1]) == 10  # YYYY-MM-DD format
