"""
Tests for App Info bulk operations.

Tests cover:
- Bulk create with valid entries
- Bulk create skipping duplicates (existing keys)
- Bulk create handling duplicate keys within request
- Bulk create UPDATE strategy: merge rules (value, is_secret guard,
  tag-replace-if-explicit, target_file fill-if-empty), and the mixed
  new+update batch shape.
- Export with revealed secret values
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.app_info_operations import AppInfoOperations
from app.models.app_info import AppInfoBulkEntry, ConflictStrategy


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
        created, updated, skipped = await self.ops.bulk_create(
            db,
            user_id=self.user_id,
            product_id=self.product_id,
            entries=[],
        )
        assert created == []
        assert updated == []
        assert skipped == []

    @pytest.mark.asyncio
    async def test_bulk_create_deduplicates_within_batch(self) -> None:
        """Duplicate keys in batch take last occurrence."""
        db = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        # No existing rows — all entries are new
        self.ops.get_existing_rows_by_keys = AsyncMock(return_value={})

        entries = [
            AppInfoBulkEntry(key="API_KEY", value="first_value"),
            AppInfoBulkEntry(key="API_KEY", value="second_value"),
            AppInfoBulkEntry(key="OTHER_KEY", value="other_value"),
        ]

        created, updated, skipped = await self.ops.bulk_create(
            db,
            user_id=self.user_id,
            product_id=self.product_id,
            entries=entries,
        )

        # Should only create 2 entries (API_KEY deduplicated)
        assert len(created) == 2
        assert updated == []
        assert skipped == []

        # Verify the second value was used for API_KEY
        api_key_entry = next((e for e in created if e.key == "API_KEY"), None)
        assert api_key_entry is not None
        assert api_key_entry.value == "second_value"

    @pytest.mark.asyncio
    async def test_bulk_create_skips_existing_keys(self) -> None:
        """Under SKIP strategy (default), entries with existing keys are dropped."""
        db = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        # One existing row in the org — represented by a stub object with the key
        existing_stub = MagicMock()
        existing_stub.key = "EXISTING_KEY"
        self.ops.get_existing_rows_by_keys = AsyncMock(return_value={"EXISTING_KEY": existing_stub})

        entries = [
            AppInfoBulkEntry(key="EXISTING_KEY", value="new_value"),
            AppInfoBulkEntry(key="NEW_KEY", value="new_value"),
        ]

        created, updated, skipped = await self.ops.bulk_create(
            db,
            user_id=self.user_id,
            product_id=self.product_id,
            entries=entries,
        )

        # Should only create 1 entry, skip 1
        assert len(created) == 1
        assert created[0].key == "NEW_KEY"
        assert updated == []
        assert skipped == ["EXISTING_KEY"]


class TestAppInfoBulkCreateUpdateStrategy:
    """Tests for the UPDATE conflict_strategy path in bulk_create.

    These tests assert the merge-rule contract from Phase 1's plan, by mocking
    `self.update()` and inspecting the partial payload bulk_create assembles.
    The actual write (re-encryption, updated_at, tag normalization) flows
    through `update()` and is exercised by the integration suite.
    """

    def setup_method(self) -> None:
        self.ops = AppInfoOperations()
        self.user_id = uuid.uuid4()
        self.product_id = uuid.uuid4()

    def _existing(self, *, key: str, **fields: object) -> MagicMock:
        """Build a stub for an existing AppInfo row with sane defaults."""
        stub = MagicMock()
        stub.key = key
        stub.is_secret = fields.get("is_secret", False)
        stub.tags = fields.get("tags", [])
        stub.target_file = fields.get("target_file")
        stub.description = fields.get("description")
        stub.category = fields.get("category", "env")
        return stub

    @pytest.mark.asyncio
    async def test_update_strategy_overwrites_value(self) -> None:
        """Existing key + UPDATE strategy delegates to self.update() with new value."""
        db = MagicMock()
        db.flush = AsyncMock()

        existing = self._existing(key="API_KEY")
        self.ops.get_existing_rows_by_keys = AsyncMock(return_value={"API_KEY": existing})
        # Mock update() to return the row it was given (we just want to inspect args)
        self.ops.update = AsyncMock(side_effect=lambda db, db_obj, obj_in: db_obj)

        entries = [AppInfoBulkEntry(key="API_KEY", value="new_value")]
        created, updated, skipped = await self.ops.bulk_create(
            db,
            user_id=self.user_id,
            product_id=self.product_id,
            entries=entries,
            conflict_strategy=ConflictStrategy.UPDATE,
        )

        assert created == []
        assert skipped == []
        assert len(updated) == 1
        # Inspect the payload that was sent to update()
        self.ops.update.assert_awaited_once()
        kwargs = self.ops.update.await_args.kwargs
        assert kwargs["db_obj"] is existing
        assert kwargs["obj_in"]["value"] == "new_value"

    @pytest.mark.asyncio
    async def test_update_strategy_omits_is_secret_to_preserve_existing_flag(self) -> None:
        """`is_secret` must NOT appear in the partial payload — preserves existing flag.

        Pasting cannot flip a row from non-secret to secret or vice versa. The
        contract is enforced by simply not passing is_secret to update(), which
        falls back to db_obj.is_secret for both the encryption decision and
        the field assignment.
        """
        db = MagicMock()
        db.flush = AsyncMock()

        existing = self._existing(key="DB_PASSWORD", is_secret=True)
        self.ops.get_existing_rows_by_keys = AsyncMock(return_value={"DB_PASSWORD": existing})
        self.ops.update = AsyncMock(side_effect=lambda db, db_obj, obj_in: db_obj)

        # Pasted entry tries to flip is_secret to False
        entries = [AppInfoBulkEntry(key="DB_PASSWORD", value="rotated", is_secret=False)]
        await self.ops.bulk_create(
            db,
            user_id=self.user_id,
            product_id=self.product_id,
            entries=entries,
            conflict_strategy=ConflictStrategy.UPDATE,
        )

        kwargs = self.ops.update.await_args.kwargs
        assert "is_secret" not in kwargs["obj_in"]

    @pytest.mark.asyncio
    async def test_update_strategy_replaces_tags_only_when_explicit(self) -> None:
        """Tags are replaced only if the pasted entry has explicit tags."""
        db = MagicMock()
        db.flush = AsyncMock()

        existing_tagged = self._existing(key="TAGGED", tags=["env"])
        existing_no_explicit = self._existing(key="NO_EXPLICIT", tags=["env"])
        self.ops.get_existing_rows_by_keys = AsyncMock(
            return_value={"TAGGED": existing_tagged, "NO_EXPLICIT": existing_no_explicit}
        )
        self.ops.update = AsyncMock(side_effect=lambda db, db_obj, obj_in: db_obj)

        entries = [
            AppInfoBulkEntry(key="TAGGED", value="v", tags=["production", "auth"]),
            AppInfoBulkEntry(key="NO_EXPLICIT", value="v"),  # tags=[] default
        ]
        await self.ops.bulk_create(
            db,
            user_id=self.user_id,
            product_id=self.product_id,
            entries=entries,
            conflict_strategy=ConflictStrategy.UPDATE,
            default_tags=["should-not-clobber"],
        )

        # Two update() calls — one per existing row
        assert self.ops.update.await_count == 2
        payloads = {
            call.kwargs["db_obj"].key: call.kwargs["obj_in"]
            for call in self.ops.update.await_args_list
        }
        # Explicit tags → replaced
        assert payloads["TAGGED"]["tags"] == ["production", "auth"]
        # No explicit tags → tags key omitted (default_tags must NOT clobber)
        assert "tags" not in payloads["NO_EXPLICIT"]

    @pytest.mark.asyncio
    async def test_update_strategy_target_file_only_fills_when_existing_is_none(self) -> None:
        """target_file: adopt pasted value only if existing has none; otherwise preserve."""
        db = MagicMock()
        db.flush = AsyncMock()

        existing_with_file = self._existing(key="HAS_FILE", target_file=".env")
        existing_no_file = self._existing(key="NO_FILE", target_file=None)
        self.ops.get_existing_rows_by_keys = AsyncMock(
            return_value={"HAS_FILE": existing_with_file, "NO_FILE": existing_no_file}
        )
        self.ops.update = AsyncMock(side_effect=lambda db, db_obj, obj_in: db_obj)

        entries = [
            AppInfoBulkEntry(key="HAS_FILE", value="v", target_file=".env.local"),
            AppInfoBulkEntry(key="NO_FILE", value="v", target_file=".env.local"),
        ]
        await self.ops.bulk_create(
            db,
            user_id=self.user_id,
            product_id=self.product_id,
            entries=entries,
            conflict_strategy=ConflictStrategy.UPDATE,
        )

        payloads = {
            call.kwargs["db_obj"].key: call.kwargs["obj_in"]
            for call in self.ops.update.await_args_list
        }
        # Existing had a target_file → not in payload (preserved)
        assert "target_file" not in payloads["HAS_FILE"]
        # Existing was None → adopted from paste
        assert payloads["NO_FILE"]["target_file"] == ".env.local"

    @pytest.mark.asyncio
    async def test_update_strategy_mixed_batch(self) -> None:
        """A batch with both new and existing entries returns both lists populated."""
        db = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        existing = self._existing(key="EXISTING")
        self.ops.get_existing_rows_by_keys = AsyncMock(return_value={"EXISTING": existing})
        self.ops.update = AsyncMock(side_effect=lambda db, db_obj, obj_in: db_obj)

        entries = [
            AppInfoBulkEntry(key="EXISTING", value="rewritten"),
            AppInfoBulkEntry(key="BRAND_NEW", value="fresh"),
        ]
        created, updated, skipped = await self.ops.bulk_create(
            db,
            user_id=self.user_id,
            product_id=self.product_id,
            entries=entries,
            conflict_strategy=ConflictStrategy.UPDATE,
        )

        assert len(created) == 1
        assert created[0].key == "BRAND_NEW"
        assert len(updated) == 1
        assert skipped == []
        # New entries still go through the insert flush, not update()
        self.ops.update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_strategy_does_not_send_default_tags_to_update_payload(self) -> None:
        """default_tags is reserved for new entries; never propagated into update payloads."""
        db = MagicMock()
        db.flush = AsyncMock()

        existing = self._existing(key="K")
        self.ops.get_existing_rows_by_keys = AsyncMock(return_value={"K": existing})
        self.ops.update = AsyncMock(side_effect=lambda db, db_obj, obj_in: db_obj)

        entries = [AppInfoBulkEntry(key="K", value="v")]  # no explicit tags
        await self.ops.bulk_create(
            db,
            user_id=self.user_id,
            product_id=self.product_id,
            entries=entries,
            default_tags=["imported"],
            conflict_strategy=ConflictStrategy.UPDATE,
        )

        payload = self.ops.update.await_args.kwargs["obj_in"]
        assert "tags" not in payload


class TestGetExistingRowsByKeys:
    """Tests for AppInfoOperations.get_existing_rows_by_keys method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.ops = AppInfoOperations()

    @pytest.mark.asyncio
    async def test_returns_matching_rows_keyed_by_key(self) -> None:
        """Returns dict of {key: AppInfo row} for keys that exist in the product."""
        db = AsyncMock()

        # Mock execute to return two stub rows
        row1 = MagicMock()
        row1.key = "KEY1"
        row2 = MagicMock()
        row2.key = "KEY2"
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [row1, row2]
        db.execute = AsyncMock(return_value=mock_result)

        result = await self.ops.get_existing_rows_by_keys(
            db,
            product_id=uuid.uuid4(),
            keys=["KEY1", "KEY2", "KEY3"],
        )

        assert set(result.keys()) == {"KEY1", "KEY2"}
        assert result["KEY1"] is row1
        assert result["KEY2"] is row2

    @pytest.mark.asyncio
    async def test_empty_keys_short_circuits(self) -> None:
        """Empty keys list returns empty dict without hitting the DB."""
        db = AsyncMock()
        result = await self.ops.get_existing_rows_by_keys(db, product_id=uuid.uuid4(), keys=[])
        assert result == {}
        db.execute.assert_not_called()


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
