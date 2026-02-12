"""Unit tests for RepositoryOperations — all DB calls mocked."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.repository_operations import RepositoryOperations

from tests.helpers.mock_factories import (
    make_mock_repository,
    mock_scalar_result,
    mock_scalars_result,
)


class TestRepositoryGet:
    """Tests for single repository retrieval."""

    def setup_method(self):
        self.ops = RepositoryOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_get_returns_repository(self):
        repo = make_mock_repository()
        self.db.execute = AsyncMock(return_value=mock_scalar_result(repo))

        result = await self.ops.get(self.db, repo.id)
        assert result == repo

    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_found(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(None))

        result = await self.ops.get(self.db, uuid.uuid4())
        assert result is None


class TestRepositoryCountByOrg:
    """Tests for org-scoped repository counting."""

    def setup_method(self):
        self.ops = RepositoryOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_count_returns_integer(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(5))

        result = await self.ops.count_by_org(self.db, uuid.uuid4())
        assert result == 5

    @pytest.mark.asyncio
    async def test_count_returns_zero_when_no_repos(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(0))

        result = await self.ops.count_by_org(self.db, uuid.uuid4())
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_returns_zero_when_null(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(None))

        result = await self.ops.count_by_org(self.db, uuid.uuid4())
        assert result == 0


class TestRepositoryGetByOrg:
    """Tests for org-scoped repository listing."""

    def setup_method(self):
        self.ops = RepositoryOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_list_of_repos(self):
        repos = [make_mock_repository(name=f"repo-{i}") for i in range(3)]
        self.db.execute = AsyncMock(return_value=mock_scalars_result(repos))

        result = await self.ops.get_by_org(self.db, uuid.uuid4())
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_repos(self):
        self.db.execute = AsyncMock(return_value=mock_scalars_result([]))

        result = await self.ops.get_by_org(self.db, uuid.uuid4())
        assert result == []


class TestRepositoryGetByProduct:
    """Tests for product-scoped repository listing."""

    def setup_method(self):
        self.ops = RepositoryOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_repos_for_product(self):
        product_id = uuid.uuid4()
        repos = [make_mock_repository(product_id=product_id) for _ in range(2)]
        self.db.execute = AsyncMock(return_value=mock_scalars_result(repos))

        result = await self.ops.get_by_product(self.db, product_id)
        assert len(result) == 2


class TestRepositoryGetByGithubId:
    """Tests for GitHub ID lookup within a product."""

    def setup_method(self):
        self.ops = RepositoryOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_finds_repo_by_github_id(self):
        repo = make_mock_repository(github_id=12345)
        self.db.execute = AsyncMock(return_value=mock_scalar_result(repo))

        result = await self.ops.get_by_github_id(self.db, repo.product_id, 12345)
        assert result == repo

    @pytest.mark.asyncio
    async def test_returns_none_when_github_id_not_found(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(None))

        result = await self.ops.get_by_github_id(self.db, uuid.uuid4(), 99999)
        assert result is None


class TestRepositoryFindByGithubId:
    """Tests for global GitHub ID lookup (cross-product)."""

    def setup_method(self):
        self.ops = RepositoryOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_finds_repo_across_products(self):
        repo = make_mock_repository(github_id=12345)
        self.db.execute = AsyncMock(return_value=mock_scalar_result(repo))

        result = await self.ops.find_by_github_id(self.db, 12345)
        assert result == repo


class TestRepositoryCreate:
    """Tests for repository creation."""

    def setup_method(self):
        self.ops = RepositoryOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_create_adds_and_flushes(self):
        user_id = uuid.uuid4()
        product_id = uuid.uuid4()
        obj_in = {"name": "__test_repo", "product_id": product_id}

        self.db.add = MagicMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()

        result = await self.ops.create(self.db, obj_in, user_id)
        self.db.add.assert_called_once()
        self.db.flush.assert_awaited_once()
        self.db.refresh.assert_awaited_once()

        added_obj = self.db.add.call_args[0][0]
        assert added_obj.imported_by_user_id == user_id


class TestRepositoryUpdate:
    """Tests for repository updates."""

    def setup_method(self):
        self.ops = RepositoryOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_update_sets_fields(self):
        repo = make_mock_repository()
        self.db.add = MagicMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()

        result = await self.ops.update(self.db, repo, {"name": "new_name"})
        assert result.name == "new_name"

    @pytest.mark.asyncio
    async def test_update_applies_none_values(self):
        """update() applies all keys including None — callers should exclude_unset."""
        repo = make_mock_repository(name="original")
        self.db.add = MagicMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()

        await self.ops.update(self.db, repo, {"name": None, "url": "https://new.url"})
        assert repo.name is None
        assert repo.url == "https://new.url"


class TestRepositoryDelete:
    """Tests for repository deletion."""

    def setup_method(self):
        self.ops = RepositoryOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_delete_returns_true_when_found(self):
        repo = make_mock_repository()
        self.db.execute = AsyncMock(return_value=mock_scalar_result(repo))
        self.db.delete = AsyncMock()
        self.db.flush = AsyncMock()

        result = await self.ops.delete(self.db, repo.id)
        assert result is True
        self.db.delete.assert_awaited_once_with(repo)

    @pytest.mark.asyncio
    async def test_delete_returns_false_when_not_found(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(None))

        result = await self.ops.delete(self.db, uuid.uuid4())
        assert result is False


class TestRepositoryBulkDeleteExcept:
    """Tests for bulk deletion (subscription downgrade flow)."""

    def setup_method(self):
        self.ops = RepositoryOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_deletes_repos_not_in_keep_list(self):
        keep_id = uuid.uuid4()
        delete_id_1 = uuid.uuid4()
        delete_id_2 = uuid.uuid4()

        repos = [
            make_mock_repository(id=keep_id),
            make_mock_repository(id=delete_id_1),
            make_mock_repository(id=delete_id_2),
        ]
        self.db.execute = AsyncMock(return_value=mock_scalars_result(repos))
        self.db.delete = AsyncMock()
        self.db.flush = AsyncMock()

        result = await self.ops.bulk_delete_except(
            self.db, uuid.uuid4(), keep_ids=[keep_id]
        )
        assert result == 2
        assert self.db.delete.await_count == 2

    @pytest.mark.asyncio
    async def test_deletes_nothing_when_all_kept(self):
        repo_id = uuid.uuid4()
        repos = [make_mock_repository(id=repo_id)]
        self.db.execute = AsyncMock(return_value=mock_scalars_result(repos))
        self.db.flush = AsyncMock()

        result = await self.ops.bulk_delete_except(
            self.db, uuid.uuid4(), keep_ids=[repo_id]
        )
        assert result == 0


class TestRepositoryGetByFullName:
    """Tests for full_name (owner/repo) lookup."""

    def setup_method(self):
        self.ops = RepositoryOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_finds_repo_by_full_name(self):
        repo = make_mock_repository(full_name="test-org/my-repo")
        self.db.execute = AsyncMock(return_value=mock_scalar_result(repo))

        result = await self.ops.get_by_full_name(self.db, "test-org/my-repo")
        assert result == repo


class TestRepositoryUpdateFullName:
    """Tests for GitHub rename/transfer handling."""

    def setup_method(self):
        self.ops = RepositoryOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_updates_full_name_and_extracts_new_name(self):
        repo = make_mock_repository(full_name="old-org/old-repo", name="old-repo")
        self.db.execute = AsyncMock(return_value=mock_scalar_result(repo))
        self.db.add = MagicMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()

        result = await self.ops.update_full_name(self.db, repo.id, "new-org/new-repo")
        assert result.full_name == "new-org/new-repo"
        assert result.name == "new-repo"

    @pytest.mark.asyncio
    async def test_returns_none_when_repo_not_found(self):
        self.db.execute = AsyncMock(return_value=mock_scalar_result(None))

        result = await self.ops.update_full_name(self.db, uuid.uuid4(), "org/repo")
        assert result is None

    @pytest.mark.asyncio
    async def test_handles_name_without_slash(self):
        repo = make_mock_repository()
        self.db.execute = AsyncMock(return_value=mock_scalar_result(repo))
        self.db.add = MagicMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()

        result = await self.ops.update_full_name(self.db, repo.id, "just-name")
        assert result.full_name == "just-name"
        assert result.name == "just-name"


class TestRepositoryGetGithubReposByProduct:
    """Tests for GitHub-linked repos within a product."""

    def setup_method(self):
        self.ops = RepositoryOperations()
        self.db = AsyncMock()

    @pytest.mark.asyncio
    async def test_returns_only_github_repos(self):
        repos = [make_mock_repository(github_id=i) for i in range(3)]
        self.db.execute = AsyncMock(return_value=mock_scalars_result(repos))

        result = await self.ops.get_github_repos_by_product(self.db, uuid.uuid4())
        assert len(result) == 3
