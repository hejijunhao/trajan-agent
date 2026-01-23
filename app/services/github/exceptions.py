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


class GitHubRepoRenamed(GitHubAPIError):
    """Repository has been renamed or transferred on GitHub.

    When GitHub returns a 301 redirect, this exception provides the old and new
    repository names so callers can update their records and retry.

    In some cases, GitHub redirects to a repository ID-based URL instead of
    providing the new owner/repo directly. When this happens, new_full_name
    will be None and repo_id will contain the GitHub repository ID that can
    be used to fetch the current name.
    """

    def __init__(
        self,
        old_full_name: str,
        new_full_name: str | None = None,
        repo_id: int | None = None,
    ):
        self.old_full_name = old_full_name
        self.new_full_name = new_full_name
        self.repo_id = repo_id

        if new_full_name:
            message = f"Repository renamed: {old_full_name} → {new_full_name}"
        elif repo_id:
            message = f"Repository {old_full_name} moved (GitHub ID: {repo_id})"
        else:
            message = f"Repository {old_full_name} was moved"

        super().__init__(message, status_code=301)
