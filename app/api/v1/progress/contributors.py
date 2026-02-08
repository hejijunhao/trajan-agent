"""Progress API: Contributors endpoint."""

import uuid as uuid_pkg
from collections import defaultdict
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    ProductAccessContext,
    get_current_user,
    get_db_with_rls,
    get_product_access,
)
from app.models import User
from app.services.github.timeline_types import TimelineEvent

from .commit_fetcher import fetch_commit_stats, fetch_product_commits
from .types import ContributorDetail
from .utils import generate_daily_activity

router = APIRouter()


@router.get("/products/{product_id}/contributors")
async def get_progress_contributors(
    product_id: uuid_pkg.UUID,
    period: str = Query("7d", description="Time period: 24h, 48h, 7d, 14d, 30d, 90d, 365d"),
    repo_ids: str | None = Query(None, description="Comma-separated repository IDs to filter"),
    sort_by: str = Query("commits", description="Sort by: commits, additions, last_active"),
    _access_ctx: ProductAccessContext = Depends(get_product_access),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    """Get detailed contributor statistics for a product.

    Returns per-contributor breakdown including:
    - Stats: commits, LOC, files changed
    - Last active timestamp
    - Focus areas (top 3 directories)
    - Activity sparkline (daily commits)
    - Recent commits (last 3)
    """
    # Fetch commits using consolidated fetcher
    result = await fetch_product_commits(
        db=db,
        product_id=product_id,
        current_user=current_user,
        period=period,
        repo_ids=repo_ids,
        fetch_limit=200,
    )

    if not result:
        return {"contributors": []}

    # Fetch commit stats for LOC calculation
    events = await fetch_commit_stats(db, result.github, result.repos, result.events)

    # Compute per-contributor details
    contributors = _compute_contributors(events, period, sort_by)

    return {"contributors": contributors}


def _compute_contributors(
    events: list[TimelineEvent], period: str, sort_by: str
) -> list[dict[str, Any]]:
    """Compute detailed per-contributor statistics."""
    # Sort events by timestamp (newest first) for last_active and recent_commits
    events.sort(key=lambda e: e.timestamp, reverse=True)

    # Group events by author
    author_events: dict[str, list[TimelineEvent]] = defaultdict(list)
    for event in events:
        author_events[event.commit_author].append(event)

    contributors: list[ContributorDetail] = []

    for author, author_commits in author_events.items():
        # Basic stats
        commits = len(author_commits)
        additions = sum(e.additions or 0 for e in author_commits)
        deletions = sum(e.deletions or 0 for e in author_commits)
        files_changed = sum(e.files_changed or 0 for e in author_commits)

        # Avatar (take from first commit)
        avatar_url = author_commits[0].commit_author_avatar if author_commits else None

        # Last active (already sorted newest first)
        last_active = author_commits[0].timestamp if author_commits else ""

        # Focus areas (top 3 repositories for this author)
        repo_counts: dict[str, int] = defaultdict(int)
        for event in author_commits:
            repo_counts[event.repository_name] += 1
        focus_areas = [
            repo for repo, _ in sorted(repo_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        ]

        # Daily activity (sparkline)
        daily_counts: dict[str, int] = defaultdict(int)
        for event in author_commits:
            date = event.timestamp.split("T")[0]
            daily_counts[date] += 1
        daily_activity = generate_daily_activity(daily_counts, period)

        # Recent commits (last 3)
        recent_commits = [
            {
                "sha": e.commit_sha[:7],
                "message": e.commit_message,
                "repository": e.repository_name,
                "timestamp": e.timestamp,
                "url": e.commit_url,
            }
            for e in author_commits[:3]
        ]

        contributors.append(
            ContributorDetail(
                author=author,
                avatar_url=avatar_url,
                commits=commits,
                additions=additions,
                deletions=deletions,
                files_changed=files_changed,
                last_active=last_active,
                focus_areas=focus_areas,
                daily_activity=daily_activity,
                recent_commits=recent_commits,
            )
        )

    # Sort contributors
    if sort_by == "additions":
        contributors.sort(key=lambda c: c.additions, reverse=True)
    elif sort_by == "last_active":
        contributors.sort(key=lambda c: c.last_active, reverse=True)
    else:  # Default: commits
        contributors.sort(key=lambda c: c.commits, reverse=True)

    return [asdict(c) for c in contributors]
