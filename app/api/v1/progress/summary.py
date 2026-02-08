"""Progress API: Summary endpoint."""

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
from .types import ContributorStats, FocusArea
from .utils import generate_daily_activity

router = APIRouter()


@router.get("/products/{product_id}/summary")
async def get_progress_summary(
    product_id: uuid_pkg.UUID,
    period: str = Query("7d", description="Time period: 24h, 48h, 7d, 14d, 30d, 90d, 365d"),
    repo_ids: str | None = Query(None, description="Comma-separated repository IDs to filter"),
    _access_ctx: ProductAccessContext = Depends(get_product_access),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    """Get progress summary for a product.

    Returns aggregated statistics including:
    - Total commits, contributors, additions, deletions
    - Focus areas (top directories by commit count)
    - Top contributors with their stats
    - Daily activity breakdown (for sparkline)
    - Recent commits preview
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
        return _empty_summary_response()

    # Fetch commit stats for LOC calculation
    events = await fetch_commit_stats(db, result.github, result.repos, result.events)

    # Compute aggregations
    return _compute_summary(events, period)


def _compute_summary(events: list[TimelineEvent], period: str) -> dict[str, Any]:
    """Compute summary statistics from events."""
    # Sort events by timestamp (newest first)
    events.sort(key=lambda e: e.timestamp, reverse=True)

    # Aggregate stats
    total_commits = len(events)
    total_additions = sum(e.additions or 0 for e in events)
    total_deletions = sum(e.deletions or 0 for e in events)

    # Unique contributors
    contributors: dict[str, ContributorStats] = {}
    for event in events:
        author = event.commit_author
        if author not in contributors:
            contributors[author] = ContributorStats(
                author=author,
                avatar_url=event.commit_author_avatar,
                commits=0,
                additions=0,
                deletions=0,
                files_changed=0,
            )
        stats = contributors[author]
        stats.commits += 1
        stats.additions += event.additions or 0
        stats.deletions += event.deletions or 0
        stats.files_changed += event.files_changed or 0

    total_contributors = len(contributors)

    # Top contributors (sorted by commits, top 5)
    top_contributors = sorted(contributors.values(), key=lambda c: c.commits, reverse=True)[:5]

    # Focus areas (aggregate by repository name as proxy)
    focus_area_counts: dict[str, int] = defaultdict(int)
    for event in events:
        focus_area_counts[event.repository_name] += 1

    focus_areas = [
        FocusArea(path=path, commits=count)
        for path, count in sorted(focus_area_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    ]

    # Daily activity breakdown
    daily_counts: dict[str, int] = defaultdict(int)
    for event in events:
        date = event.timestamp.split("T")[0]
        daily_counts[date] += 1

    # Generate all days in period for sparkline (even if 0 commits)
    daily_activity = generate_daily_activity(daily_counts, period)

    # Recent commits (top 5)
    recent_commits = [
        {
            "id": e.id,
            "sha": e.commit_sha[:7],
            "message": e.commit_message,
            "author": e.commit_author,
            "author_avatar": e.commit_author_avatar,
            "repository": e.repository_name,
            "timestamp": e.timestamp,
            "url": e.commit_url,
            "additions": e.additions,
            "deletions": e.deletions,
        }
        for e in events[:5]
    ]

    return {
        "total_commits": total_commits,
        "total_contributors": total_contributors,
        "total_additions": total_additions,
        "total_deletions": total_deletions,
        "focus_areas": [asdict(fa) for fa in focus_areas],
        "top_contributors": [asdict(tc) for tc in top_contributors],
        "daily_activity": daily_activity,
        "recent_commits": recent_commits,
    }


def _empty_summary_response() -> dict[str, Any]:
    """Return an empty summary response."""
    return {
        "total_commits": 0,
        "total_contributors": 0,
        "total_additions": 0,
        "total_deletions": 0,
        "focus_areas": [],
        "top_contributors": [],
        "daily_activity": [],
        "recent_commits": [],
    }
