"""Timeline API endpoints (serves Progress tab)."""

import asyncio
import uuid as uuid_pkg
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ProductAccessContext, get_current_user, get_db_with_rls, get_product_access
from app.domain import commit_stats_cache_ops, repository_ops
from app.domain.preferences_operations import preferences_ops
from app.models import User
from app.models.repository import Repository
from app.services.github import GitHubReadOperations
from app.services.github.timeline_types import TimelineEvent

router = APIRouter(prefix="/timeline", tags=["timeline"])

# Concurrency limit for fetching commit stats (avoid rate limiting)
MAX_CONCURRENT_STAT_FETCHES = 10


@router.get("/products/{product_id}")
async def get_product_timeline(
    product_id: uuid_pkg.UUID,
    cursor: str | None = Query(None, description="Pagination cursor (timestamp:sha)"),
    limit: int = Query(50, ge=1, le=100),
    repo_ids: str | None = Query(None, description="Comma-separated repository IDs to filter"),
    author: str | None = Query(None, description="Filter by commit author name (partial match)"),
    since: str | None = Query(None, description="Filter commits since date (ISO 8601)"),
    until: str | None = Query(None, description="Filter commits until date (ISO 8601)"),
    file_path: str | None = Query(None, description="Filter commits touching this file path"),
    _access_ctx: ProductAccessContext = Depends(get_product_access),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    """Get development timeline for a product with optional filters."""
    # access_ctx verifies product access (raises 404 if not found, 403 if no access)

    # 2. Get GitHub-linked repositories (RLS enforces product access)
    repos = await repository_ops.get_github_repos_by_product(db, product_id=product_id)
    if not repos:
        return {"events": [], "has_more": False, "next_cursor": None}

    # 2b. Filter repositories if repo_ids provided
    if repo_ids:
        filter_ids = set(repo_ids.split(","))
        repos = [r for r in repos if str(r.id) in filter_ids]
        if not repos:
            return {"events": [], "has_more": False, "next_cursor": None}

    # 3. Get GitHub token (decrypted)
    preferences = await preferences_ops.get_by_user_id(db, current_user.id)
    github_token = preferences_ops.get_decrypted_token(preferences) if preferences else None
    if not github_token:
        raise HTTPException(status_code=400, detail="GitHub token required")

    # 4. Fetch commits from all repos in parallel
    github = GitHubReadOperations(github_token)

    async def fetch_repo_commits(
        repo: Repository,
    ) -> list[tuple[Repository, dict[str, Any]]]:
        if not repo.full_name:
            return []
        owner, name = repo.full_name.split("/")
        commits, _ = await github.get_commits_for_timeline(
            owner, name, repo.default_branch, per_page=limit, path=file_path
        )
        return [(repo, c) for c in commits]

    results = await asyncio.gather(
        *[fetch_repo_commits(r) for r in repos],
        return_exceptions=True,
    )

    # 5. Flatten and filter errors
    all_commits: list[tuple[Repository, dict[str, Any]]] = []
    for result in results:
        if isinstance(result, BaseException):
            continue  # Skip failed repos
        all_commits.extend(result)

    # 6. Convert to TimelineEvent and sort
    events = []
    for repo, commit in all_commits:
        events.append(
            TimelineEvent(
                id=f"commit:{commit['sha']}",
                event_type="commit",
                timestamp=commit["commit"]["committer"]["date"],
                repository_id=str(repo.id),
                repository_name=repo.name or "",
                repository_full_name=repo.full_name or "",
                commit_sha=commit["sha"],
                commit_message=commit["commit"]["message"].split("\n")[0][:100],
                commit_author=commit["commit"]["author"]["name"],
                commit_author_avatar=(
                    commit["author"]["avatar_url"] if commit.get("author") else None
                ),
                commit_url=commit["html_url"],
            )
        )

    # 7. Apply filters
    # Filter by author (case-insensitive partial match)
    if author:
        author_lower = author.lower()
        events = [e for e in events if author_lower in e.commit_author.lower()]

    # Filter by date range
    if since:
        events = [e for e in events if e.timestamp >= since]
    if until:
        # Add time component if not present for inclusive end date
        until_ts = until if "T" in until else f"{until}T23:59:59Z"
        events = [e for e in events if e.timestamp <= until_ts]

    # 8. Sort by timestamp (newest first) and paginate
    events.sort(key=lambda e: e.timestamp, reverse=True)

    # Apply cursor if provided
    if cursor:
        cursor_ts, cursor_sha = cursor.rsplit(":", 1)
        idx = next(
            (
                i
                for i, e in enumerate(events)
                if e.timestamp <= cursor_ts and e.commit_sha != cursor_sha
            ),
            len(events),
        )
        events = events[idx:]

    # Limit results
    has_more = len(events) > limit
    events = events[:limit]

    # Build next cursor
    next_cursor = None
    if has_more and events:
        last = events[-1]
        next_cursor = f"{last.timestamp}:{last.commit_sha}"

    # 8. Fetch commit stats: cache-first, then GitHub API for misses
    # Build a map of repo full_name -> (owner, repo_name) for stat fetching
    repo_map: dict[str, tuple[str, str]] = {}
    for repo in repos:
        if repo.full_name:
            owner_name, repo_name = repo.full_name.split("/")
            repo_map[repo.full_name] = (owner_name, repo_name)

    # 8a. Build lookup keys for all events
    lookup_keys = [(e.repository_full_name, e.commit_sha) for e in events]

    # 8b. Bulk fetch from cache
    cached_stats = await commit_stats_cache_ops.get_bulk_by_repo_shas(db, lookup_keys)

    # 8c. Identify cache misses and populate hits
    events_needing_fetch: list[TimelineEvent] = []
    for event in events:
        key = (event.repository_full_name, event.commit_sha)
        if key in cached_stats:
            cached = cached_stats[key]
            event.additions = cached.additions
            event.deletions = cached.deletions
            event.files_changed = cached.files_changed
        else:
            events_needing_fetch.append(event)

    # 8d. Fetch missing stats from GitHub (with concurrency limit)
    if events_needing_fetch:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_STAT_FETCHES)
        stats_to_cache: list[dict[str, str | int]] = []

        async def fetch_and_cache_stats(event: TimelineEvent) -> None:
            """Fetch stats from GitHub and queue for caching."""
            repo_info = repo_map.get(event.repository_full_name)
            if not repo_info:
                return
            owner_name, repo_name = repo_info

            async with semaphore:
                stats = await github.get_commit_detail(owner_name, repo_name, event.commit_sha)
                if stats:
                    event.additions = stats["additions"]
                    event.deletions = stats["deletions"]
                    event.files_changed = stats["files_changed"]
                    stats_to_cache.append(
                        {
                            "full_name": event.repository_full_name,
                            "sha": event.commit_sha,
                            "additions": stats["additions"],
                            "deletions": stats["deletions"],
                            "files_changed": stats["files_changed"],
                        }
                    )

        await asyncio.gather(
            *[fetch_and_cache_stats(e) for e in events_needing_fetch],
            return_exceptions=True,
        )

        # 8e. Bulk insert newly fetched stats into cache
        if stats_to_cache:
            await commit_stats_cache_ops.bulk_upsert(db, stats_to_cache)

    return {
        "events": [e.__dict__ for e in events],
        "has_more": has_more,
        "next_cursor": next_cursor,
    }


@router.get("/commits/{repo_full_name:path}/{sha}/files")
async def get_commit_files(
    repo_full_name: str,
    sha: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    """
    Get file changes for a specific commit.

    Used by the expandable commit details in the Commits tab.
    Returns the list of files changed in the commit with their stats.
    """
    # 1. Get GitHub token
    preferences = await preferences_ops.get_by_user_id(db, current_user.id)
    github_token = preferences_ops.get_decrypted_token(preferences) if preferences else None
    if not github_token:
        raise HTTPException(status_code=400, detail="GitHub token required")

    # 2. Parse repo full name
    if "/" not in repo_full_name:
        raise HTTPException(status_code=400, detail="Invalid repository format")

    owner, repo = repo_full_name.split("/", 1)

    # 3. Fetch commit files from GitHub
    github = GitHubReadOperations(github_token)
    files = await github.get_commit_files(owner, repo, sha)

    if files is None:
        raise HTTPException(status_code=404, detail="Commit not found or fetch failed")

    return {"files": files}
