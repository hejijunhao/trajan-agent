"""Unit tests for GitHub service — read and write operations.

Tests GitHubService with mocked HTTP responses to verify:
- Request construction (URLs, headers, params)
- Response parsing and normalization
- Error handling (401, 403, 404, rate limits)
- Caching behavior
- Timeout handling
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.github.cache import clear_all_caches
from app.services.github.exceptions import GitHubAPIError, GitHubRepoRenamed
from app.services.github.service import GitHubService, calculate_lines_of_code
from app.services.github.types import (
    CommitStats,
    ContributorInfo,
    GitHubRepo,
    LanguageStat,
    RepoFile,
    RepoTree,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TOKEN = "ghp_test_token_12345"


def _make_response(
    status_code: int = 200,
    json_data: object = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Build a fake httpx.Response with the given status, JSON body, and headers."""
    resp = httpx.Response(
        status_code=status_code,
        json=json_data,
        headers=headers or {},
    )
    return resp


def _repo_json(
    github_id: int = 12345,
    name: str = "my-repo",
    full_name: str = "owner/my-repo",
    **overrides: object,
) -> dict:
    """Minimal GitHub repo API payload."""
    base = {
        "id": github_id,
        "name": name,
        "full_name": full_name,
        "description": "A test repo",
        "html_url": f"https://github.com/{full_name}",
        "default_branch": "main",
        "private": False,
        "language": "Python",
        "stargazers_count": 42,
        "forks_count": 5,
        "updated_at": "2026-01-15T00:00:00Z",
        "created_at": "2025-06-01T00:00:00Z",
        "pushed_at": "2026-01-14T00:00:00Z",
        "open_issues_count": 3,
        "license": {"spdx_id": "MIT"},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_caches():
    """Clear GitHub TTL caches before each test to prevent cross-test pollution."""
    clear_all_caches()
    yield
    clear_all_caches()


# ═══════════════════════════════════════════════════════════════════════════
# calculate_lines_of_code
# ═══════════════════════════════════════════════════════════════════════════


class TestCalculateLinesOfCode:
    """Tests for the module-level LOC utility."""

    def test_empty_dict_returns_zero(self):
        assert calculate_lines_of_code({}) == 0

    def test_single_file(self):
        assert calculate_lines_of_code({"main.py": "line1\nline2\nline3"}) == 3

    def test_multiple_files(self):
        files = {"a.py": "x\ny", "b.py": "z"}
        assert calculate_lines_of_code(files) == 3


# ═══════════════════════════════════════════════════════════════════════════
# get_user_repos
# ═══════════════════════════════════════════════════════════════════════════


class TestGetUserRepos:
    """Tests for listing authenticated user's repositories."""

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_returns_repos_list(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(
            json_data=[_repo_json()],
            headers={"X-RateLimit-Remaining": "59"},
        )

        svc = GitHubService(TOKEN)
        result = await svc.get_user_repos()

        assert len(result.repos) == 1
        assert result.repos[0].name == "my-repo"
        assert result.repos[0].github_id == 12345
        assert result.rate_limit_remaining == 59
        assert result.has_more is False

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_detects_pagination_via_link_header(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(
            json_data=[_repo_json()],
            headers={
                "Link": '<https://api.github.com/user/repos?page=2>; rel="next"',
                "X-RateLimit-Remaining": "58",
            },
        )

        svc = GitHubService(TOKEN)
        result = await svc.get_user_repos()

        assert result.has_more is True

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_caps_per_page_at_100(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(json_data=[])

        svc = GitHubService(TOKEN)
        await svc.get_user_repos(per_page=200)

        call_kwargs = client.get.call_args
        assert call_kwargs.kwargs["params"]["per_page"] == 100

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_raises_on_401(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(status_code=401)

        svc = GitHubService(TOKEN)
        with pytest.raises(GitHubAPIError, match="Invalid or expired"):
            await svc.get_user_repos()

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_raises_on_rate_limit(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(
            status_code=403,
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"},
        )

        svc = GitHubService(TOKEN)
        with pytest.raises(GitHubAPIError, match="rate limit") as exc_info:
            await svc.get_user_repos()

        assert exc_info.value.rate_limit_reset == 1700000000


# ═══════════════════════════════════════════════════════════════════════════
# get_repo_details
# ═══════════════════════════════════════════════════════════════════════════


class TestGetRepoDetails:
    """Tests for fetching individual repository details."""

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_returns_normalized_repo(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(json_data=_repo_json())

        svc = GitHubService(TOKEN)
        repo = await svc.get_repo_details("owner", "my-repo")

        assert isinstance(repo, GitHubRepo)
        assert repo.full_name == "owner/my-repo"
        assert repo.license_name == "MIT"
        assert repo.stars_count == 42

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_raises_on_404(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(status_code=404)

        svc = GitHubService(TOKEN)
        with pytest.raises(GitHubAPIError, match="not found"):
            await svc.get_repo_details("owner", "missing-repo")

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_raises_on_403_forbidden(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(
            status_code=403,
            headers={"X-RateLimit-Remaining": "50"},
        )

        svc = GitHubService(TOKEN)
        with pytest.raises(GitHubAPIError, match="forbidden"):
            await svc.get_repo_details("owner", "private-repo")


# ═══════════════════════════════════════════════════════════════════════════
# get_repo_tree
# ═══════════════════════════════════════════════════════════════════════════


class TestGetRepoTree:
    """Tests for fetching repository file trees."""

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_parses_tree_items(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(
            json_data={
                "sha": "abc123",
                "tree": [
                    {"path": "src/main.py", "type": "blob", "size": 1024, "sha": "f1"},
                    {"path": "src", "type": "tree", "size": None, "sha": "d1"},
                ],
                "truncated": False,
            }
        )

        svc = GitHubService(TOKEN)
        tree = await svc.get_repo_tree("owner", "repo")

        assert isinstance(tree, RepoTree)
        assert tree.files == ["src/main.py"]
        assert tree.directories == ["src"]
        assert tree.truncated is False
        assert len(tree.all_items) == 2

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_reports_truncated_tree(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(
            json_data={"sha": "abc", "tree": [], "truncated": True}
        )

        svc = GitHubService(TOKEN)
        tree = await svc.get_repo_tree("owner", "repo")

        assert tree.truncated is True


# ═══════════════════════════════════════════════════════════════════════════
# get_file_content
# ═══════════════════════════════════════════════════════════════════════════


class TestGetFileContent:
    """Tests for fetching individual file contents."""

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_decodes_base64_content(self, mock_get_client):
        import base64

        content = "print('hello')"
        encoded = base64.b64encode(content.encode()).decode()

        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(
            json_data={
                "type": "file",
                "size": len(content),
                "content": encoded,
                "sha": "filesha",
                "encoding": "base64",
            }
        )

        svc = GitHubService(TOKEN)
        result = await svc.get_file_content("owner", "repo", "main.py")

        assert isinstance(result, RepoFile)
        assert result.content == content
        assert result.path == "main.py"

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_returns_none_for_404(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(status_code=404)

        svc = GitHubService(TOKEN)
        result = await svc.get_file_content("owner", "repo", "missing.txt")

        assert result is None

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_returns_none_for_oversized_file(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(
            json_data={"type": "file", "size": 500_000, "content": "", "sha": "x"}
        )

        svc = GitHubService(TOKEN)
        result = await svc.get_file_content("owner", "repo", "big.bin", max_size=100)

        assert result is None

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_returns_none_for_directory(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(
            json_data={"type": "dir", "size": 0}
        )

        svc = GitHubService(TOKEN)
        result = await svc.get_file_content("owner", "repo", "src/")

        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# get_repo_languages
# ═══════════════════════════════════════════════════════════════════════════


class TestGetRepoLanguages:
    """Tests for fetching language breakdown."""

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_calculates_percentages(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(
            json_data={"Python": 7000, "JavaScript": 3000}
        )

        svc = GitHubService(TOKEN)
        langs = await svc.get_repo_languages("owner", "repo")

        assert len(langs) == 2
        assert isinstance(langs[0], LanguageStat)
        # Sorted descending by percentage
        assert langs[0].name == "Python"
        assert langs[0].percentage == 70.0
        assert langs[1].percentage == 30.0

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_empty_repo_returns_empty_list(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(json_data={})

        svc = GitHubService(TOKEN)
        langs = await svc.get_repo_languages("owner", "repo")

        assert langs == []


# ═══════════════════════════════════════════════════════════════════════════
# get_repo_contributors
# ═══════════════════════════════════════════════════════════════════════════


class TestGetRepoContributors:
    """Tests for fetching contributor lists."""

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_returns_contributor_list(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(
            json_data=[
                {"login": "alice", "avatar_url": "https://avatar/alice", "contributions": 100},
                {"login": "bob", "avatar_url": None, "contributions": 50},
            ]
        )

        svc = GitHubService(TOKEN)
        contribs = await svc.get_repo_contributors("owner", "repo")

        assert len(contribs) == 2
        assert isinstance(contribs[0], ContributorInfo)
        assert contribs[0].login == "alice"
        assert contribs[0].contributions == 100

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_handles_204_empty_repo(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(status_code=204)

        svc = GitHubService(TOKEN)
        contribs = await svc.get_repo_contributors("owner", "repo")

        assert contribs == []


# ═══════════════════════════════════════════════════════════════════════════
# get_commit_stats
# ═══════════════════════════════════════════════════════════════════════════


class TestGetCommitStats:
    """Tests for commit statistics."""

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_single_commit_repo(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(
            json_data=[{"commit": {"committer": {"date": "2026-01-15T00:00:00Z"}}}],
            headers={},  # No Link header → single page → 1 commit
        )

        svc = GitHubService(TOKEN)
        stats = await svc.get_commit_stats("owner", "repo")

        assert isinstance(stats, CommitStats)
        assert stats.total_commits == 1
        assert stats.last_commit_date == "2026-01-15T00:00:00Z"
        assert stats.first_commit_date == stats.last_commit_date

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_empty_repo_returns_zero_commits(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(json_data=[])

        svc = GitHubService(TOKEN)
        stats = await svc.get_commit_stats("owner", "repo")

        assert stats.total_commits == 0
        assert stats.first_commit_date is None

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_non_200_returns_zero(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(status_code=409)

        svc = GitHubService(TOKEN)
        stats = await svc.get_commit_stats("owner", "repo")

        assert stats.total_commits == 0


# ═══════════════════════════════════════════════════════════════════════════
# get_commit_detail
# ═══════════════════════════════════════════════════════════════════════════


class TestGetCommitDetail:
    """Tests for fetching single commit stats."""

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_returns_stats(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(
            json_data={
                "stats": {"additions": 10, "deletions": 3},
                "files": [{"filename": "a.py"}, {"filename": "b.py"}],
            }
        )

        svc = GitHubService(TOKEN)
        result = await svc.get_commit_detail("owner", "repo", "abc123")

        assert result == {"additions": 10, "deletions": 3, "files_changed": 2}

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_returns_none_on_timeout(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.side_effect = httpx.TimeoutException("timed out")

        svc = GitHubService(TOKEN)
        result = await svc.get_commit_detail("owner", "repo", "abc123")

        assert result is None

    @patch("app.services.github.read_operations.get_github_client")
    @pytest.mark.anyio
    async def test_returns_none_on_non_200(self, mock_get_client):
        client = AsyncMock()
        mock_get_client.return_value = client
        client.get.return_value = _make_response(status_code=404)

        svc = GitHubService(TOKEN)
        result = await svc.get_commit_detail("owner", "repo", "bad_sha")

        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# get_repo_context (integration of multiple reads)
# ═══════════════════════════════════════════════════════════════════════════


class TestGetRepoContext:
    """Tests for the aggregated repo context fetcher."""

    @pytest.mark.anyio
    async def test_collects_errors_gracefully(self):
        """If sub-calls fail, errors are collected rather than raised."""
        svc = GitHubService(TOKEN)

        # Patch individual methods to simulate partial failures
        with (
            patch.object(svc, "get_repo_details", new_callable=AsyncMock) as mock_details,
            patch.object(svc, "get_repo_tree", new_callable=AsyncMock) as mock_tree,
            patch.object(svc, "get_key_files", new_callable=AsyncMock) as mock_files,
            patch.object(svc, "get_repo_languages", new_callable=AsyncMock) as mock_langs,
            patch.object(svc, "get_repo_contributors", new_callable=AsyncMock) as mock_contribs,
            patch.object(svc, "get_commit_stats", new_callable=AsyncMock) as mock_stats,
        ):
            mock_details.return_value = GitHubRepo(
                github_id=1, name="r", full_name="o/r", description=None,
                url="https://github.com/o/r", default_branch="main",
                is_private=False, language=None, stars_count=0, forks_count=0,
                updated_at="",
            )
            mock_tree.side_effect = GitHubAPIError("tree fail", 500)
            mock_files.return_value = {}
            mock_langs.side_effect = GitHubAPIError("langs fail", 500)
            mock_contribs.return_value = []
            mock_stats.return_value = CommitStats(0, None, None)

            ctx = await svc.get_repo_context("o", "r")

        assert ctx.owner == "o"
        assert ctx.repo == "r"
        assert any("tree fail" in e for e in ctx.errors)
        assert any("langs fail" in e for e in ctx.errors)

    @pytest.mark.anyio
    async def test_uses_provided_branch(self):
        """When branch is provided, skips fetching repo details for branch."""
        svc = GitHubService(TOKEN)

        with (
            patch.object(svc, "get_repo_details", new_callable=AsyncMock) as mock_details,
            patch.object(svc, "get_repo_tree", new_callable=AsyncMock) as mock_tree,
            patch.object(svc, "get_key_files", new_callable=AsyncMock) as mock_files,
            patch.object(svc, "get_repo_languages", new_callable=AsyncMock) as mock_langs,
            patch.object(svc, "get_repo_contributors", new_callable=AsyncMock) as mock_contribs,
            patch.object(svc, "get_commit_stats", new_callable=AsyncMock) as mock_stats,
        ):
            mock_details.return_value = GitHubRepo(
                github_id=1, name="r", full_name="o/r", description=None,
                url="https://github.com/o/r", default_branch="develop",
                is_private=False, language=None, stars_count=0, forks_count=0,
                updated_at="",
            )
            mock_tree.return_value = RepoTree(
                sha="x", files=[], directories=[], all_items=[], truncated=False,
            )
            mock_files.return_value = {}
            mock_langs.return_value = []
            mock_contribs.return_value = []
            mock_stats.return_value = CommitStats(0, None, None)

            ctx = await svc.get_repo_context("o", "r", branch="custom-branch")

        assert ctx.default_branch == "custom-branch"
        # Tree should have been called with the custom branch
        mock_tree.assert_called_once_with("o", "r", "custom-branch")
