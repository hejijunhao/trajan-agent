"""
GitHub API helper utilities.

Provides rate limit handling and error response processing for GitHub API calls.
Extracted from service.py to reduce duplication and improve maintainability.
"""

import httpx

from app.services.github.exceptions import GitHubAPIError


class RateLimitInfo:
    """Rate limit information from GitHub API response."""

    def __init__(self, response: httpx.Response) -> None:
        self.remaining = response.headers.get("X-RateLimit-Remaining")
        self.reset = response.headers.get("X-RateLimit-Reset")

    @property
    def reset_timestamp(self) -> int | None:
        """Get reset timestamp as integer, or None if not available."""
        return int(self.reset) if self.reset else None

    @property
    def is_exhausted(self) -> bool:
        """Check if rate limit is exhausted."""
        return self.remaining is not None and int(self.remaining) == 0


def handle_error_response(response: httpx.Response, repo_name: str) -> None:
    """
    Handle common error responses from GitHub API.

    Args:
        response: The HTTP response from GitHub API
        repo_name: Repository name for error context

    Raises:
        GitHubAPIError: For authentication, authorization, or other API errors
    """
    rate_info = RateLimitInfo(response)

    if response.status_code == 401:
        raise GitHubAPIError("Invalid or expired GitHub token", 401)
    elif response.status_code == 404:
        raise GitHubAPIError(f"Repository or resource not found: {repo_name}", 404)
    elif response.status_code == 403:
        if rate_info.is_exhausted:
            raise GitHubAPIError(
                "GitHub API rate limit exceeded",
                403,
                rate_limit_reset=rate_info.reset_timestamp,
            )
        raise GitHubAPIError("GitHub API forbidden", 403)
    elif response.status_code != 200:
        raise GitHubAPIError(
            f"GitHub API error: {response.status_code}", response.status_code
        )


def handle_rate_limit_error(
    response: httpx.Response,
    error_message: str,
) -> None:
    """
    Handle 403 responses with rate limit check.

    Args:
        response: The HTTP response from GitHub API
        error_message: Custom error message for non-rate-limit 403s

    Raises:
        GitHubAPIError: With appropriate message based on rate limit status
    """
    rate_info = RateLimitInfo(response)

    if rate_info.is_exhausted:
        raise GitHubAPIError(
            "GitHub API rate limit exceeded",
            403,
            rate_limit_reset=rate_info.reset_timestamp,
        )
    raise GitHubAPIError(error_message, 403)
