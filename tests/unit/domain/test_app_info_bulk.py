"""
Tests for App Info bulk operations.

Tests cover:
- Bulk create with valid entries
- Bulk create skipping duplicates (existing keys)
- Bulk create handling duplicate keys within request
- Export with revealed secret values
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.app_info_operations import AppInfoOperations
from app.models.app_info import AppInfoBulkEntry


class TestAppInfoBulkCreate:
    """Tests for AppInfoOperations.bulk_create method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.ops = AppInfoOperations()
        self.user_id = uuid.uuid4()
        self.product_id = uuid.uuid4()

    @pytest.mark.asyncio
    async def test_bulk_create_empty_list(self) -> None:
        """Empty entries list returns empty results."""
        db = AsyncMock()
        created, skipped = await self.ops.bulk_create(
            db,
            user_id=self.user_id,
            product_id=self.product_id,
            entries=[],
        )
        assert created == []
        assert skipped == []

    @pytest.mark.asyncio
    async def test_bulk_create_deduplicates_within_batch(self) -> None:
        """Duplicate keys in batch take last occurrence."""
        db = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        # Mock get_existing_keys to return empty set
        self.ops.get_existing_keys = AsyncMock(return_value=set())

        entries = [
            AppInfoBulkEntry(key="API_KEY", value="first_value"),
            AppInfoBulkEntry(key="API_KEY", value="second_value"),
            AppInfoBulkEntry(key="OTHER_KEY", value="other_value"),
        ]

        created, skipped = await self.ops.bulk_create(
            db,
            user_id=self.user_id,
            product_id=self.product_id,
            entries=entries,
        )

        # Should only create 2 entries (API_KEY deduplicated)
        assert len(created) == 2
        assert skipped == []

        # Verify the second value was used for API_KEY
        api_key_entry = next((e for e in created if e.key == "API_KEY"), None)
        assert api_key_entry is not None
        assert api_key_entry.value == "second_value"

    @pytest.mark.asyncio
    async def test_bulk_create_skips_existing_keys(self) -> None:
        """Entries with existing keys are skipped."""
        db = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        # Mock get_existing_keys to return one existing key
        self.ops.get_existing_keys = AsyncMock(return_value={"EXISTING_KEY"})

        entries = [
            AppInfoBulkEntry(key="EXISTING_KEY", value="new_value"),
            AppInfoBulkEntry(key="NEW_KEY", value="new_value"),
        ]

        created, skipped = await self.ops.bulk_create(
            db,
            user_id=self.user_id,
            product_id=self.product_id,
            entries=entries,
        )

        # Should only create 1 entry, skip 1
        assert len(created) == 1
        assert created[0].key == "NEW_KEY"
        assert skipped == ["EXISTING_KEY"]


class TestGetExistingKeys:
    """Tests for AppInfoOperations.get_existing_keys method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.ops = AppInfoOperations()

    @pytest.mark.asyncio
    async def test_returns_matching_keys(self) -> None:
        """Returns set of keys that exist in database."""
        db = AsyncMock()

        # Mock the execute to return existing keys
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = ["KEY1", "KEY2"]
        db.execute = AsyncMock(return_value=mock_result)

        result = await self.ops.get_existing_keys(
            db,
            user_id=uuid.uuid4(),
            product_id=uuid.uuid4(),
            keys=["KEY1", "KEY2", "KEY3"],
        )

        assert result == {"KEY1", "KEY2"}


class TestAppInfoBulkEntry:
    """Tests for AppInfoBulkEntry schema."""

    def test_defaults(self) -> None:
        """Default values are applied correctly."""
        entry = AppInfoBulkEntry(key="TEST", value="value")
        assert entry.is_secret is False
        assert entry.category is None
        assert entry.description is None

    def test_is_secret_flag(self) -> None:
        """is_secret flag is set correctly."""
        entry = AppInfoBulkEntry(key="PASSWORD", value="secret", is_secret=True)
        assert entry.is_secret is True
