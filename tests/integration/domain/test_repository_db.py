"""DB integration tests for RepositoryOperations.

Tests real SQL against PostgreSQL via rollback fixture.
Covers: create, product/org scoping, GitHub ID lookup, full_name rename, bulk delete.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.repository_operations import repository_ops


# ─────────────────────────────────────────────────────────────────────────────
# CRUD and lookups
# ─────────────────────────────────────────────────────────────────────────────


class TestRepositoryCRUD:
    """Test repository create, read, update, delete."""

    async def test_create_repository(
        self, db_session: AsyncSession, test_user, test_product
    ):
        """Can create a repository linked to a product."""
        repo = await repository_ops.create(
            db_session,
            obj_in={
                "name": "my-repo",
                "full_name": "org/my-repo",
                "product_id": test_product.id,
                "github_id": 999999,
                "language": "TypeScript",
            },
            imported_by_user_id=test_user.id,
        )

        assert repo.id is not None
        assert repo.name == "my-repo"
        assert repo.full_name == "org/my-repo"
        assert repo.imported_by_user_id == test_user.id
        assert repo.github_id == 999999

    async def test_get_by_product(
        self, db_session: AsyncSession, test_product, test_repository
    ):
        """get_by_product returns repos for the given product."""
        repos = await repository_ops.get_by_product(db_session, test_product.id)
        repo_ids = [r.id for r in repos]
        assert test_repository.id in repo_ids

    async def test_get_by_org(
        self, db_session: AsyncSession, test_org, test_repository
    ):
        """get_by_org returns repos across all products in the org."""
        repos = await repository_ops.get_by_org(db_session, test_org.id)
        repo_ids = [r.id for r in repos]
        assert test_repository.id in repo_ids

    async def test_count_by_org(
        self, db_session: AsyncSession, test_org, test_repository  # noqa: ARG002
    ):
        """count_by_org returns correct count of repos in org."""
        count = await repository_ops.count_by_org(db_session, test_org.id)
        assert count >= 1

    async def test_delete_repository(
        self, db_session: AsyncSession, test_repository
    ):
        """Can delete a repository by ID."""
        deleted = await repository_ops.delete(db_session, test_repository.id)
        assert deleted is True

        found = await repository_ops.get(db_session, test_repository.id)
        assert found is None


# ─────────────────────────────────────────────────────────────────────────────
# GitHub ID lookup
# ─────────────────────────────────────────────────────────────────────────────


class TestRepositoryGitHub:
    """Test GitHub-specific lookups."""

    async def test_get_by_github_id(
        self, db_session: AsyncSession, test_product, test_repository
    ):
        """Can find a repo by GitHub ID within a product."""
        found = await repository_ops.get_by_github_id(
            db_session, test_product.id, test_repository.github_id
        )
        assert found is not None
        assert found.id == test_repository.id

    async def test_get_by_full_name(
        self, db_session: AsyncSession, test_repository
    ):
        """Can find a repo by owner/repo full name."""
        found = await repository_ops.get_by_full_name(
            db_session, test_repository.full_name
        )
        assert found is not None
        assert found.id == test_repository.id

    async def test_update_full_name(
        self, db_session: AsyncSession, test_repository
    ):
        """update_full_name updates both full_name and name."""
        updated = await repository_ops.update_full_name(
            db_session, test_repository.id, "new-owner/renamed-repo"
        )
        assert updated is not None
        assert updated.full_name == "new-owner/renamed-repo"
        assert updated.name == "renamed-repo"


# ─────────────────────────────────────────────────────────────────────────────
# Bulk operations
# ─────────────────────────────────────────────────────────────────────────────


class TestRepositoryBulkOps:
    """Test bulk operations."""

    async def test_bulk_delete_except(
        self, db_session: AsyncSession, test_user, test_org, test_product
    ):
        """bulk_delete_except deletes all repos in org except those in keep_ids."""
        # Create 3 repos
        repos = []
        for i in range(3):
            repo = await repository_ops.create(
                db_session,
                obj_in={
                    "name": f"bulk-repo-{i}",
                    "product_id": test_product.id,
                    "github_id": 200000 + i,
                },
                imported_by_user_id=test_user.id,
            )
            repos.append(repo)

        # Keep only the first one
        deleted_count = await repository_ops.bulk_delete_except(
            db_session, test_org.id, keep_ids=[repos[0].id]
        )
        assert deleted_count == 2

        # Verify the kept one still exists
        remaining = await repository_ops.get_by_org(db_session, test_org.id)
        remaining_ids = [r.id for r in remaining]
        assert repos[0].id in remaining_ids
        assert repos[1].id not in remaining_ids
        assert repos[2].id not in remaining_ids
