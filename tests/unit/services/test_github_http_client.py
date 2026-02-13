"""Unit tests for GitHub HTTP client and helpers.

Tests the shared HTTP client singleton, rate limit parsing,
redirect handling, and error response processing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.github.cache import (
    clear_all_caches,
    get_cache_stats,
)
from app.services.github.exceptions import GitHubAPIError, GitHubRepoRenamed
from app.services.github.helpers import (
    RateLimitInfo,
    handle_error_response,
    handle_rate_limit_error,
    parse_redirect_location,
    parse_redirect_repo_id,
)
from app.services.github.http_client import close_github_client, get_github_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(
    status_code: int = 200,
    json_data: object = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Build a fake httpx.Response."""
    return httpx.Response(
        status_code=status_code,
        json=json_data,
        headers=headers or {},
    )


# ═══════════════════════════════════════════════════════════════════════════
# RateLimitInfo
# ═══════════════════════════════════════════════════════════════════════════


class TestRateLimitInfo:
    """Tests for rate limit header parsing."""

    def test_extracts_remaining_and_reset(self):
        resp = _make_response(
            headers={
                "X-RateLimit-Remaining": "42",
                "X-RateLimit-Reset": "1700000000",
            }
        )
        info = RateLimitInfo(resp)

        assert info.remaining == "42"
        assert info.reset_timestamp == 1700000000
        assert info.is_exhausted is False

    def test_detects_exhausted(self):
        resp = _make_response(
            headers={
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": "1700000000",
            }
        )
        info = RateLimitInfo(resp)

        assert info.is_exhausted is True

    def test_missing_headers(self):
        resp = _make_response(headers={})
        info = RateLimitInfo(resp)

        assert info.remaining is None
        assert info.reset_timestamp is None
        assert info.is_exhausted is False


# ═══════════════════════════════════════════════════════════════════════════
# parse_redirect_location
# ═══════════════════════════════════════════════════════════════════════════


class TestParseRedirectLocation:
    """Tests for extracting owner/repo from GitHub redirect URLs."""

    def test_absolute_url(self):
        result = parse_redirect_location(
            "https://api.github.com/repos/newowner/newrepo/git/trees/main"
        )
        assert result == ("newowner", "newrepo")

    def test_relative_url(self):
        result = parse_redirect_location("/repos/org/project/contents/README.md")
        assert result == ("org", "project")

    def test_empty_string_returns_none(self):
        assert parse_redirect_location("") is None

    def test_unrecognized_format_returns_none(self):
        assert parse_redirect_location("https://example.com/something") is None


# ═══════════════════════════════════════════════════════════════════════════
# parse_redirect_repo_id
# ═══════════════════════════════════════════════════════════════════════════


class TestParseRedirectRepoId:
    """Tests for extracting repository ID from redirect URLs."""

    def test_absolute_repositories_url(self):
        result = parse_redirect_repo_id(
            "https://api.github.com/repositories/1133274306/git/trees/main"
        )
        assert result == 1133274306

    def test_relative_repositories_url(self):
        result = parse_redirect_repo_id("/repositories/99999")
        assert result == 99999

    def test_empty_returns_none(self):
        assert parse_redirect_repo_id("") is None

    def test_non_numeric_returns_none(self):
        assert parse_redirect_repo_id("https://api.github.com/repositories/abc") is None


# ═══════════════════════════════════════════════════════════════════════════
# handle_error_response
# ═══════════════════════════════════════════════════════════════════════════


class TestHandleErrorResponse:
    """Tests for centralized GitHub API error handling."""

    def test_200_does_nothing(self):
        resp = _make_response(status_code=200)
        handle_error_response(resp, "owner/repo")  # should not raise

    def test_401_raises_auth_error(self):
        resp = _make_response(status_code=401)
        with pytest.raises(GitHubAPIError, match="Invalid or expired"):
            handle_error_response(resp, "owner/repo")

    def test_404_raises_not_found(self):
        resp = _make_response(status_code=404)
        with pytest.raises(GitHubAPIError, match="not found"):
            handle_error_response(resp, "owner/repo")

    def test_403_with_rate_limit_exhausted(self):
        resp = _make_response(
            status_code=403,
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"},
        )
        with pytest.raises(GitHubAPIError, match="rate limit") as exc_info:
            handle_error_response(resp, "owner/repo")

        assert exc_info.value.rate_limit_reset == 1700000000

    def test_403_without_rate_limit_raises_forbidden(self):
        resp = _make_response(
            status_code=403,
            headers={"X-RateLimit-Remaining": "50"},
        )
        with pytest.raises(GitHubAPIError, match="forbidden"):
            handle_error_response(resp, "owner/repo")

    def test_301_with_owner_repo_redirect(self):
        resp = _make_response(
            status_code=301,
            headers={"Location": "https://api.github.com/repos/new-owner/new-repo/stuff"},
        )
        with pytest.raises(GitHubRepoRenamed) as exc_info:
            handle_error_response(resp, "old-owner/old-repo")

        assert exc_info.value.new_full_name == "new-owner/new-repo"

    def test_301_with_repo_id_redirect(self):
        resp = _make_response(
            status_code=301,
            headers={"Location": "https://api.github.com/repositories/12345/git/trees/main"},
        )
        with pytest.raises(GitHubRepoRenamed) as exc_info:
            handle_error_response(resp, "old/repo")

        assert exc_info.value.repo_id == 12345

    def test_301_unparseable_falls_back_to_api_error(self):
        resp = _make_response(
            status_code=301,
            headers={"Location": "https://completely-unknown.example.com/x"},
        )
        with pytest.raises(GitHubAPIError, match="moved.*couldn't parse"):
            handle_error_response(resp, "owner/repo")

    def test_500_raises_generic_error(self):
        resp = _make_response(status_code=500)
        with pytest.raises(GitHubAPIError, match="500"):
            handle_error_response(resp, "owner/repo")


# ═══════════════════════════════════════════════════════════════════════════
# handle_rate_limit_error
# ═══════════════════════════════════════════════════════════════════════════


class TestHandleRateLimitError:
    """Tests for the dedicated rate limit error handler."""

    def test_exhausted_raises_rate_limit(self):
        resp = _make_response(
            status_code=403,
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"},
        )
        with pytest.raises(GitHubAPIError, match="rate limit"):
            handle_rate_limit_error(resp, "Custom error")

    def test_not_exhausted_raises_custom_message(self):
        resp = _make_response(
            status_code=403,
            headers={"X-RateLimit-Remaining": "10"},
        )
        with pytest.raises(GitHubAPIError, match="Custom error"):
            handle_rate_limit_error(resp, "Custom error")


# ═══════════════════════════════════════════════════════════════════════════
# HTTP Client Singleton
# ═══════════════════════════════════════════════════════════════════════════


class TestGitHubHttpClient:
    """Tests for the shared HTTP client singleton."""

    def test_client_returns_async_client(self):
        """get_github_client returns an httpx.AsyncClient instance."""
        # Reset the module-level singleton
        import app.services.github.http_client as mod

        original = mod._client
        mod._client = None

        try:
            client = get_github_client()
            assert isinstance(client, httpx.AsyncClient)
            assert client.timeout.connect == 5.0
            assert client.timeout.pool == 30.0
        finally:
            # Clean up: close the client we created and restore
            if mod._client and not mod._client.is_closed:
                import asyncio

                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        pass  # Can't close in running loop, will be cleaned up
                except RuntimeError:
                    pass
            mod._client = original

    def test_returns_same_instance(self):
        """Repeated calls return the same singleton client."""
        import app.services.github.http_client as mod

        original = mod._client
        mod._client = None

        try:
            a = get_github_client()
            b = get_github_client()
            assert a is b
        finally:
            mod._client = original


# ═══════════════════════════════════════════════════════════════════════════
# Cache utilities
# ═══════════════════════════════════════════════════════════════════════════


class TestCacheUtilities:
    """Tests for cache management functions."""

    def test_clear_all_caches(self):
        from app.services.github.cache import tree_cache

        tree_cache["test_key"] = "test_value"
        assert len(tree_cache) == 1

        clear_all_caches()
        assert len(tree_cache) == 0

    def test_get_cache_stats_returns_sizes(self):
        clear_all_caches()
        stats = get_cache_stats()

        assert "tree" in stats
        assert "languages" in stats
        assert "contributors" in stats
        assert "repo_details" in stats
        assert stats["tree"]["size"] == 0
        assert stats["tree"]["maxsize"] == 100
