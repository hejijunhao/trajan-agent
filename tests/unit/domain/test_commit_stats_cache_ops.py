"""Unit tests for CommitStatsCacheOperations — all DB calls mocked."""

from unittest.mock import AsyncMock

import pytest

from app.domain.commit_stats_cache_operations import CommitStatsCacheOperations

from tests.helpers.mock_factories import make_mock_commit_stats_cache, mock_scalars_result


class TestGetBulkByRepoShas:
    """Tests for bulk cache lookups."""

    def setup_method(self):
        self.ops = CommitStatsCacheOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_empty_dict_for_empty_lookups(self):
        result = await self.ops.get_bulk_by_repo_shas(self.db, [])
        assert result == {}
        self.db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_cache_hits_keyed_by_tuple(self):
        cache1 = make_mock_commit_stats_cache(
            repository_full_name="org/repo1", commit_sha="aaa111"
        )
        cache2 = make_mock_commit_stats_cache(
            repository_full_name="org/repo2", commit_sha="bbb222"
        )
        self.db.execute = AsyncMock(return_value=mock_scalars_result([cache1, cache2]))

        lookups = [("org/repo1", "aaa111"), ("org/repo2", "bbb222")]
        result = await self.ops.get_bulk_by_repo_shas(self.db, lookups)

        assert len(result) == 2
        assert ("org/repo1", "aaa111") in result
        assert ("org/repo2", "bbb222") in result
        assert result[("org/repo1", "aaa111")] == cache1

    @pytest.mark.asyncio
    async def test_missing_entries_not_in_result(self):
        cache1 = make_mock_commit_stats_cache(
            repository_full_name="org/repo1", commit_sha="aaa111"
        )
        self.db.execute = AsyncMock(return_value=mock_scalars_result([cache1]))

        lookups = [("org/repo1", "aaa111"), ("org/repo2", "missing")]
        result = await self.ops.get_bulk_by_repo_shas(self.db, lookups)

        assert len(result) == 1
        assert ("org/repo2", "missing") not in result


class TestBulkUpsert:
    """Tests for bulk insert of commit stats."""

    def setup_method(self):
        self.ops = CommitStatsCacheOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_list(self):
        result = await self.ops.bulk_upsert(self.db, [])
        assert result == 0
        self.db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_count_of_inserted_rows(self):
        stats = [
            {
                "full_name": "org/repo",
                "sha": "abc123",
                "additions": 10,
                "deletions": 5,
                "files_changed": 3,
            },
            {
                "full_name": "org/repo",
                "sha": "def456",
                "additions": 20,
                "deletions": 10,
                "files_changed": 5,
            },
        ]
        self.db.execute = AsyncMock()
        self.db.flush = AsyncMock()

        result = await self.ops.bulk_upsert(self.db, stats)
        assert result == 2
        self.db.execute.assert_awaited_once()
        self.db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_single_stat_upsert(self):
        stats = [
            {
                "full_name": "org/repo",
                "sha": "abc123",
                "additions": 1,
                "deletions": 0,
                "files_changed": 1,
            },
        ]
        self.db.execute = AsyncMock()
        self.db.flush = AsyncMock()

        result = await self.ops.bulk_upsert(self.db, stats)
        assert result == 1
