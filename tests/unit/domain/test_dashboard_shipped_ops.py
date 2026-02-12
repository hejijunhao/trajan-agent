"""Unit tests for DashboardShippedOperations — all DB calls mocked."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.dashboard_shipped_operations import DashboardShippedOperations

from tests.helpers.mock_factories import (
    make_mock_dashboard_shipped,
    mock_scalar_result,
    mock_scalars_result,
)


class TestGetByProductPeriod:
    """Tests for single product+period lookup."""

    def setup_method(self):
        self.ops = DashboardShippedOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_summary_when_found(self):
        shipped = make_mock_dashboard_shipped()
        self.db.execute = AsyncMock(return_value=mock_scalar_result(shipped))

        result = await self.ops.get_by_product_period(self.db, shipped.product_id, "7d")
        assert result == shipped

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(None))

        result = await self.ops.get_by_product_period(self.db, uuid.uuid4(), "7d")
        assert result is None


class TestGetByProductsPeriod:
    """Tests for multi-product period lookup."""

    def setup_method(self):
        self.ops = DashboardShippedOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_summaries_for_multiple_products(self):
        shipped_list = [make_mock_dashboard_shipped() for _ in range(3)]
        self.db.execute = AsyncMock(return_value=mock_scalars_result(shipped_list))

        product_ids = [uuid.uuid4() for _ in range(3)]
        result = await self.ops.get_by_products_period(self.db, product_ids, "7d")
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_product_ids(self):
        result = await self.ops.get_by_products_period(self.db, [], "7d")
        assert result == []
        self.db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_summaries_exist(self):
        self.db.execute = AsyncMock(return_value=mock_scalars_result([]))

        result = await self.ops.get_by_products_period(
            self.db, [uuid.uuid4()], "30d"
        )
        assert result == []


class TestUpsert:
    """Tests for upsert (create or update) of shipped summaries."""

    def setup_method(self):
        self.ops = DashboardShippedOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_upsert_executes_and_flushes(self):
        shipped = make_mock_dashboard_shipped()
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = shipped
        self.db.execute = AsyncMock(return_value=result_mock)
        self.db.flush = AsyncMock()

        result = await self.ops.upsert(
            self.db,
            product_id=uuid.uuid4(),
            period="7d",
            items=[{"description": "Added feature X", "category": "feature"}],
        )
        assert result == shipped
        self.db.execute.assert_awaited_once()
        self.db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_upsert_with_all_params(self):
        shipped = make_mock_dashboard_shipped()
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = shipped
        self.db.execute = AsyncMock(return_value=result_mock)
        self.db.flush = AsyncMock()

        now = datetime.now(UTC)
        result = await self.ops.upsert(
            self.db,
            product_id=uuid.uuid4(),
            period="30d",
            items=[],
            has_significant_changes=False,
            total_commits=50,
            total_additions=500,
            total_deletions=200,
            last_activity_at=now,
        )
        assert result == shipped


class TestUpdateLastActivity:
    """Tests for last_activity_at timestamp updates."""

    def setup_method(self):
        self.ops = DashboardShippedOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_updates_timestamp_when_found(self):
        shipped = make_mock_dashboard_shipped()
        self.db.execute = AsyncMock(return_value=mock_scalar_result(shipped))
        self.db.add = MagicMock()
        self.db.flush = AsyncMock()

        now = datetime.now(UTC)
        await self.ops.update_last_activity(self.db, shipped.product_id, "7d", now)
        assert shipped.last_activity_at == now
        self.db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_op_when_not_found(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(None))
        self.db.add = MagicMock()

        await self.ops.update_last_activity(
            self.db, uuid.uuid4(), "7d", datetime.now(UTC)
        )
        self.db.add.assert_not_called()


class TestDeleteByProduct:
    """Tests for product-level cache invalidation."""

    def setup_method(self):
        self.ops = DashboardShippedOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_deleted_count(self):
        result_mock = MagicMock()
        result_mock.rowcount = 3
        self.db.execute = AsyncMock(return_value=result_mock)
        self.db.flush = AsyncMock()

        result = await self.ops.delete_by_product(self.db, uuid.uuid4())
        assert result == 3

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_to_delete(self):
        result_mock = MagicMock()
        result_mock.rowcount = 0
        self.db.execute = AsyncMock(return_value=result_mock)
        self.db.flush = AsyncMock()

        result = await self.ops.delete_by_product(self.db, uuid.uuid4())
        assert result == 0
