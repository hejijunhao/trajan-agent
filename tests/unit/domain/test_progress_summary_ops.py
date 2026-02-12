"""Unit tests for ProgressSummaryOperations — all DB calls mocked."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.progress_summary_operations import ProgressSummaryOperations

from tests.helpers.mock_factories import (
    make_mock_progress_summary,
    mock_scalar_result,
)


class TestGetByProductPeriod:
    """Tests for single product+period summary lookup."""

    def setup_method(self):
        self.ops = ProgressSummaryOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_summary_when_found(self):
        summary = make_mock_progress_summary()
        self.db.execute = AsyncMock(return_value=mock_scalar_result(summary))

        result = await self.ops.get_by_product_period(
            self.db, summary.product_id, "7d"
        )
        assert result == summary

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(None))

        result = await self.ops.get_by_product_period(self.db, uuid.uuid4(), "7d")
        assert result is None


class TestUpsert:
    """Tests for upsert (create or update) of progress summaries."""

    def setup_method(self):
        self.ops = ProgressSummaryOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_upsert_executes_and_flushes(self):
        summary = make_mock_progress_summary()
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = summary
        self.db.execute = AsyncMock(return_value=result_mock)
        self.db.flush = AsyncMock()

        result = await self.ops.upsert(
            self.db,
            product_id=uuid.uuid4(),
            period="7d",
            summary_text="This week the team shipped...",
        )
        assert result == summary
        self.db.execute.assert_awaited_once()
        self.db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_upsert_with_all_stats(self):
        summary = make_mock_progress_summary()
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = summary
        self.db.execute = AsyncMock(return_value=result_mock)
        self.db.flush = AsyncMock()

        now = datetime.now(UTC)
        result = await self.ops.upsert(
            self.db,
            product_id=uuid.uuid4(),
            period="30d",
            summary_text="Monthly summary",
            total_commits=100,
            total_contributors=5,
            total_additions=1000,
            total_deletions=500,
            last_activity_at=now,
        )
        assert result == summary


class TestUpdateLastActivity:
    """Tests for last_activity_at timestamp updates."""

    def setup_method(self):
        self.ops = ProgressSummaryOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_updates_timestamp_when_found(self):
        summary = make_mock_progress_summary()
        self.db.execute = AsyncMock(return_value=mock_scalar_result(summary))
        self.db.add = MagicMock()
        self.db.flush = AsyncMock()

        now = datetime.now(UTC)
        await self.ops.update_last_activity(
            self.db, summary.product_id, "7d", now
        )
        assert summary.last_activity_at == now
        self.db.add.assert_called_once()
        self.db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_op_when_not_found(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(None))
        self.db.add = MagicMock()

        await self.ops.update_last_activity(
            self.db, uuid.uuid4(), "7d", datetime.now(UTC)
        )
        self.db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_sets_updated_at(self):
        summary = make_mock_progress_summary()
        self.db.execute = AsyncMock(return_value=mock_scalar_result(summary))
        self.db.add = MagicMock()
        self.db.flush = AsyncMock()

        now = datetime.now(UTC)
        await self.ops.update_last_activity(
            self.db, summary.product_id, "7d", now
        )
        assert summary.updated_at is not None
