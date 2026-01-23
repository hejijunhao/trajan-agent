"""
GitHub API helper utilities.

Provides rate limit handling and error response processing for GitHub API calls.
Extracted from service.py to reduce duplication and improve maintainability.
"""

import logging
import re

import httpx

from app.services.github.exceptions import GitHubAPIError, GitHubRepoRenamed

logger = logging.getLogger(__name__)


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


def parse_redirect_location(location: str) -> tuple[str, str] | None:
    """
    Extract owner/repo from GitHub redirect Location header.

    When a repository is renamed or transferred, GitHub returns a 301 with a
    Location header pointing to the new URL.

    Args:
        location: The Location header value, which can be:
            - Absolute: "https://api.github.com/repos/owner/newname/..."
            - Relative: "/repos/owner/newname/..."

    Returns:
        Tuple of (owner, repo) if parseable, None otherwise
    """
    if not location:
        return None

    # Try absolute URL format: https://api.github.com/repos/{owner}/{repo}/...
    match = re.match(r"https://api\.github\.com/repos/([^/]+)/([^/]+)", location)
    if match:
        return (match.group(1), match.group(2))

    # Try relative URL format: /repos/{owner}/{repo}/...
    match = re.match(r"/repos/([^/]+)/([^/]+)", location)
    if match:
        return (match.group(1), match.group(2))

    return None


def parse_redirect_repo_id(location: str) -> int | None:
    """
    Extract repository ID from GitHub redirect Location header.

    GitHub sometimes redirects to a repository ID-based URL instead of owner/repo:
    https://api.github.com/repositories/1133274306/git/trees/main

    Args:
        location: The Location header value

    Returns:
        Repository ID as integer if parseable, None otherwise
    """
    if not location:
        return None

    # Try: https://api.github.com/repositories/{id}/...
    match = re.match(r"https://api\.github\.com/repositories/(\d+)", location)
    if match:
        return int(match.group(1))

    # Try relative: /repositories/{id}/...
    match = re.match(r"/repositories/(\d+)", location)
    if match:
        return int(match.group(1))

    return None


def handle_error_response(response: httpx.Response, repo_name: str) -> None:
    """
    Handle common error responses from GitHub API.

    Args:
        response: The HTTP response from GitHub API
        repo_name: Repository name for error context (format: "owner/repo")

    Raises:
        GitHubRepoRenamed: If repository was renamed/transferred (301)
        GitHubAPIError: For authentication, authorization, or other API errors
    """
    rate_info = RateLimitInfo(response)

    if response.status_code == 301:
        # Repository was renamed or transferred
        location = response.headers.get("Location", "")
        logger.debug(f"Got 301 redirect for {repo_name}, Location header: {location!r}")

        # Try to parse owner/repo format first
        new_repo = parse_redirect_location(location)
        if new_repo:
            new_full_name = f"{new_repo[0]}/{new_repo[1]}"
            logger.info(f"Repository redirect detected: {repo_name} → {new_full_name}")
            raise GitHubRepoRenamed(repo_name, new_full_name)

        # Try to parse repository ID format (GitHub sometimes uses /repositories/{id}/...)
        repo_id = parse_redirect_repo_id(location)
        if repo_id:
            logger.info(f"Repository redirect to ID detected: {repo_name} → ID {repo_id}")
            raise GitHubRepoRenamed(repo_name, new_full_name=None, repo_id=repo_id)

        # Fallback: try to extract from response body (GitHub sometimes includes url field)
        try:
            body = response.json()
            if "url" in body:
                url_match = parse_redirect_location(body["url"])
                if url_match:
                    new_full_name = f"{url_match[0]}/{url_match[1]}"
                    logger.info(f"Repository redirect from body: {repo_name} → {new_full_name}")
                    raise GitHubRepoRenamed(repo_name, new_full_name)
        except Exception:
            pass  # JSON parsing failed, continue to fallback

        # Log the actual Location header for debugging
        logger.warning(
            f"Repository {repo_name} returned 301 but Location header couldn't be parsed. "
            f"Location: {location!r}"
        )
        raise GitHubAPIError(
            f"Repository {repo_name} was moved (301), but couldn't parse new location",
            301,
        )
    elif response.status_code == 401:
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
