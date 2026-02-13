"""Unit tests for AnnouncementOperations — all DB calls mocked."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.domain.announcement_operations import AnnouncementOperations

from tests.helpers.mock_factories import (
    make_mock_announcement,
    mock_scalars_result,
)


class TestAnnouncementGetActive:
    """Tests for active announcements retrieval."""

    def setup_method(self):
        self.ops = AnnouncementOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_active_announcements(self):
        announcements = [
            make_mock_announcement(variant="error"),
            make_mock_announcement(variant="info"),
        ]
        self.db.execute = AsyncMock(return_value=mock_scalars_result(announcements))

        result = await self.ops.get_active(self.db)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_active(self):
        self.db.execute = AsyncMock(return_value=mock_scalars_result([]))

        result = await self.ops.get_active(self.db)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_list_type(self):
        self.db.execute = AsyncMock(return_value=mock_scalars_result([]))

        result = await self.ops.get_active(self.db)
        assert isinstance(result, list)
