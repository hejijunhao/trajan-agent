"""API endpoint tests for GitHub integration routes.

Tests the HTTP layer: request validation, response shapes, error codes,
and coordination between the API handler and the GitHub service + domain ops.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.services.github.exceptions import GitHubAPIError, GitHubRepoRenamed
from app.services.github.types import GitHubRepo, GitHubReposResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _github_repo(github_id: int = 1001, name: str = "test-repo") -> GitHubRepo:
    """Build a GitHubRepo fixture for mocked responses."""
    return GitHubRepo(
        github_id=github_id,
        name=name,
        full_name=f"octocat/{name}",
        description="A test repo",
        url=f"https://github.com/octocat/{name}",
        default_branch="main",
        is_private=False,
        language="Python",
        stars_count=10,
        forks_count=2,
        updated_at="2026-01-15T00:00:00Z",
    )


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/v1/github/repos — List user's GitHub repos
# ═══════════════════════════════════════════════════════════════════════════


class TestListGitHubRepos:
    """Tests for the list repos endpoint."""

    @pytest.mark.anyio
    async def test_lists_repos_successfully(
        self, api_client: AsyncClient, test_subscription, db_session, test_user
    ):
        """GET /api/v1/github/repos returns repo list with import status."""
        mock_response = GitHubReposResponse(
            repos=[_github_repo()],
            total_count=1,
            has_more=False,
            rate_limit_remaining=59,
        )

        with (
            patch(
                "app.api.v1.github.get_github_token", new_callable=AsyncMock
            ) as mock_token,
            patch("app.api.v1.github.GitHubService") as MockService,
        ):
            mock_token.return_value = "ghp_fake"
            instance = MockService.return_value
            instance.get_user_repos = AsyncMock(return_value=mock_response)

            resp = await api_client.get("/api/v1/github/repos")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["repos"]) == 1
        assert data["repos"][0]["name"] == "test-repo"
        assert data["repos"][0]["already_imported"] is False
        assert data["has_more"] is False

    @pytest.mark.anyio
    async def test_returns_400_without_github_token(
        self, api_client: AsyncClient, test_subscription
    ):
        """GET /api/v1/github/repos returns 400 when no token configured."""
        with patch(
            "app.api.v1.github.get_github_token", new_callable=AsyncMock
        ) as mock_token:
            from fastapi import HTTPException

            mock_token.side_effect = HTTPException(status_code=400, detail="GitHub token not configured")
            resp = await api_client.get("/api/v1/github/repos")

        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_returns_502_on_github_error(
        self, api_client: AsyncClient, test_subscription
    ):
        """GET /api/v1/github/repos returns 502 on GitHub API failure."""
        with (
            patch(
                "app.api.v1.github.get_github_token", new_callable=AsyncMock
            ) as mock_token,
            patch("app.api.v1.github.GitHubService") as MockService,
        ):
            mock_token.return_value = "ghp_fake"
            instance = MockService.return_value
            instance.get_user_repos = AsyncMock(
                side_effect=GitHubAPIError("Server error", 502)
            )

            resp = await api_client.get("/api/v1/github/repos")

        assert resp.status_code == 502

    @pytest.mark.anyio
    async def test_rate_limit_includes_reset_time(
        self, api_client: AsyncClient, test_subscription
    ):
        """Rate limit errors include reset time in the detail message."""
        with (
            patch(
                "app.api.v1.github.get_github_token", new_callable=AsyncMock
            ) as mock_token,
            patch("app.api.v1.github.GitHubService") as MockService,
        ):
            mock_token.return_value = "ghp_fake"
            instance = MockService.return_value
            instance.get_user_repos = AsyncMock(
                side_effect=GitHubAPIError("rate limit", 403, rate_limit_reset=9999999999)
            )

            resp = await api_client.get("/api/v1/github/repos")

        assert resp.status_code == 403
        assert "minutes" in resp.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/v1/github/import — Import repos into a product
# ═══════════════════════════════════════════════════════════════════════════


class TestImportGitHubRepos:
    """Tests for the import repos endpoint."""

    @pytest.mark.anyio
    async def test_import_success(
        self, api_client: AsyncClient, test_product, test_subscription
    ):
        """POST /api/v1/github/import creates repository records."""
        repo = _github_repo(github_id=2001, name="new-repo")
        mock_repos_response = GitHubReposResponse(
            repos=[repo], total_count=1, has_more=False, rate_limit_remaining=50,
        )

        with (
            patch("app.api.v1.github.get_github_token", new_callable=AsyncMock) as mock_token,
            patch("app.api.v1.github.GitHubService") as MockService,
            patch("app.api.v1.github.maybe_auto_trigger_docs", new_callable=AsyncMock) as mock_docs,
            patch("app.api.v1.github.maybe_auto_trigger_analysis", new_callable=AsyncMock) as mock_analysis,
        ):
            mock_token.return_value = "ghp_fake"
            instance = MockService.return_value
            instance.get_user_repos = AsyncMock(return_value=mock_repos_response)
            instance.get_repo_details = AsyncMock(return_value=repo)
            mock_docs.return_value = True
            mock_analysis.return_value = True

            resp = await api_client.post(
                "/api/v1/github/import",
                json={
                    "product_id": str(test_product.id),
                    "github_ids": [2001],
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["imported"]) == 1
        assert data["imported"][0]["name"] == "new-repo"
        assert data["skipped"] == []

    @pytest.mark.anyio
    async def test_import_skips_already_imported(
        self,
        api_client: AsyncClient,
        test_product,
        test_subscription,
        db_session,
        test_user,
    ):
        """POST /api/v1/github/import skips repos already in the product."""
        from app.domain.repository_operations import repository_ops

        # Create a repo that's already linked to a github_id
        github_id = 3001
        await repository_ops.create(
            db_session,
            obj_in={
                "product_id": test_product.id,
                "name": "existing-repo",
                "full_name": "octocat/existing-repo",
                "github_id": github_id,
            },
            imported_by_user_id=test_user.id,
        )

        repo = _github_repo(github_id=github_id, name="existing-repo")
        mock_repos_response = GitHubReposResponse(
            repos=[repo], total_count=1, has_more=False, rate_limit_remaining=50,
        )

        with (
            patch("app.api.v1.github.get_github_token", new_callable=AsyncMock) as mock_token,
            patch("app.api.v1.github.GitHubService") as MockService,
        ):
            mock_token.return_value = "ghp_fake"
            instance = MockService.return_value
            instance.get_user_repos = AsyncMock(return_value=mock_repos_response)

            resp = await api_client.post(
                "/api/v1/github/import",
                json={
                    "product_id": str(test_product.id),
                    "github_ids": [github_id],
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["skipped"]) == 1
        assert "Already imported" in data["skipped"][0]["reason"]

    @pytest.mark.anyio
    async def test_import_product_not_found(
        self, api_client: AsyncClient, test_subscription
    ):
        """POST /api/v1/github/import returns 404 for non-existent product."""
        resp = await api_client.post(
            "/api/v1/github/import",
            json={
                "product_id": str(uuid.uuid4()),
                "github_ids": [1001],
            },
        )
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/v1/github/refresh/{id} — Refresh single repo
# ═══════════════════════════════════════════════════════════════════════════


class TestRefreshRepository:
    """Tests for the single repository refresh endpoint."""

    @pytest.mark.anyio
    async def test_refresh_success(
        self,
        api_client: AsyncClient,
        test_repository,
        test_subscription,
        db_session,
    ):
        """POST /api/v1/github/refresh/{id} updates metadata."""
        # Set github_id and full_name so the endpoint doesn't reject it
        test_repository.github_id = 5001
        test_repository.full_name = "octocat/test-repo"
        db_session.add(test_repository)
        await db_session.flush()

        fresh = _github_repo(github_id=5001, name="test-repo")

        with (
            patch("app.api.v1.github.get_github_token", new_callable=AsyncMock) as mock_token,
            patch("app.api.v1.github.GitHubService") as MockService,
        ):
            mock_token.return_value = "ghp_fake"
            instance = MockService.return_value
            instance.get_repo_details = AsyncMock(return_value=fresh)

            resp = await api_client.post(f"/api/v1/github/refresh/{test_repository.id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["stars_count"] == 10

    @pytest.mark.anyio
    async def test_refresh_repo_not_found(
        self, api_client: AsyncClient, test_subscription
    ):
        """POST /api/v1/github/refresh/{fake_id} returns 404."""
        resp = await api_client.post(f"/api/v1/github/refresh/{uuid.uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_refresh_non_github_repo(
        self,
        api_client: AsyncClient,
        test_repository,
        test_subscription,
        db_session,
    ):
        """POST /api/v1/github/refresh/{id} returns 400 for non-GitHub repo."""
        # Ensure github_id is None (manual repo)
        test_repository.github_id = None
        db_session.add(test_repository)
        await db_session.flush()

        resp = await api_client.post(f"/api/v1/github/refresh/{test_repository.id}")
        assert resp.status_code == 400
        assert "Not a GitHub" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_refresh_handles_rename(
        self,
        api_client: AsyncClient,
        test_repository,
        test_subscription,
        db_session,
    ):
        """Refresh resolves renamed repos by fetching the new name."""
        test_repository.github_id = 6001
        test_repository.full_name = "old-owner/old-name"
        db_session.add(test_repository)
        await db_session.flush()

        fresh = _github_repo(github_id=6001, name="new-name")

        with (
            patch("app.api.v1.github.get_github_token", new_callable=AsyncMock) as mock_token,
            patch("app.api.v1.github.GitHubService") as MockService,
        ):
            mock_token.return_value = "ghp_fake"
            instance = MockService.return_value
            # First call raises renamed, resolve_renamed_repo calls get_repo_details again
            instance.get_repo_details = AsyncMock(
                side_effect=[
                    GitHubRepoRenamed("old-owner/old-name", "octocat/new-name"),
                    fresh,
                ]
            )
            instance.get_repo_by_id = AsyncMock()

            resp = await api_client.post(f"/api/v1/github/refresh/{test_repository.id}")

        assert resp.status_code == 200
        assert resp.json()["name"] == "new-name"


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/v1/github/refresh-all — Bulk refresh
# ═══════════════════════════════════════════════════════════════════════════


class TestBulkRefreshRepos:
    """Tests for the bulk refresh endpoint."""

    @pytest.mark.anyio
    async def test_bulk_refresh_success(
        self,
        api_client: AsyncClient,
        test_product,
        test_subscription,
        db_session,
        test_user,
    ):
        """POST /api/v1/github/refresh-all refreshes all GitHub repos in product."""
        from app.domain.repository_operations import repository_ops

        # Create a GitHub-linked repo
        repo = await repository_ops.create(
            db_session,
            obj_in={
                "product_id": test_product.id,
                "name": "bulk-repo",
                "full_name": "octocat/bulk-repo",
                "github_id": 7001,
            },
            imported_by_user_id=test_user.id,
        )

        fresh = _github_repo(github_id=7001, name="bulk-repo")

        with (
            patch("app.api.v1.github.get_github_token", new_callable=AsyncMock) as mock_token,
            patch("app.api.v1.github.GitHubService") as MockService,
        ):
            mock_token.return_value = "ghp_fake"
            instance = MockService.return_value
            instance.get_repo_details = AsyncMock(return_value=fresh)

            resp = await api_client.post(
                "/api/v1/github/refresh-all",
                json={"product_id": str(test_product.id)},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["refreshed"]) >= 1
        assert data["failed"] == []

    @pytest.mark.anyio
    async def test_bulk_refresh_empty_product(
        self, api_client: AsyncClient, test_product, test_subscription
    ):
        """POST /api/v1/github/refresh-all with no repos returns empty lists."""
        with (
            patch("app.api.v1.github.get_github_token", new_callable=AsyncMock) as mock_token,
            patch("app.api.v1.github.GitHubService"),
        ):
            mock_token.return_value = "ghp_fake"

            resp = await api_client.post(
                "/api/v1/github/refresh-all",
                json={"product_id": str(test_product.id)},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["refreshed"] == []
        assert data["failed"] == []

    @pytest.mark.anyio
    async def test_bulk_refresh_product_not_found(
        self, api_client: AsyncClient, test_subscription
    ):
        """POST /api/v1/github/refresh-all returns 404 for unknown product."""
        resp = await api_client.post(
            "/api/v1/github/refresh-all",
            json={"product_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_bulk_refresh_continues_on_failure(
        self,
        api_client: AsyncClient,
        test_product,
        test_subscription,
        db_session,
        test_user,
    ):
        """Bulk refresh continues processing even when one repo fails."""
        from app.domain.repository_operations import repository_ops

        repo_ok = await repository_ops.create(
            db_session,
            obj_in={
                "product_id": test_product.id,
                "name": "ok-repo",
                "full_name": "octocat/ok-repo",
                "github_id": 8001,
            },
            imported_by_user_id=test_user.id,
        )
        repo_fail = await repository_ops.create(
            db_session,
            obj_in={
                "product_id": test_product.id,
                "name": "fail-repo",
                "full_name": "octocat/fail-repo",
                "github_id": 8002,
            },
            imported_by_user_id=test_user.id,
        )

        fresh_ok = _github_repo(github_id=8001, name="ok-repo")

        with (
            patch("app.api.v1.github.get_github_token", new_callable=AsyncMock) as mock_token,
            patch("app.api.v1.github.GitHubService") as MockService,
        ):
            mock_token.return_value = "ghp_fake"
            instance = MockService.return_value

            # First call succeeds, second fails
            call_count = 0
            original_repos = {"octocat/ok-repo": fresh_ok}

            async def side_effect(owner, repo_name):
                full = f"{owner}/{repo_name}"
                if full in original_repos:
                    return original_repos[full]
                raise GitHubAPIError("Not found", 404)

            instance.get_repo_details = AsyncMock(side_effect=side_effect)

            resp = await api_client.post(
                "/api/v1/github/refresh-all",
                json={"product_id": str(test_product.id)},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["refreshed"]) >= 1
        assert len(data["failed"]) >= 1
