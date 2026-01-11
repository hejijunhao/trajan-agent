"""
GitHub service package.

Re-exports all public types and classes for backwards compatibility.
Usage: `from app.services.github import GitHubService, RepoContext`

Module structure:
- service.py: Main GitHubService facade
- read_operations.py: All read-only API operations
- write_operations.py: All write/mutation API operations
- helpers.py: Rate limit handling and error utilities
- types.py: Data types and response models
- exceptions.py: Custom exceptions
- constants.py: API constants and configuration
"""

from app.services.github.constants import GITHUB_LANGUAGE_COLORS, KEY_FILES
from app.services.github.exceptions import GitHubAPIError
from app.services.github.helpers import RateLimitInfo, handle_error_response
from app.services.github.read_operations import GitHubReadOperations
from app.services.github.service import GitHubService, calculate_lines_of_code
from app.services.github.types import (
    CommitStats,
    ContributorInfo,
    GitHubRepo,
    GitHubReposResponse,
    LanguageStat,
    RepoContext,
    RepoFile,
    RepoTree,
    RepoTreeItem,
)
from app.services.github.write_operations import GitHubWriteOperations

__all__ = [
    # Service (main entry point)
    "GitHubService",
    # Operation classes (for direct use if needed)
    "GitHubReadOperations",
    "GitHubWriteOperations",
    # Utilities
    "calculate_lines_of_code",
    "handle_error_response",
    "RateLimitInfo",
    # Exceptions
    "GitHubAPIError",
    # Types
    "CommitStats",
    "ContributorInfo",
    "GitHubRepo",
    "GitHubReposResponse",
    "LanguageStat",
    "RepoContext",
    "RepoFile",
    "RepoTree",
    "RepoTreeItem",
    # Constants
    "GITHUB_LANGUAGE_COLORS",
    "KEY_FILES",
]
