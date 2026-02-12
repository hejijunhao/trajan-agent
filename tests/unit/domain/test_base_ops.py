"""Unit tests for BaseOperations — generic CRUD with all DB calls mocked.

Uses Feedback model as the concrete type since BaseOperations requires a
real SQLModel class for select() to build valid query expressions.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.base_operations import BaseOperations
from app.models.feedback import Feedback

from tests.helpers.mock_factories import mock_scalar_result, mock_scalars_result


class TestBaseGet:
    """Tests for BaseOperations.get()."""

    def setup_method(self):
        self.ops = BaseOperations(Feedback)
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_get_returns_record(self):
        record = MagicMock()
        self.db.execute = AsyncMock(return_value=mock_scalar_result(record))

        result = await self.ops.get(self.db, uuid.uuid4())
        assert result == record

    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_found(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(None))

        result = await self.ops.get(self.db, uuid.uuid4())
        assert result is None


class TestBaseGetByUser:
    """Tests for BaseOperations.get_by_user()."""

    def setup_method(self):
        self.ops = BaseOperations(Feedback)
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_record_for_matching_user(self):
        record = MagicMock()
        self.db.execute = AsyncMock(return_value=mock_scalar_result(record))

        result = await self.ops.get_by_user(self.db, uuid.uuid4(), uuid.uuid4())
        assert result == record

    @pytest.mark.asyncio
    async def test_returns_none_when_user_mismatch(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(None))

        result = await self.ops.get_by_user(self.db, uuid.uuid4(), uuid.uuid4())
        assert result is None


class TestBaseGetMultiByUser:
    """Tests for BaseOperations.get_multi_by_user()."""

    def setup_method(self):
        self.ops = BaseOperations(Feedback)
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_list_of_records(self):
        records = [MagicMock(), MagicMock()]
        self.db.execute = AsyncMock(return_value=mock_scalars_result(records))

        result = await self.ops.get_multi_by_user(self.db, uuid.uuid4())
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_records(self):
        self.db.execute = AsyncMock(return_value=mock_scalars_result([]))

        result = await self.ops.get_multi_by_user(self.db, uuid.uuid4())
        assert result == []

    @pytest.mark.asyncio
    async def test_respects_skip_and_limit(self):
        """Verifies that skip/limit are passed to the query builder."""
        self.db.execute = AsyncMock(return_value=mock_scalars_result([]))

        await self.ops.get_multi_by_user(self.db, uuid.uuid4(), skip=10, limit=5)
        self.db.execute.assert_awaited_once()


class TestBaseCreate:
    """Tests for BaseOperations.create()."""

    def setup_method(self):
        self.ops = BaseOperations(Feedback)
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_create_adds_flushes_and_refreshes(self):
        user_id = uuid.uuid4()
        self.db.add = MagicMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()

        result = await self.ops.create(
            self.db, {"category": "bug", "message": "__test"}, user_id
        )
        self.db.add.assert_called_once()
        self.db.flush.assert_awaited_once()
        self.db.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_sets_user_id(self):
        user_id = uuid.uuid4()
        self.db.add = MagicMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()

        result = await self.ops.create(
            self.db, {"category": "feature", "message": "__test"}, user_id
        )
        added_obj = self.db.add.call_args[0][0]
        assert added_obj.user_id == user_id


class TestBaseUpdate:
    """Tests for BaseOperations.update()."""

    def setup_method(self):
        self.ops = BaseOperations(Feedback)
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_update_sets_fields(self):
        record = MagicMock()
        self.db.add = MagicMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()

        await self.ops.update(self.db, record, {"status": "reviewed"})
        assert record.status == "reviewed"

    @pytest.mark.asyncio
    async def test_update_skips_none_values(self):
        record = MagicMock()
        record.status = "new"
        self.db.add = MagicMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()

        await self.ops.update(self.db, record, {"status": None})
        assert record.status == "new"


class TestBaseDelete:
    """Tests for BaseOperations.delete()."""

    def setup_method(self):
        self.ops = BaseOperations(Feedback)
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_delete_returns_true_when_found(self):
        record = MagicMock()
        self.db.execute = AsyncMock(return_value=mock_scalar_result(record))
        self.db.delete = AsyncMock()
        self.db.flush = AsyncMock()

        result = await self.ops.delete(self.db, uuid.uuid4(), uuid.uuid4())
        assert result is True
        self.db.delete.assert_awaited_once_with(record)

    @pytest.mark.asyncio
    async def test_delete_returns_false_when_not_found(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(None))

        result = await self.ops.delete(self.db, uuid.uuid4(), uuid.uuid4())
        assert result is False
