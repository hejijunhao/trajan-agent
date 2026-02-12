"""DB integration tests for AppInfoOperations.

Tests real SQL against PostgreSQL via rollback fixture.
Covers: create with tag normalization, tag filter (PostgreSQL array containment),
get_all_tags (unnest + distinct), get_by_key, bulk_create skips duplicates,
and secret encryption round-trip.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.app_info_operations import app_info_ops, normalize_tags
from app.models.app_info import AppInfoBulkEntry


# ─────────────────────────────────────────────────────────────────────────────
# Create with tag normalization
# ─────────────────────────────────────────────────────────────────────────────


class TestAppInfoCreate:
    """Test app info creation with tags and encryption."""

    async def test_create_with_tags(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """Tags are normalized (lowercased, sorted, deduped) on create."""
        entry = await app_info_ops.create(
            db_session,
            obj_in={
                "key": "API_KEY",
                "value": "test-value-123",
                "category": "env_var",
                "product_id": test_product.id,
                "tags": ["Production", "AUTH", "production"],  # Mixed case + dupe
            },
            user_id=test_user.id,
        )

        assert entry.id is not None
        assert entry.key == "API_KEY"
        assert entry.tags == ["auth", "production"]  # lowercased, deduped, sorted

    async def test_create_secret_encrypts_value(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """Secret entries have their value encrypted (if encryption is enabled)."""
        entry = await app_info_ops.create(
            db_session,
            obj_in={
                "key": "DB_PASSWORD",
                "value": "super-secret-password",
                "category": "credential",
                "is_secret": True,
                "product_id": test_product.id,
            },
            user_id=test_user.id,
        )

        assert entry.is_secret is True
        # Value should either be encrypted or pass-through (depending on config)
        # The decrypt round-trip should always return the original
        decrypted = app_info_ops.decrypt_entry_value(entry)
        assert decrypted == "super-secret-password"

    def test_normalize_tags_function(self):
        """normalize_tags handles edge cases correctly."""
        assert normalize_tags(None) == []
        assert normalize_tags([]) == []
        assert normalize_tags(["HELLO", "world", "Hello"]) == ["hello", "world"]
        assert normalize_tags(["valid-tag", "@invalid!"]) == ["valid-tag"]
        assert normalize_tags(["a" * 50]) == []  # Exceeds MAX_TAG_LENGTH


# ─────────────────────────────────────────────────────────────────────────────
# Tag filtering (PostgreSQL array containment @>)
# ─────────────────────────────────────────────────────────────────────────────


class TestAppInfoTagFilter:
    """Test PostgreSQL array containment operator for tag filtering."""

    async def test_filter_by_tags(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """Filtering by tags uses AND logic — entries must have ALL specified tags."""
        # Entry with both tags
        await app_info_ops.create(
            db_session,
            obj_in={
                "key": "TAGGED_BOTH",
                "value": "v1",
                "product_id": test_product.id,
                "tags": ["auth", "production"],
            },
            user_id=test_user.id,
        )
        # Entry with only one tag
        await app_info_ops.create(
            db_session,
            obj_in={
                "key": "TAGGED_ONE",
                "value": "v2",
                "product_id": test_product.id,
                "tags": ["auth"],
            },
            user_id=test_user.id,
        )

        # Filter by both tags — should only return the entry with both
        results = await app_info_ops.get_by_product(
            db_session, test_user.id, test_product.id, tags=["auth", "production"]
        )
        keys = [r.key for r in results]
        assert "TAGGED_BOTH" in keys
        assert "TAGGED_ONE" not in keys

    async def test_get_all_tags(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """get_all_tags returns sorted unique tags via unnest + distinct."""
        await app_info_ops.create(
            db_session,
            obj_in={
                "key": "KEY_A",
                "value": "v",
                "product_id": test_product.id,
                "tags": ["backend", "api"],
            },
            user_id=test_user.id,
        )
        await app_info_ops.create(
            db_session,
            obj_in={
                "key": "KEY_B",
                "value": "v",
                "product_id": test_product.id,
                "tags": ["api", "frontend"],
            },
            user_id=test_user.id,
        )

        tags = await app_info_ops.get_all_tags(
            db_session, test_user.id, test_product.id
        )
        assert tags == ["api", "backend", "frontend"]


# ─────────────────────────────────────────────────────────────────────────────
# Key lookup and bulk create
# ─────────────────────────────────────────────────────────────────────────────


class TestAppInfoKeyOps:
    """Test key-based lookups and bulk operations."""

    async def test_get_by_key(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """Can retrieve an entry by its key (user-scoped)."""
        await app_info_ops.create(
            db_session,
            obj_in={
                "key": "UNIQUE_KEY",
                "value": "unique-value",
                "product_id": test_product.id,
            },
            user_id=test_user.id,
        )

        found = await app_info_ops.get_by_key(
            db_session, test_user.id, test_product.id, "UNIQUE_KEY"
        )
        assert found is not None
        assert found.value == "unique-value"

    async def test_bulk_create_skips_duplicates(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """bulk_create skips keys that already exist."""
        # Create an existing entry
        await app_info_ops.create(
            db_session,
            obj_in={
                "key": "EXISTING",
                "value": "old-value",
                "product_id": test_product.id,
            },
            user_id=test_user.id,
        )

        # Bulk create with one existing + one new
        entries = [
            AppInfoBulkEntry(key="EXISTING", value="new-value"),
            AppInfoBulkEntry(key="BRAND_NEW", value="fresh-value"),
        ]
        created, skipped = await app_info_ops.bulk_create(
            db_session, test_user.id, test_product.id, entries
        )

        assert len(created) == 1
        assert created[0].key == "BRAND_NEW"
        assert skipped == ["EXISTING"]

        # Verify original value unchanged
        original = await app_info_ops.get_by_key(
            db_session, test_user.id, test_product.id, "EXISTING"
        )
        assert original is not None
        assert original.value == "old-value"

    async def test_bulk_create_with_default_tags(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """bulk_create applies default_tags to entries without their own tags."""
        entries = [
            AppInfoBulkEntry(key="NO_TAGS", value="v1"),
            AppInfoBulkEntry(key="OWN_TAGS", value="v2", tags=["custom"]),
        ]
        created, _ = await app_info_ops.bulk_create(
            db_session,
            test_user.id,
            test_product.id,
            entries,
            default_tags=["imported"],
        )

        by_key = {e.key: e for e in created}
        assert by_key["NO_TAGS"].tags == ["imported"]
        assert by_key["OWN_TAGS"].tags == ["custom"]
