"""Lightweight activity checker for auto-progress smart-skip logic.

Checks if a product has new commits without fetching full commit data.
Uses GitHub's per_page=1 trick to minimize API usage.
"""

import logging
from datetime import datetime

from app.models.repository import Repository
from app.services.github import GitHubReadOperations

logger = logging.getLogger(__name__)


class ActivityChecker:
    """Check for new commit activity across a product's repositories."""

    async def get_latest_commit_date(
        self,
        repos: list[Repository],
        github: GitHubReadOperations,
    ) -> datetime | None:
        """
        Get the most recent commit timestamp across all repos.

        Uses GET /repos/{owner}/{repo}/commits?per_page=1 for minimal API usage.
        Returns the latest committer date across all repos, or None if no commits.
        """
        latest: datetime | None = None

        for repo in repos:
            if not repo.full_name:
                continue

            try:
                owner, name = repo.full_name.split("/")
                commits, _ = await github.get_commits_for_timeline(
                    owner, name, repo.default_branch, per_page=1
                )

                if not commits:
                    continue

                # Parse the committer date from the most recent commit
                timestamp_str = commits[0]["commit"]["committer"]["date"]
                commit_dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))

                if latest is None or commit_dt > latest:
                    latest = commit_dt

            except Exception as e:
                logger.warning(f"Activity check failed for {repo.full_name}: {e}")
                continue

        return latest


activity_checker = ActivityChecker()
