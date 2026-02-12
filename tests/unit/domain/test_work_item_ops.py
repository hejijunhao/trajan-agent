"""Unit tests for WorkItemOperations — all DB calls mocked."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.work_item_operations import WorkItemOperations

from tests.helpers.mock_factories import (
    make_mock_work_item,
    mock_scalar_result,
    mock_scalars_result,
)


class TestWorkItemGet:
    """Tests for single work item retrieval."""

    def setup_method(self):
        self.ops = WorkItemOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_get_returns_work_item(self):
        item = make_mock_work_item()
        self.db.execute = AsyncMock(return_value=mock_scalar_result(item))

        result = await self.ops.get(self.db, item.id)
        assert result == item

    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_found(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(None))

        result = await self.ops.get(self.db, uuid.uuid4())
        assert result is None


class TestWorkItemGetByProduct:
    """Tests for product-scoped work item listing with filters."""

    def setup_method(self):
        self.ops = WorkItemOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_all_items_for_product(self):
        items = [make_mock_work_item() for _ in range(3)]
        self.db.execute = AsyncMock(return_value=mock_scalars_result(items))

        result = await self.ops.get_by_product(self.db, uuid.uuid4())
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_items(self):
        self.db.execute = AsyncMock(return_value=mock_scalars_result([]))

        result = await self.ops.get_by_product(self.db, uuid.uuid4())
        assert result == []

    @pytest.mark.asyncio
    async def test_accepts_status_filter(self):
        items = [make_mock_work_item(status="done")]
        self.db.execute = AsyncMock(return_value=mock_scalars_result(items))

        result = await self.ops.get_by_product(self.db, uuid.uuid4(), status="done")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_accepts_type_filter(self):
        items = [make_mock_work_item(type="bug")]
        self.db.execute = AsyncMock(return_value=mock_scalars_result(items))

        result = await self.ops.get_by_product(self.db, uuid.uuid4(), type="bug")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_accepts_both_filters(self):
        items = [make_mock_work_item(status="open", type="feature")]
        self.db.execute = AsyncMock(return_value=mock_scalars_result(items))

        result = await self.ops.get_by_product(
            self.db, uuid.uuid4(), status="open", type="feature"
        )
        assert len(result) == 1


class TestWorkItemCreate:
    """Tests for work item creation."""

    def setup_method(self):
        self.ops = WorkItemOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_create_sets_created_by_user_id(self):
        user_id = uuid.uuid4()
        product_id = uuid.uuid4()
        obj_in = {"title": "__test_item", "product_id": product_id}

        self.db.add = MagicMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()

        result = await self.ops.create(self.db, obj_in, user_id)
        self.db.add.assert_called_once()
        added_obj = self.db.add.call_args[0][0]
        assert added_obj.created_by_user_id == user_id

    @pytest.mark.asyncio
    async def test_create_flushes_and_refreshes(self):
        self.db.add = MagicMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()

        await self.ops.create(self.db, {"title": "__test"}, uuid.uuid4())
        self.db.flush.assert_awaited_once()
        self.db.refresh.assert_awaited_once()


class TestWorkItemUpdate:
    """Tests for work item updates."""

    def setup_method(self):
        self.ops = WorkItemOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_update_sets_fields(self):
        item = make_mock_work_item(status="open")
        self.db.add = MagicMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()

        result = await self.ops.update(self.db, item, {"status": "done"})
        assert result.status == "done"

    @pytest.mark.asyncio
    async def test_update_applies_none_values(self):
        """update() applies all keys including None — callers should exclude_unset."""
        item = make_mock_work_item(title="original")
        self.db.add = MagicMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()

        await self.ops.update(self.db, item, {"title": None, "status": "done"})
        assert item.title is None
        assert item.status == "done"


class TestWorkItemDelete:
    """Tests for work item deletion."""

    def setup_method(self):
        self.ops = WorkItemOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_delete_returns_true(self):
        item = make_mock_work_item()
        self.db.delete = AsyncMock()
        self.db.flush = AsyncMock()

        result = await self.ops.delete(self.db, item)
        assert result is True
        self.db.delete.assert_awaited_once_with(item)
        self.db.flush.assert_awaited_once()
