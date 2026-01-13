"""Timeline API endpoints."""

import asyncio
import uuid as uuid_pkg
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.domain import product_ops, repository_ops
from app.models import User
from app.models.repository import Repository
from app.services.github import GitHubReadOperations
from app.services.github.timeline_types import TimelineEvent

router = APIRouter(prefix="/timeline", tags=["timeline"])


@router.get("/products/{product_id}")
async def get_product_timeline(
    product_id: uuid_pkg.UUID,
    cursor: str | None = Query(None, description="Pagination cursor (timestamp:sha)"),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get development timeline for a product."""

    # 1. Verify product access
    product = await product_ops.get_by_user(db, user_id=current_user.id, id=product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # 2. Get GitHub-linked repositories
    repos = await repository_ops.get_github_repos_by_product(
        db, user_id=current_user.id, product_id=product_id
    )
    if not repos:
        return {"events": [], "has_more": False, "next_cursor": None}

    # 3. Get GitHub token
    github_token = current_user.preferences.github_token if current_user.preferences else None
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
            owner, name, repo.default_branch, per_page=limit
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

    # 7. Sort by timestamp (newest first) and paginate
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

    return {
        "events": [e.__dict__ for e in events],
        "has_more": has_more,
        "next_cursor": next_cursor,
    }
