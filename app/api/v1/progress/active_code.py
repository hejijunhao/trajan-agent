"""Progress API: Active Code endpoint."""

import asyncio
import logging
import uuid as uuid_pkg
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    ProductAccessContext,
    get_current_user,
    get_db_with_rls,
    get_product_access,
)
from app.domain import repository_ops
from app.models import User
from app.models.repository import Repository
from app.services.github import GitHubReadOperations
from app.services.github.exceptions import GitHubRepoRenamed

from .commit_fetcher import MAX_CONCURRENT_STAT_FETCHES
from .utils import get_period_start, handle_repo_rename, resolve_github_token

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/products/{product_id}/active-code")
async def get_active_code(
    product_id: uuid_pkg.UUID,
    period: str = Query("7d", description="Time period: 24h, 48h, 7d, 14d, 30d, 90d, 365d"),
    repo_ids: str | None = Query(None, description="Comma-separated repository IDs to filter"),
    _access_ctx: ProductAccessContext = Depends(get_product_access),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    """Get active code visualization data for a product.

    Returns file and directory activity including:
    - Hottest files (top 15 by commit count)
    - Directory tree with aggregated stats
    - Quiet areas (directories with no recent changes)
    - Total unique files changed
    """
    # Get GitHub-linked repositories
    repos = await repository_ops.get_github_repos_by_product(db, product_id=product_id)
    if not repos:
        return _empty_active_code_response()

    # Filter repositories if repo_ids provided
    if repo_ids:
        filter_ids = set(repo_ids.split(","))
        repos = [r for r in repos if str(r.id) in filter_ids]
        if not repos:
            return _empty_active_code_response()

    # Resolve GitHub token
    github_token = await resolve_github_token(db, current_user, product_id)
    if not github_token:
        return _empty_active_code_response()

    # Calculate period bounds
    period_start = get_period_start(period)
    since_str = period_start.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Fetch commits from all repos in parallel
    github = GitHubReadOperations(github_token)
    fetch_limit = 200

    async def fetch_repo_commits(
        repo: Repository,
    ) -> list[tuple[Repository, dict[str, Any]]]:
        if not repo.full_name:
            return []
        owner, name = repo.full_name.split("/")
        commits, _ = await github.get_commits_for_timeline(
            owner, name, repo.default_branch, per_page=fetch_limit
        )
        return [(repo, c) for c in commits]

    results = await asyncio.gather(
        *[fetch_repo_commits(r) for r in repos],
        return_exceptions=True,
    )

    # Handle renames and flatten, filter by date
    commits_in_period: list[tuple[Repository, dict[str, Any]]] = []
    repos_to_retry: list[Repository] = []

    for i, result in enumerate(results):
        if isinstance(result, GitHubRepoRenamed):
            repo = repos[i]
            updated_repo = await handle_repo_rename(db, github, repo, result)
            if updated_repo:
                repos_to_retry.append(updated_repo)
        elif isinstance(result, BaseException):
            logger.warning(f"Failed to fetch commits for repo: {result}")
            continue
        else:
            for repo, commit in result:
                timestamp = commit["commit"]["committer"]["date"]
                if timestamp >= since_str:
                    commits_in_period.append((repo, commit))

    # Retry renamed repos
    if repos_to_retry:
        retry_results = await asyncio.gather(
            *[fetch_repo_commits(r) for r in repos_to_retry],
            return_exceptions=True,
        )
        for result in retry_results:
            if isinstance(result, BaseException):
                logger.warning(f"Retry failed for renamed repo: {result}")
                continue
            for repo, commit in result:
                timestamp = commit["commit"]["committer"]["date"]
                if timestamp >= since_str:
                    commits_in_period.append((repo, commit))

    if not commits_in_period:
        return _empty_active_code_response()

    # Fetch file details for each commit
    file_activity = await _fetch_file_activity(github, repos, commits_in_period)

    # Compute active code data
    return _compute_active_code(file_activity)


async def _fetch_file_activity(
    github: GitHubReadOperations,
    repos: list[Repository],
    commits: list[tuple[Repository, dict[str, Any]]],
) -> dict[str, dict[str, int]]:
    """Fetch file changes for commits and aggregate by file path."""
    # Build repo map
    repo_map: dict[str, tuple[str, str]] = {}
    for repo in repos:
        if repo.full_name:
            owner_name, repo_name = repo.full_name.split("/")
            repo_map[repo.full_name] = (owner_name, repo_name)

    # Track file activity: path -> {commits, additions, deletions}
    file_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"commits": 0, "additions": 0, "deletions": 0}
    )

    # Fetch file changes with concurrency limit
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_STAT_FETCHES)

    async def fetch_commit_files(
        repo: Repository, commit: dict[str, Any]
    ) -> list[dict[str, Any]] | None:
        if not repo.full_name:
            return None
        repo_info = repo_map.get(repo.full_name)
        if not repo_info:
            return None
        owner_name, repo_name = repo_info
        sha = commit["sha"]

        async with semaphore:
            return await github.get_commit_files(owner_name, repo_name, sha)

    # Fetch all commit files in parallel
    tasks = [fetch_commit_files(repo, commit) for repo, commit in commits]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Aggregate file activity
    for i, result in enumerate(results):
        if isinstance(result, BaseException) or result is None:
            continue

        repo, _ = commits[i]
        repo_prefix = repo.name + "/" if repo.name else ""

        for file_change in result:
            # Prefix file path with repo name for multi-repo products
            file_path = repo_prefix + file_change.get("filename", "")
            if not file_path:
                continue

            file_stats[file_path]["commits"] += 1
            file_stats[file_path]["additions"] += file_change.get("additions", 0)
            file_stats[file_path]["deletions"] += file_change.get("deletions", 0)

    return dict(file_stats)


def _compute_active_code(
    file_activity: dict[str, dict[str, int]],
) -> dict[str, Any]:
    """Compute active code visualization data from file activity."""
    if not file_activity:
        return _empty_active_code_response()

    # Hottest files (top 15 by commit count)
    sorted_files = sorted(
        file_activity.items(),
        key=lambda x: (x[1]["commits"], x[1]["additions"] + x[1]["deletions"]),
        reverse=True,
    )
    hottest_files = [
        {
            "path": path,
            "commits": stats["commits"],
            "additions": stats["additions"],
            "deletions": stats["deletions"],
        }
        for path, stats in sorted_files[:15]
    ]

    # Directory tree - aggregate by directory
    dir_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"commits": 0, "additions": 0, "deletions": 0, "files": set()}
    )

    for file_path, stats in file_activity.items():
        parts = file_path.split("/")
        for i in range(1, len(parts)):
            dir_path = "/".join(parts[:i])
            dir_stats[dir_path]["commits"] += stats["commits"]
            dir_stats[dir_path]["additions"] += stats["additions"]
            dir_stats[dir_path]["deletions"] += stats["deletions"]
            dir_stats[dir_path]["files"].add(file_path)

    directory_tree = [
        {
            "path": path,
            "commits": stats["commits"],
            "additions": stats["additions"],
            "deletions": stats["deletions"],
            "file_count": len(stats["files"]),
            "depth": path.count("/"),
        }
        for path, stats in sorted(
            dir_stats.items(),
            key=lambda x: (x[1]["commits"], len(x[1]["files"])),
            reverse=True,
        )
    ]

    # Quiet areas (empty for now - requires historical data)
    quiet_areas: list[dict[str, Any]] = []

    return {
        "hottest_files": hottest_files,
        "directory_tree": directory_tree,
        "quiet_areas": quiet_areas,
        "total_files_changed": len(file_activity),
    }


def _empty_active_code_response() -> dict[str, Any]:
    """Return an empty active code response."""
    return {
        "hottest_files": [],
        "directory_tree": [],
        "quiet_areas": [],
        "total_files_changed": 0,
    }
