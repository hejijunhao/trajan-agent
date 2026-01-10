"""Exceptions for GitHub service."""


class GitHubAPIError(Exception):
    """Error from GitHub API."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        rate_limit_reset: int | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.rate_limit_reset = rate_limit_reset  # Unix timestamp when rate limit resets
        super().__init__(message)
