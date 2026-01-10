"""
GitHub service package.

Re-exports all public types and classes for backwards compatibility.
Usage: `from app.services.github import GitHubService, RepoContext`
"""

from app.services.github.constants import GITHUB_LANGUAGE_COLORS, KEY_FILES
from app.services.github.exceptions import GitHubAPIError
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

__all__ = [
    # Service
    "GitHubService",
    # Utilities
    "calculate_lines_of_code",
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
